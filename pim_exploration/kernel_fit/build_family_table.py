#!/usr/bin/env python
"""Kernel-family table for TPC-H Q2-Q22 (SF1) joined from ncu per-launch counters and nsys real-clock durations.

Run:  /home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I build_family_table.py  (venv has numpy+matplotlib only; no pandas)
Outputs (same directory): launches_all.csv, kernel_families.csv, tier_shares.csv, bw_bound.csv, sass_opcode_mix.csv,
                          stats.json, tier_shares.png

Columns prefixed ncu_ come from ncu_warm_metrics.json (serialized, clock-locked, L2 flushed before every kernel).
Columns prefixed nsys_ come from warm_kernel_list.json (real clock).  They are never combined arithmetically; the only
cross-use is *selecting* launches with an ncu flag (e.g. dram_pct >= x) and summing their nsys durations.

Join: ncu `kernels[]` and nsys list have the same length per query (= summary kernels), but the ORDER differs in 13 of 21
queries (ncu serializes the 4 pipeline threads, nsys shows concurrent launches).  Join = k-th occurrence of
(name, grid, block) in each list; leftovers = k-th occurrence of name.  Positional name mismatches are counted.
"""
import json, re, os, collections, csv
import numpy as np

R = '/home/sai/cs254_project/tpch_q1_analysis/analysis/results'
OUT = os.path.dirname(os.path.abspath(__file__))
QS = list(range(2, 23))

# ---------------------------------------------------------------- family classification
def short(n):
    return re.sub(r'std::|cuda::|thrust::|cudf::|__detail::|cub::|policy_selector_from_types', '', n)

def tx_in_type(n):
    m = re.search(r'tuple<(thrust::permutation_iterator<)?(?:const )?([A-Za-z_:<>0-9 ,]*?)(?: \*|,|>)', n)
    return m

def family(name, func):
    n = name
    s = short(name)
    if func == 'transform_kernel':
        if 'convert_to_rep' in n: return 'transform: dyn-filter key convert (convert_to_rep)'
        if 'encode_fn' in n: return 'transform: dictionary encode (cuco set find)'
        if re.search(r'strings::|substring|string', n): return 'transform: string op (substr etc.)'
        if re.search(r'__return_constant|compute_sequence|counting_iterator<long, __int128>', n) and 'permutation_iterator' not in n.split('always_true')[0]:
            return 'transform: fill constant / sequence'
        m = re.search(r'tuple<thrust::permutation_iterator<(const )?([A-Za-z_ :]*?)( \*|,)', n)
        if m and 'always_true, std::identity' in n:
            t = m.group(2).strip()
            if t.startswith('cudf::input_indexalator'): return 'transform: gather index-column (indexalator)'
            if t == '__int128': return 'transform: gather fixed-width 16 B'
            if t in ('long', 'double'): return 'transform: gather fixed-width 8 B'
            return 'transform: gather fixed-width 1-4 B'
        if 'fixed_point_unary_cast' in n or 'device_cast<long, __int128>' in n or 'device_cast<__int128' in n or '__int128' in n.split('always_true')[0] and 'cast' in n:
            return 'transform: cast decimal/wide (to/from int128, fixed_point)'
        if re.search(r'unary_cast|device_cast', n): return 'transform: cast integral widen'
        if 'datetime::' in n: return 'transform: datetime extract'
        if 'permutation_iterator<' in n.split('always_true')[0]: return 'transform: small scatter (flags/sequence)'
        return 'transform: misc elementwise (not/unique flag/other)'
    if func == 'static_kernel':
        if 'initialize_functor' in n: return 'for_each: cuco hash-table init (fill)'
        m = re.search(r'binops::(Mul|Sub|Add|Div)>', n)
        if m: return 'for_each: binop mul/div' if m.group(1) in ('Mul', 'Div') else 'for_each: binop add/sub'
        if re.search(r'binops::(Equal|Greater|LessEqual|Less)>', n): return 'for_each: binop compare'
        if re.search(r'compute_single_pass_aggs|compute_groupby', n): return 'for_each: group-by hash aggregate'
        if 'needle_lookup' in n: return 'for_each: dyn-filter membership (needle, small set)'
        if 'set_lookup' in n: return 'for_each: dyn-filter membership (cuco set)'
        if 'bloom_lookup' in n: return 'for_each: dyn-filter membership (bloom)'
        if 'binary_search_functor' in n: return 'for_each: binary search (lower_bound)'
        return 'for_each: fill / label_segments / misc'
    if func in ('DeviceScanInitKernel', 'DeviceCompactInitKernel', 'InitTileStateKernel', 'DeviceRadixSortInitKernel'):
        return 'cub: tile-state / histogram init'
    if func == 'DeviceScanKernel':
        if 'string_offsets_fn' in n: return 'cub scan: string offsets (gather-strings sizes)'
        if 'make_offsets_child_column' in n: return 'cub scan: constant-size offsets'
        if 'sizes_to_offsets_iterator<long *' in n or 'sizes_to_offsets_iterator<long*' in n: return 'cub scan: long sizes -> offsets'
        return 'cub scan: int exclusive sum (positions)'
    if func == 'DeviceSelectSweepKernel':
        if 'retention_mask_filter' in n: return 'cub select: boolean-mask compaction'
        if 'gather_mask' in n: return 'cub select: gather_mask compaction'
        if 'distinct_hash_join' in n: return 'cub select: hash-join output compaction'
        if 'slot_is_filled' in n: return 'cub select: hash-table slot extract'
        return 'cub select: other'
    if func == 'DeviceReduceKernel': return 'cub reduce: block partial (min/max, sum)'
    if func in ('DeviceReduceSingleTileKernel', 'single_thread_kernel', 'DeviceReduceByKeyKernel') and func != 'DeviceReduceByKeyKernel':
        return 'cub reduce: final single-tile / assign_min_max'
    if func == '_kernel_agent' or func == 'DeviceReduceByKeyKernel': return 'cub reduce-by-key (sort-based group-by)'
    if func == 'DeviceMergeSortBlockSortKernel': return 'sort: merge-sort block sort'
    if func == 'DeviceMergeSortPartitionKernel': return 'sort: merge-sort partition'
    if func == 'DeviceMergeSortMergeKernel': return 'sort: merge-sort merge'
    if func in ('DeviceRadixSortOnesweepKernel', 'DeviceRadixSortSingleTileKernel', 'DeviceRadixSortHistogramKernel', 'DeviceRadixSortExclusiveSumKernel'):
        return 'sort: radix sort'
    if func.startswith('DeviceTopK'): return 'sort: top-k'
    if func == 'insert_if_n':
        if 'rhs_index_type' in n: return 'cuco: hash-join build insert (pair)'
        if 'filtered_join' in n: return 'cuco: semi-join build insert (filtered_join)'
        return 'cuco: dyn-filter key-set insert'
    if func == 'add_if_n': return 'cuco: bloom-filter add (dyn filter build)'
    if func == 'find_if_n': return 'cuco: hash-join probe find'
    if func == 'contains_if_n': return 'cuco: semi-join probe contains'
    if func.startswith('hash_csr_build'): return 'csr join: build (' + func.split('_')[3] + ')'
    if func.startswith('hash_csr_probe') or func == 'hash_csr_retrieve_kernel':
        return 'csr join: probe count' if 'probe_count' in func else 'csr join: retrieve'
    if func == 'fused_membership_mask_kernel': return 'sirius: fused membership mask (dyn filter)'
    if func == 'compute_column_kernel':
        return 'AST compute_column (has_null)' if re.search(r'compute_column_kernel<128, 1', n) else 'AST compute_column (no nulls)'
    if func == 'gather_chars_fn_char_parallel': return 'strings: gather chars (char-parallel)'
    if func == 'gather_chars_fn_string_parallel': return 'strings: gather chars (string-parallel)'
    if func == 'single_pass_shmem_aggs_kernel': return 'groupby: single_pass_shmem_aggs'
    if func == 'mapping_indices_kernel': return 'groupby: mapping_indices (cuco insert+find)'
    if func == 'add_if_shmem': return 'hyperloglog add_if_shmem'
    if func in ('copy_range_kernel',): return 'copy_range (constant fill)'
    if func in ('fused_concatenate_kernel', 'fused_concatenate_string_offset_kernel', 'fused_concatenate_string_chars_kernel',
                'BatchMemcpyKernel', 'MultiBlockBatchMemcpyKernel'): return 'copy / concatenate'
    if func in ('valid_if_n_kernel', 'valid_if_kernel'): return 'validity bitmask build (valid_if)'
    if func == 'copy_if_else_kernel': return 'copy_if_else'
    if func == 'like_multiliteral_kernel': return 'strings: LIKE multi-literal'
    if func in ('find_kernel', 'init_found_pos_pointer'): return 'thrust find (is-sorted / first-less)'
    if func in ('accumulate_kernel', 'emit_kernel'): return 'sirius: dense-count join accumulate/emit'
    if func in ('filter_join_indices_kernel', 'compute_conditional_join_output_size', 'conditional_join', 'mixed_join_semi'):
        return 'join: conditional / mixed (AST) join'
    return 'other: ' + func

# ---------------------------------------------------------------- family attributes (INFERENCE; rules in the final report)
# pattern codes: SEQ stream, COMPACT (stream read, data-dependent seq write), GATHER (index-driven random read),
#                RANDW (random write / atomic), TINY
# compute codes: BIT (bitwise/compare), INTADD, HASH, WIDE (64/128-bit mul/div/ decimal), FP, STR (string/bytewise control flow)
A = {}
def a(f, pat, comp, tier, why, prim, hw):
    A[f] = dict(pattern=pat, compute=comp, tier=tier, why=why, primitive=prim, hw_need=hw)

a('transform: gather fixed-width 1-4 B', 'GATHER', 'INTADD', 'T3', 'index-driven read across a whole column; output sequential', 'gather', 'address indirection (bank-spanning reads)')
a('transform: gather fixed-width 8 B', 'GATHER', 'INTADD', 'T3', 'same as 1-4 B gather, 8 B elements', 'gather', 'address indirection')
a('transform: gather fixed-width 16 B', 'GATHER', 'INTADD', 'T3', 'gather of decimal128 columns', 'gather', 'address indirection')
a('transform: gather index-column (indexalator)', 'GATHER', 'INTADD', 'T3', 'gather of an index column by an index column', 'gather', 'address indirection')
a('transform: cast integral widen', 'SEQ', 'BIT', 'T1', 'sequential read/write, sign-extend only', 'map (unary cast)', 'element-wise unit (width conversion)')
a('transform: cast decimal/wide (to/from int128, fixed_point)', 'SEQ', 'WIDE', 'T2', 'sequential but 128-bit/rescale arithmetic', 'map (cast)', 'wide integer unit')
a('transform: datetime extract', 'SEQ', 'INTADD', 'T2', 'sequential; calendar arithmetic with integer divides', 'map (date part)', 'integer divider')
a('transform: fill constant / sequence', 'SEQ', 'BIT', 'T1', 'write-only sequential stream of constant or iota', 'fill / iota', 'row-buffer write')
a('transform: small scatter (flags/sequence)', 'RANDW', 'INTADD', 'T3', 'scatter by index (permutation_iterator on output)', 'scatter', 'address indirection (write)')
a('transform: misc elementwise (not/unique flag/other)', 'SEQ', 'BIT', 'T1', 'boolean not / adjacent-compare flags, sequential', 'map / adjacent-diff', 'comparator')
a('transform: dyn-filter key convert (convert_to_rep)', 'SEQ', 'BIT', 'T1', 'sequential reinterpret/convert of join keys', 'map', 'element-wise unit')
a('transform: dictionary encode (cuco set find)', 'GATHER', 'HASH', 'T3', 'hash lookup per row into a table', 'hash probe', 'hash unit + indirection')
a('transform: string op (substr etc.)', 'GATHER', 'STR', 'T5', 'string-view construction, byte-wise', 'string substr', 'not general')
a('for_each: cuco hash-table init (fill)', 'SEQ', 'BIT', 'T1', 'write-only constant fill of the table', 'fill (table init)', 'row-buffer write / memset')
a('for_each: binop mul/div', 'SEQ', 'WIDE', 'T2', 'sequential, but multiply/divide (decimal)', 'map (arith)', 'multiplier / wide ALU')
a('for_each: binop add/sub', 'SEQ', 'INTADD', 'T1', 'sequential, add/sub', 'map (arith)', 'adder')
a('for_each: binop compare', 'SEQ', 'BIT', 'T1', 'sequential compare producing bool column', 'filter predicate', 'comparator')
a('for_each: group-by hash aggregate', 'RANDW', 'HASH', 'T3', 'hash insert/atomic update per row', 'hash aggregate', 'hash unit + atomic add across banks')
a('for_each: dyn-filter membership (needle, small set)', 'SEQ', 'BIT', 'T1', 'few needles: compare against a tiny constant set', 'filter predicate (IN-list)', 'comparator + small constant CAM')
a('for_each: dyn-filter membership (cuco set)', 'GATHER', 'HASH', 'T3', 'hash probe of a key set per row', 'hash probe (semi-join filter)', 'hash unit + indirection')
a('for_each: dyn-filter membership (bloom)', 'GATHER', 'HASH', 'T3', 'bloom bit-test at hashed addresses', 'hash probe (bloom)', 'hash unit + indirection')
a('for_each: binary search (lower_bound)', 'GATHER', 'INTADD', 'T3', 'log n dependent random reads into sorted array', 'binary search', 'address indirection')
a('for_each: fill / label_segments / misc', 'TINY', 'BIT', 'T4', 'small fills / segment labelling', 'fill', 'none')
a('cub: tile-state / histogram init', 'TINY', 'BIT', 'T4', 'bookkeeping, single/few blocks', 'none (launch overhead)', 'none')
a('cub scan: string offsets (gather-strings sizes)', 'SEQ', 'INTADD', 'T2', 'sequential but prefix-sum with data-dependent chain + fused string_offsets_fn gather of sizes', 'prefix sum (scan)', 'adder chain across banks')
a('cub scan: constant-size offsets', 'SEQ', 'INTADD', 'T2', 'prefix sum of constants', 'prefix sum (scan)', 'adder chain')
a('cub scan: long sizes -> offsets', 'SEQ', 'INTADD', 'T2', 'prefix sum', 'prefix sum (scan)', 'adder chain')
a('cub scan: int exclusive sum (positions)', 'SEQ', 'INTADD', 'T2', 'prefix sum; carries across blocks (decoupled look-back)', 'prefix sum (scan)', 'adder chain')
a('cub select: boolean-mask compaction', 'COMPACT', 'INTADD', 'T2', 'streaming read, data-dependent write position', 'compact', 'popcount/prefix + write pointer')
a('cub select: gather_mask compaction', 'COMPACT', 'INTADD', 'T2', 'streaming read, data-dependent write position', 'compact', 'popcount/prefix + write pointer')
a('cub select: hash-join output compaction', 'COMPACT', 'HASH', 'T2', 'streaming predicate over match flags, data-dependent output', 'compact', 'prefix + write pointer')
a('cub select: hash-table slot extract', 'COMPACT', 'BIT', 'T2', 'streaming scan of table slots, keep filled ones', 'compact', 'compare + write pointer')
a('cub select: other', 'COMPACT', 'INTADD', 'T2', 'compaction', 'compact', 'prefix + write pointer')
a('cub reduce: block partial (min/max, sum)', 'SEQ', 'INTADD', 'T1', 'sequential read, reduce tree', 'reduce (min/max/sum)', 'adder / comparator tree')
a('cub reduce: final single-tile / assign_min_max', 'TINY', 'INTADD', 'T4', 'single block / single thread finalize', 'none (launch overhead)', 'none')
a('cub reduce-by-key (sort-based group-by)', 'SEQ', 'INTADD', 'T2', 'sequential segmented reduce with data-dependent output', 'segmented reduce', 'adder + boundary compare')
a('sort: merge-sort block sort', 'SEQ', 'BIT', 'T5', 'this kernel: ~23 warp-inst per DRAM byte, thread_eff ~16, in-smem comparator merge, mostly 1 CTA; sort as an operator could be redone for PIM, this kernel cannot', 'sort', 'comparator network')
a('sort: merge-sort partition', 'GATHER', 'BIT', 'T4', 'tiny merge-path binary search', 'sort', 'none')
a('sort: merge-sort merge', 'GATHER', 'BIT', 'T3', 'merge of sorted runs, read cursors data-dependent across whole array', 'sort (merge)', 'comparator + indirection')
a('sort: radix sort', 'SEQ', 'BIT', 'T3', 'scatter of keys by digit rank (random write)', 'sort (radix)', 'histogram + scatter')
a('sort: top-k', 'SEQ', 'BIT', 'T2', 'streaming candidate selection', 'top-k', 'comparator + histogram')
a('cuco: hash-join build insert (pair)', 'RANDW', 'HASH', 'T3', 'hash insert into table (random write + CAS)', 'hash build', 'hash unit + CAS across banks')
a('cuco: semi-join build insert (filtered_join)', 'RANDW', 'HASH', 'T3', 'hash insert', 'hash build', 'hash unit + CAS')
a('cuco: dyn-filter key-set insert', 'RANDW', 'HASH', 'T3', 'hash insert', 'hash build', 'hash unit + CAS')
a('cuco: bloom-filter add (dyn filter build)', 'RANDW', 'HASH', 'T3', 'hash + atomic OR of bits in filter', 'hash build (bloom)', 'hash unit + atomic or')
a('cuco: hash-join probe find', 'GATHER', 'HASH', 'T3', 'hash probe (random read + key compare)', 'hash probe', 'hash unit + indirection + comparator')
a('cuco: semi-join probe contains', 'GATHER', 'HASH', 'T3', 'hash probe', 'hash probe', 'hash unit + indirection')
a('csr join: build (count)', 'RANDW', 'HASH', 'T3', 'hash + atomic count per bucket', 'hash build (count)', 'hash unit + atomic add')
a('csr join: build (fill)', 'RANDW', 'HASH', 'T3', 'hash + atomic slot reservation + scatter', 'hash build (fill)', 'hash unit + atomic + scatter')
a('csr join: probe count', 'GATHER', 'HASH', 'T3', 'hash probe', 'hash probe', 'hash unit + indirection')
a('csr join: retrieve', 'GATHER', 'HASH', 'T3', 'probe + write matches', 'hash probe (emit)', 'hash unit + indirection')
a('sirius: fused membership mask (dyn filter)', 'GATHER', 'HASH', 'T3', 'hash/bloom probe producing a bitmask', 'hash probe (bloom/set)', 'hash unit + indirection')
a('AST compute_column (has_null)', 'SEQ', 'INTADD', 'T5', 'expression-tree interpreter: control flow dominates', 'map (expression)', 'generic ALU (not fixed-function)')
a('AST compute_column (no nulls)', 'SEQ', 'INTADD', 'T5', 'expression-tree interpreter: control flow dominates', 'map (expression)', 'generic ALU (not fixed-function)')
a('strings: gather chars (char-parallel)', 'GATHER', 'STR', 'T3', 'copy variable-length byte ranges by index', 'gather (strings)', 'address indirection + byte copy')
a('strings: gather chars (string-parallel)', 'GATHER', 'STR', 'T3', 'copy variable-length byte ranges by index', 'gather (strings)', 'address indirection + byte copy')
a('groupby: single_pass_shmem_aggs', 'RANDW', 'WIDE', 'T3', 'shared-mem hash aggregate, 64-bit atomic adds, per-row type dispatch', 'hash aggregate', 'atomic add + type dispatch')
a('groupby: mapping_indices (cuco insert+find)', 'RANDW', 'HASH', 'T3', 'hash insert-and-find of group keys (row hasher)', 'hash group-by (key mapping)', 'hash unit + CAS')
a('hyperloglog add_if_shmem', 'RANDW', 'HASH', 'T3', 'hash + register max in shared memory', 'approx-distinct', 'hash + max-update')
a('copy_range (constant fill)', 'SEQ', 'BIT', 'T1', 'write-only constant fill', 'fill', 'row-buffer write')
a('copy / concatenate', 'SEQ', 'BIT', 'T1', 'sequential block copy', 'copy / concat', 'bank-to-bank copy')
a('validity bitmask build (valid_if)', 'SEQ', 'BIT', 'T1', 'sequential predicate -> bitmask', 'bitmask build', 'comparator + bit-pack')
a('copy_if_else', 'SEQ', 'BIT', 'T1', 'sequential select between two columns by mask', 'select (if-else)', 'mux')
a('strings: LIKE multi-literal', 'SEQ', 'STR', 'T5', 'byte-wise substring match, divergent', 'string match', 'not general')
a('thrust find (is-sorted / first-less)', 'TINY', 'BIT', 'T4', 'short search / init pointer', 'search', 'none')
a('sirius: dense-count join accumulate/emit', 'RANDW', 'INTADD', 'T3', 'atomic count per dense key, then emit', 'dense hash count', 'atomic add')
a('join: conditional / mixed (AST) join', 'GATHER', 'INTADD', 'T5', 'AST-evaluated nested-loop style join', 'conditional join', 'generic ALU')

# ---------------------------------------------------------------- load & join
NCU_COLS = ['dur_ns', 'dram_rd', 'dram_wr', 'dram_bytes', 'dram_pct', 'achieved_bw_gbs', 'l2_hit', 'l1_hit', 'inst',
            'inst_per_byte', 'ipc', 'ld_glob', 'st_glob', 'atom_glob', 'red_glob', 'ldreq_glob', 'streq_glob', 'waves',
            'grid', 'block', 'thread_eff', 'occ_ach', 'sm_active_frac', 'pipe_alu', 'pipe_fma', 'pipe_lsu', 'pipe_xu',
            'pipe_fp64', 'pipe_adu', 'pipe_cbu', 'regs']
rows = []
join_report = {}
summ = {r['q']: r for r in json.load(open(f'{R}/summary/summary_data.json'))}
for q in QS:
    nc = json.load(open(f'{R}/q{q}/ncu_warm_metrics.json'))['kernels']
    ns = json.load(open(f'{R}/q{q}/warm_kernel_list.json'))
    assert len(nc) == len(ns) == summ[q]['kernels'], (q, len(nc), len(ns), summ[q]['kernels'])
    pos_mis = sum(a_['name'] != b_['name'] for a_, b_ in zip(nc, ns))
    k1 = lambda k: (k['name'], k['grid'], k['block'])
    k2 = lambda k: k['name']
    dn = collections.defaultdict(list)
    for j, k in enumerate(ns): dn[k1(k)].append(j)
    match, used, cnt = {}, set(), collections.Counter()
    for i, k in enumerate(nc):
        key = k1(k); j = cnt[key]; cnt[key] += 1
        if j < len(dn[key]): match[i] = dn[key][j]; used.add(dn[key][j])
    left_ns = collections.defaultdict(list)
    for j, k in enumerate(ns):
        if j not in used: left_ns[k2(k)].append(j)
    for i, k in enumerate(nc):
        if i in match: continue
        if left_ns[k2(k)]: match[i] = left_ns[k2(k)].pop(0)
    # third pass: same func+grid+block but different demangled name (thrust fill functor: ncu 'cuda_cub::functor<int*,int>'
    # vs nsys '__uninitialized_fill::functor<int*,int>')
    used2 = set(match.values())
    left3 = collections.defaultdict(list)
    for j, k in enumerate(ns):
        if j not in used2: left3[(k['func'], k['grid'], k['block'])].append(j)
    renamed = 0; unmatched = 0
    for i, k in enumerate(nc):
        if i in match: continue
        key = (k['func'], k['grid'], k['block'])
        if left3[key]: match[i] = left3[key].pop(0); renamed += 1
        else: unmatched += 1
    exact3 = sum(1 for i, j in match.items() if k1(nc[i]) == k1(ns[j]))
    join_report[q] = dict(kernels=len(nc), summary_kernels=summ[q]['kernels'], positional_name_mismatch=pos_mis,
                          unmatched=unmatched, joined_by_func_grid_block_only=renamed, matched_name_grid_block=exact3)
    for i, k in enumerate(nc):
        j = match.get(i)
        fam_ = family(k['name'], k['func'])
        r = dict(q=q, pos=k['pos'], func=k['func'], family=fam_, pattern=A[fam_]['pattern'], compute=A[fam_]['compute'],
                 tier=A[fam_]['tier'], tier_reason=A[fam_]['why'], name_short=short(k['name'])[:160],
                 nsys_dur_ns=ns[j]['dur_ns'] if j is not None else float('nan'),
                 nsys_id=ns[j]['id'] if j is not None else -1)
        for c in NCU_COLS: r['ncu_' + c] = float(k.get(c) or 0)
        r['_stalls'] = dict(k.get('stalls') or {})
        r['ncu_single_block'] = int(k['grid'] == 1)
        r['ncu_top_stall'] = top_stall([r['_stalls']])[0] if False else ''
        rows.append(r)

def top_stall(stl_list):
    tot = collections.Counter()
    for s in stl_list:
        for k, v in s.items():
            if k in ('selected', 'not_selected'): continue
            tot[k] += v
    if not tot: return '', 0.0
    S = sum(tot.values()); k, v = tot.most_common(1)[0]
    return k, v / S
for r in rows: r['ncu_top_stall'] = top_stall([r['_stalls']])[0]

def W(path, recs, cols=None):
    cols = cols or list(recs[0].keys())
    with open(path, 'w', newline='') as f:
        w = csv.writer(f); w.writerow(cols)
        for r in recs: w.writerow([('%.6g' % r[c]) if isinstance(r[c], float) else r[c] for c in cols])

pubcols = [k for k in rows[0].keys() if k != '_stalls']
W(f'{OUT}/launches_all.csv', rows, pubcols)
W(f'{OUT}/join_report.csv', [dict(q=q, **v) for q, v in join_report.items()])

nsys = lambda g: sum(r['nsys_dur_ns'] for r in g if r['nsys_dur_ns'] == r['nsys_dur_ns'])
col = lambda g, c: np.array([r[c] for r in g], float)
med = lambda g, c: float(np.median(col(g, c)))
tot_nsys = nsys(rows)
tot_dram = col(rows, 'ncu_dram_bytes').sum()
byfam = collections.defaultdict(list)
for r in rows: byfam[r['family']].append(r)

frows = []
for f, g in byfam.items():
    top, share = top_stall([r['_stalls'] for r in g])
    qs = sorted(set(r['q'] for r in g))
    nd = np.array([r['nsys_dur_ns'] for r in g], float)
    r = dict(family=f, funcs='+'.join(sorted(set(x['func'] for x in g))), launches=len(g), queries=len(qs),
             query_list=' '.join(map(str, qs)),
             nsys_total_us=np.nansum(nd) / 1e3, nsys_median_us=float(np.nanmedian(nd)) / 1e3,
             nsys_time_share=np.nansum(nd) / tot_nsys,
             ncu_dram_rd_med_B=med(g, 'ncu_dram_rd'), ncu_dram_rd_max_B=col(g, 'ncu_dram_rd').max(),
             ncu_dram_wr_med_B=med(g, 'ncu_dram_wr'), ncu_dram_wr_max_B=col(g, 'ncu_dram_wr').max(),
             ncu_dram_rd_total_B=col(g, 'ncu_dram_rd').sum(), ncu_dram_wr_total_B=col(g, 'ncu_dram_wr').sum(),
             ncu_dram_total_B=col(g, 'ncu_dram_bytes').sum(), ncu_dram_share=col(g, 'ncu_dram_bytes').sum() / tot_dram,
             ncu_inst_per_dram_byte=col(g, 'ncu_inst').sum() / max(col(g, 'ncu_dram_bytes').sum(), 1),
             ncu_inst_per_byte_median=med(g, 'ncu_inst_per_byte'),
             ncu_bw_gbs_med=med(g, 'ncu_achieved_bw_gbs'), ncu_bw_gbs_max=col(g, 'ncu_achieved_bw_gbs').max(),
             ncu_dram_pct_med=med(g, 'ncu_dram_pct'), ncu_dram_pct_max=col(g, 'ncu_dram_pct').max(),
             ncu_l2_hit_med=med(g, 'ncu_l2_hit'), ncu_top_stall=top, ncu_top_stall_share=share,
             ncu_ld_glob_med=med(g, 'ncu_ld_glob'), ncu_st_glob_med=med(g, 'ncu_st_glob'),
             ncu_atom_glob_med=med(g, 'ncu_atom_glob'), ncu_red_glob_med=med(g, 'ncu_red_glob'),
             ncu_atom_red_total=col(g, 'ncu_atom_glob').sum() + col(g, 'ncu_red_glob').sum(),
             ncu_waves_med=med(g, 'ncu_waves'), ncu_single_block_share=col(g, 'ncu_single_block').mean(),
             ncu_thread_eff_med=med(g, 'ncu_thread_eff'),
             ncu_pipe_alu_med=med(g, 'ncu_pipe_alu'), ncu_pipe_fma_med=med(g, 'ncu_pipe_fma'),
             ncu_pipe_lsu_med=med(g, 'ncu_pipe_lsu'), ncu_pipe_xu_med=med(g, 'ncu_pipe_xu'),
             ncu_dur_total_us=col(g, 'ncu_dur_ns').sum() / 1e3,
             pattern=A[f]['pattern'], compute=A[f]['compute'], tier=A[f]['tier'], tier_reason=A[f]['why'],
             pim_primitive=A[f]['primitive'], pim_hw_need=A[f]['hw_need'])
    frows.append(r)
frows.sort(key=lambda r: -r['nsys_total_us'])
W(f'{OUT}/kernel_families.csv', frows)

T = ['T1', 'T2', 'T3', 'T4', 'T5']
def sh(g): return len(g), nsys(g) / 1e3, col(g, 'ncu_dram_bytes').sum() if g else 0.0
trows = []
byq = collections.defaultdict(list)
for r in rows: byq[r['q']].append(r)
NOBS = [r for r in rows if not r['family'].startswith('sort: merge-sort block sort')]
for q, g in list(byq.items()) + [('ALL', rows), ('ALL_excl_block_sort', NOBS)]:
    tl, tn, td = sh(g)
    for t in T:
        s = [r for r in g if r['tier'] == t]
        l, n, d = sh(s)
        trows.append(dict(query=q, tier=t, launches=l, launch_share=l / tl, nsys_us=n, nsys_time_share=n / tn,
                          ncu_dram_B=d, ncu_dram_share=d / td))
for t in T:   # unweighted mean over the 21 queries of the per-query shares
    pq = [x for x in trows if x['tier'] == t and x['query'] in QS]
    trows.append(dict(query='MEAN_OF_QUERIES', tier=t, launches=sum(x['launches'] for x in pq), launch_share=np.mean([x['launch_share'] for x in pq]),
                      nsys_us=sum(x['nsys_us'] for x in pq), nsys_time_share=np.mean([x['nsys_time_share'] for x in pq]),
                      ncu_dram_B=sum(x['ncu_dram_B'] for x in pq), ncu_dram_share=np.mean([x['ncu_dram_share'] for x in pq])))
W(f'{OUT}/tier_shares.csv', trows)

bw = []
for q, g in list(byq.items()) + [('ALL', rows)]:
    for th in (25, 50, 75):
        m = [r for r in g if r['ncu_dram_pct'] >= th]
        bw.append(dict(query=q, threshold_pct=th, kernels=len(m), kernel_share=len(m) / len(g),
                       nsys_time_share_of_those=nsys(m) / nsys(g),
                       ncu_dram_share_of_those=col(m, 'ncu_dram_bytes').sum() / col(g, 'ncu_dram_bytes').sum() if m else 0.0))
W(f'{OUT}/bw_bound.csv', bw)

# ---------------------------------------------------------------- SASS opcode mix per family (launches with *_source.csv)
def opclass(op):
    b = op.split('.')[0]
    if op.startswith('IMAD.WIDE') or op.startswith('IMAD.HI') or op == 'IMAD' or op == 'IMUL' or (b == 'IMAD' and not re.match(r'IMAD\.(MOV|IADD|SHL|X|U32)', op)):
        return 'imad_mul_or_wide'
    if b in ('FADD', 'FMUL', 'FFMA', 'DADD', 'DMUL', 'DFMA', 'MUFU', 'FSETP', 'FSEL', 'F2F', 'I2F', 'F2I', 'HFMA2'): return 'float'
    if b in ('LOP3', 'ISETP', 'SEL', 'SHF', 'LOP', 'PLOP3', 'P2R', 'R2P', 'PRMT', 'POPC', 'FLO', 'BMSK', 'LEA'): return 'logic_cmp_shift_lea'
    if b in ('IADD3', 'IADD', 'IMNMX', 'VIADD', 'VIMNMX'): return 'int_add'
    if b in ('LDG', 'STG', 'LD', 'ST', 'LDS', 'STS', 'ATOM', 'ATOMS', 'ATOMG', 'RED', 'LDC', 'ULDC', 'LDGSTS', 'LDL', 'STL'): return 'memory'
    if b in ('BRA', 'BSSY', 'BSYNC', 'EXIT', 'CALL', 'RET', 'WARPSYNC', 'BAR', 'YIELD', 'NANOSLEEP', 'BREAK', 'JMP', 'JMX', 'BRX', 'DEPBAR'): return 'control'
    if b in ('MOV', 'UMOV', 'S2R', 'S2UR', 'CS2R', 'R2UR', 'SHFL', 'VOTE', 'REDUX', 'MATCH'): return 'move_misc'
    return 'other'
pos2fam = {(r['q'], r['pos']): r['family'] for r in rows}
sass = collections.defaultdict(collections.Counter); sass_n = collections.Counter()
for q in QS:
    d = f'{R}/q{q}/sass'
    if not os.path.isdir(d): continue
    for fn in sorted(os.listdir(d)):
        m = re.match(r'(.*)_pos(\d+)_source\.csv$', fn)
        if not m: continue
        fam_ = pos2fam.get((q, int(m.group(2))))
        if fam_ is None: continue
        with open(f'{d}/{fn}', newline='') as fh:
            rd = list(csv.reader(fh))
        hdr = next((i for i, r_ in enumerate(rd) if r_ and r_[0] == 'Address'), None)
        if hdr is None: continue
        ci = {n: i for i, n in enumerate(rd[hdr])}
        if 'Instructions Executed' not in ci: continue
        sass_n[fam_] += 1
        for r_ in rd[hdr + 1:]:
            try: ex = float(r_[ci['Instructions Executed']])
            except Exception: continue
            t = re.sub(r'^@!?U?P\w+\s+', '', r_[ci['Source']].strip())
            op = t.split()[0] if t.split() else ''
            if op: sass[fam_][opclass(op)] += ex
classes = ['imad_mul_or_wide', 'int_add', 'logic_cmp_shift_lea', 'float', 'memory', 'control', 'move_misc', 'other']
srow = []
for f, c in sass.items():
    S = sum(c.values()) or 1
    r = dict(family=f, sass_launches=sass_n[f], executed_warp_inst=S)
    for k in classes: r[k] = c.get(k, 0) / S
    srow.append(r)
W(f'{OUT}/sass_opcode_mix.csv', srow)

stats = dict(total_launches=len(rows), nsys_total_us=tot_nsys / 1e3, ncu_dram_total_B=float(tot_dram), families=len(frows),
             join_unmatched=sum(1 for r in rows if r['nsys_dur_ns'] != r['nsys_dur_ns']),
             queries_with_positional_name_mismatch=[q for q, r in join_report.items() if r['positional_name_mismatch']],
             positional_mismatch_total=sum(r['positional_name_mismatch'] for r in join_report.values()),
             launches_match_name_grid_block=sum(r['matched_name_grid_block'] for r in join_report.values()),
             median_ncu_dram_pct=float(np.median(col(rows, 'ncu_dram_pct'))), max_ncu_dram_pct=float(col(rows, 'ncu_dram_pct').max()),
             single_block_launch_share=float(col(rows, 'ncu_single_block').mean()),
             dram_pct_lt5_share=float((col(rows, 'ncu_dram_pct') < 5).mean()),
             median_nsys_us=float(np.nanmedian([r['nsys_dur_ns'] for r in rows])) / 1e3)
json.dump(stats, open(f'{OUT}/stats.json', 'w'), indent=1)

import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 3, figsize=(15, 4.5), sharey=True)
cols = ['#4c78a8', '#72b7b2', '#f58518', '#bab0ac', '#e45756']
labels = [str(q) for q in QS] + ['ALL', 'ALL_excl_block_sort', 'MEAN_OF_QUERIES']
for a_, (c_, ttl) in zip(ax, [('launch_share', 'launches'), ('nsys_time_share', 'real-clock kernel time (nsys)'), ('ncu_dram_share', 'DRAM bytes (ncu)')]):
    bottom = np.zeros(len(labels))
    for t, cc in zip(T, cols):
        v = np.array([next(x[c_] for x in trows if str(x['query']) == l and x['tier'] == t) for l in labels])
        a_.bar(labels, v, bottom=bottom, color=cc, label=t); bottom += v
    a_.set_title('share of ' + ttl); a_.tick_params(axis='x', labelrotation=90)
ax[0].legend(ncol=5, fontsize=8, loc='lower left'); ax[0].set_xlabel('query'); 
plt.tight_layout(); plt.savefig(f'{OUT}/tier_shares.png', dpi=130)
print(json.dumps(stats, indent=1))
