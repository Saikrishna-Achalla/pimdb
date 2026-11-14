"""Attribute every kernel launch of one warm iteration (nsys) to a Sirius operator instance and a cause.

Usage: python -I attribute.py [q ...]        (default: 2..22)
Writes launch_attribution.json and launch_causes.csv in this directory, prints a per-query check.

Method (inferred, see the comments of each step):
 1. tasks.py splits each pipeline thread into Sirius pipeline tasks (gpu_pipeline_task.cpp:748/:890 stream syncs).
 2. label(): a left-to-right grammar over the kernel names of one task assigns each launch a FAMILY (which kind of
    libcudf/Sirius call it belongs to), a CALL name and a ROLE:
      main   = the one kernel per call that does the operator's essential work      -> cause 'distinct'
      pass   = an extra pass over the data of the same call (count/size, compaction after a mask, build before
               probe, radix/merge passes, first output gather, string offsets scan) -> cause 'multi-pass'
      column = the same kernel again for another column / key / aggregate / expression node -> 'per-column'
      init   = tiny bookkeeping (cub tile-state init, slot init, sequence, fill, single-thread, null-mask)
                                                                               -> 'bookkeeping'
 3. match(): each task with kernels is mapped to a plan pipeline whose operator chain can produce its families
    in order (time order + lowest pipeline id + exact-signature repeats = another batch of the same pipeline).
 4. Inside the pipeline, families are walked onto the chain's operators in order -> operator instance (type, id).
 5. Cause override 'per-batch': every launch of the 2nd..Nth task of the same pipeline (another scan batch), and every
    launch of CONCAT / MERGE_GROUP_BY / MERGE_AGGREGATE / MERGE_TOP_N / MERGE_SORT operators (they exist only to
    combine per-batch partial results).
"""
import collections, csv, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import tasks, ksig  # noqa: E402
from plan import plan  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
CAUSE = {"main": "distinct", "pass": "multi-pass", "column": "per-column", "init": "bookkeeping"}

# which operator types can produce which kernel family
CAN = {
    "GPU_SCAN": {"EXPR", "COMPACT", "GATHER"},
    "DYNAMIC_FILTER": {"DFP", "COMPACT", "EXPR", "GATHER"},
    "FILTER": {"EXPR", "COMPACT", "GATHER"},
    "PROJECTION": {"EXPR", "GATHER"},
    "HASH_JOIN": {"JOIN", "GATHER", "EXPR", "FILL"},
    "NESTED_LOOP_JOIN": {"JOIN", "GATHER"},
    "DENSE_COUNT_JOIN": {"DCJ", "GATHER", "RED"},
    "HASH_GROUP_BY": {"GB", "GATHER", "EXPR", "FILL"},
    "MERGE_GROUP_BY": {"GB", "GATHER", "EXPR", "CONCAT", "FILL"},
    "UNGROUPED_AGGREGATE": {"RED", "EXPR", "FILL", "GATHER"},
    "MERGE_AGGREGATE": {"RED", "EXPR", "FILL", "CONCAT", "GATHER"},
    "TOP_N": {"SORT", "GATHER"},
    "MERGE_TOP_N": {"SORT", "GATHER", "CONCAT"},
    "ORDER_BY": {"SORT", "GATHER"},
    "MERGE_SORT": {"SORT", "GATHER", "CONCAT"},
    "SORT_PARTITION": {"SORT", "GATHER"},
    "CONCAT": {"CONCAT"},
    "BUILD_FILTER": {"DFB"},
    "CTE": set(), "RESULT_COLLECTOR": set(), "PARTITION": set(), "SORT_SAMPLE": {"SORT"},
}
MERGE_OPS = {"CONCAT", "MERGE_GROUP_BY", "MERGE_AGGREGATE", "MERGE_TOP_N", "MERGE_SORT"}


def kind(k):
    """Classify one launch by its short name and demangled functor (no context)."""
    a, d = k["name"], k["demangled"]
    if a == "transform_kernel":
        if "cudf::gather(" in d or "input_indexalator>>" in d and "permutation_iterator" in d:
            return "gather"
        if re.search(r"unary_cast|device_cast|fixed_point_unary_cast|convert_to_rep", d):
            return "cast"
        if "compute_sequence_value" in d:
            return "sequence"
        if "__return_constant" in d:
            return "fill"
        if "encode_fn" in d:
            return "dict_encode"
        if "unique_copy_fn" in d or "unique_keys" in d or "groupby::" in d:
            return "gb_aux"
        if re.search(r"substring|contains_fn|extract_component|DeviceNot", d):
            return "expr"
        if "cudf::scatter(" in d:
            return "scatter"
        if "list_size_functor" in d or "copy_slice" in d:
            return "cast"
        if "permutation_iterator" in d:
            return "gather"
        return "transform_other"
    if a == "static_kernel":
        if "membership_probe_functor" in d:
            return "df_probe"
        if "initialize_functor" in d:
            return "slot_init"
        if "binary_op_device_dispatcher" in d:
            return "binop"
        if "compute_single_pass_aggs" in d or "compute_groupby" in d or "label_segments" in d:
            return "gb_aux"
        if "d_fill" in d:
            return "fill"
        if "binary_search_functor" in d:
            return "search"
        return "for_each_other"
    if a in ("insert_if_n",):
        return "insert"
    if a in ("find_if_n", "contains_if_n", "mixed_join_semi"):
        return "join_probe"
    if a == "add_if_n":
        return "bloom_add"
    if a.startswith("hash_csr_"):
        return a
    if a in ("compute_conditional_join_output_size", "conditional_join", "filter_join_indices_kernel"):
        return a
    if a in ("accumulate_kernel", "emit_kernel"):
        return "dcj"
    if a == "fused_membership_mask_kernel":
        return "df_fused"
    if a in ("init_found_pos_pointer", "find_kernel"):
        return "sorted_check_init" if a == "init_found_pos_pointer" else "sorted_check"
    if a == "add_if_shmem":
        return "hll"
    if a == "mapping_indices_kernel":
        return "gb_map"
    if a == "single_pass_shmem_aggs_kernel":
        return "gb_agg"
    if a == "_kernel_agent":
        return "rbk_init" if "InitAgent" in d else "rbk"
    if a == "DeviceReduceByKeyKernel":
        return "rbk"
    if a.startswith(("DeviceRadixSort", "DeviceMergeSort", "DeviceTopK")):
        if "Init" in a:
            return "sort_init"
        if a in ("DeviceMergeSortBlockSortKernel", "DeviceRadixSortSingleTileKernel", "DeviceTopKHistogramKernel",
                 "DeviceRadixSortHistogramKernel"):
            return "sort_first"
        return "sort_pass"
    if a in ("DeviceReduceKernel", "DeviceReduceSingleTileKernel"):
        if "minmax" in d:
            return "minmax_" + ("big" if a == "DeviceReduceKernel" else "tile")
        return "reduce_" + ("big" if a == "DeviceReduceKernel" else "tile")
    if a == "single_thread_kernel":
        return "single_thread"
    if a == "copy_range_kernel":
        return "fill"
    if a.startswith("fused_concatenate"):
        return "concat_offsets" if "offset" in a else "concat"
    if a in ("compute_column_kernel", "like_multiliteral_kernel", "copy_if_else_kernel"):
        return "expr"
    if a in ("valid_if_kernel", "InitTileStateKernel"):
        return "tiny_init"
    if a in ("BatchMemcpyKernel", "MultiBlockBatchMemcpyKernel"):
        return "batch_memcpy"
    if a == "DeviceCompactInitKernel":
        return "compact_init"
    if a == "DeviceSelectSweepKernel":
        return "compact"
    if a == "DeviceScanInitKernel":
        return "scan_init"
    if a == "DeviceScanKernel":
        return "scan"
    if a.startswith("gather_chars"):
        return "str_chars"
    if a == "valid_if_n_kernel":
        return "valid_if"
    return "other"


GB_CORE_KINDS = {"gb_map", "gb_agg", "rbk"}


def label(ks, ts):
    """Return [(family, call, role)] for the kernel launches of one task (in launch order).

    family: which kind of operator work (EXPR, COMPACT, GATHER, DFP, DFB, JOIN, GB, SORT, RED, FILL, CONCAT, DCJ)
    role  : main / pass / column / init (see module doc)."""
    n = len(ks)
    K = [kind(k) for k in ks]
    out = [None] * n
    # group-by segments: from the first pre-check before a group-by core to the last core kernel
    gb_core_idx = [i for i, x in enumerate(K) if x in GB_CORE_KINDS]
    gb_lo, gb_hi = None, None
    if gb_core_idx:
        gb_hi = gb_core_idx[-1]
        first_core = gb_core_idx[0]
        pre = [i for i in range(first_core) if K[i] in ("sorted_check_init", "sorted_check", "hll", "minmax_big",
                                                       "minmax_tile", "dict_encode")]
        # the hash-set slot init / for_each right before mapping_indices
        gb_lo = pre[0] if pre else max(0, first_core - 2)
        # global-memory / sparse path: aggregation for_each, retrieve_all (copy_if) follow the mapping kernel
        j = gb_hi + 1
        while j < n and K[j] in ("gb_aux", "slot_init", "fill", "compact_init", "compact", "transform_other",
                                 "for_each_other") and "gb_agg" not in K[gb_hi:j + 1]:
            if K[j] == "compact":
                gb_hi = j
                break
            j += 1
        else:
            pass
        # sort-based group-by: everything between the sorted check and reduce_by_key is group-by internals
    owner, owner_gathers = None, 0
    seen = collections.Counter()

    def gather_role():
        nonlocal owner_gathers
        owner_gathers += 1
        return "pass" if owner_gathers == 1 else "column"

    def first(fam, role="main"):
        seen[fam] += 1
        return role if seen[fam] == 1 else "column"

    for i, (k, x) in enumerate(zip(ks, K)):
        if out[i] is not None:
            continue
        nxt = K[i + 1] if i + 1 < n else ""
        nxt2 = K[i + 2] if i + 2 < n else ""
        in_gb = gb_lo is not None and gb_lo <= i <= gb_hi
        # ---------------- group-by segment
        if in_gb:
            if x == "gb_agg":
                out[i] = ("GB", "hash groupby: single_pass_shmem_aggs_kernel", "main")
            elif x == "rbk":
                out[i] = ("GB", "sort groupby: reduce_by_key", "main" if not any(o and o[2] == "main" and o[0] == "GB" for o in out if o) else "column")
            elif x == "gb_map":
                out[i] = ("GB", "hash groupby: mapping_indices_kernel (set insert_and_find)", "pass")
            elif x in ("sorted_check_init", "sorted_check"):
                out[i] = ("GB", "keys_ascending: cub DeviceFind is_sorted (+bool readback)", "init" if x.endswith("init") else "pass")
            elif x == "hll":
                out[i] = ("GB", "approx_distinct_count HyperLogLog (+estimate readback)", "pass")
            elif x.startswith("minmax"):
                out[i] = ("GB", "sums_to_widen: cudf::minmax (+readback)", "pass")
            elif x == "single_thread":
                out[i] = ("GB", "minmax result single_thread_kernel", "init")
            elif x in ("slot_init", "fill", "sequence", "rbk_init", "compact_init", "scan_init", "tiny_init", "sort_init"):
                out[i] = ("GB", f"groupby bookkeeping: {x}", "init")
            elif x == "cast":
                out[i] = ("GB", "groupby request: cast of value column", "column")
            elif x == "transform_other" and nxt in ("gb_agg",) or (x == "transform_other" and "gb_agg" in K[i:gb_hi + 1] and K[i - 1] != "compact"):
                out[i] = ("GB", "hash groupby: identity fill of result column", "init")
            else:
                out[i] = ("GB", f"groupby internal pass: {x} ({k['name']})", "pass")
            owner, owner_gathers = "GB", 0
            continue
        # ---------------- joins / dynamic-filter build
        if x == "slot_init" and nxt == "insert":
            if nxt2 == "join_probe":
                out[i] = ("JOIN", "cuco static_set/filtered_join ctor: slot init", "init")
            else:
                out[i] = ("DFB", "dyn-filter in-list static_set ctor: slot init", "init")
            continue
        if x == "insert":
            if nxt == "join_probe":
                out[i] = ("JOIN", "hash join build: insert_if_n", "pass")
            else:
                out[i] = ("DFB", "dyn-filter in-list set insert_if_n", first("DFB"))
            continue
        if x == "bloom_add":
            out[i] = ("DFB", "dyn-filter bloom add_if_n", first("DFB"))
            continue
        if x == "join_probe":
            out[i] = ("JOIN", f"hash join probe: {k['name']}", "main")
            owner, owner_gathers = "JOIN", 0
            if nxt == "compact_init":
                out[i + 1] = ("JOIN", "copy_if of matches: tile init", "init")
                if nxt2 == "compact":
                    out[i + 2] = ("JOIN", "copy_if of matches: select sweep (+size readback)", "pass")
            continue
        if x.startswith("hash_csr_"):
            out[i] = ("JOIN", f"cudf::hash_join CSR: {x}", "main" if x == "hash_csr_retrieve_kernel" else "pass")
            owner, owner_gathers = "JOIN", 0
            if x in ("hash_csr_build_count_kernel", "hash_csr_probe_count_kernel") and nxt == "scan_init":
                out[i + 1] = ("JOIN", "hash_join offsets scan: tile init", "init")
                if nxt2 == "scan":
                    out[i + 2] = ("JOIN", "hash_join offsets inclusive scan" + (" (+output size readback)" if "probe" in x else ""), "pass")
            continue
        if x in ("compute_conditional_join_output_size", "conditional_join", "filter_join_indices_kernel"):
            out[i] = ("JOIN", x, "main" if x == "conditional_join" else "pass")
            owner, owner_gathers = "JOIN", 0
            if x == "filter_join_indices_kernel":
                j = i + 1
                while j < n and K[j] in ("reduce_big", "reduce_tile", "compact_init", "compact"):
                    out[j] = ("JOIN", "join post-filter: count + copy_if of surviving pairs (+size readback)",
                              "init" if K[j] == "compact_init" else "pass")
                    j += 1
            continue
        if x == "scatter":
            out[i] = (owner or "JOIN", "cudf::scatter (mark-join result)", "pass")
            continue
        if x == "dcj" or (x.startswith(("minmax", "reduce")) and "dcj" in K[i:]) or (x == "single_thread" and "dcj" in K[i:]):
            out[i] = ("DCJ", f"dense count join: {k['name']}",
                      "main" if (k["name"] == "accumulate_kernel" and not seen["DCJ"]) else ("pass" if x != "dcj" else "column"))
            if k["name"] == "accumulate_kernel":
                seen["DCJ"] += 1
            owner, owner_gathers = "DCJ", 0
            continue
        # ---------------- dynamic-filter probe at the scan / at a join edge
        if x in ("df_fused", "df_probe"):
            out[i] = ("DFP", "dyn-filter membership mask" + (" (fused rounds of 4)" if x == "df_fused" else " (DeviceFor set/bloom lookup)"), first("DFP"))
            owner, owner_gathers = "DFP", 0
            continue
        if x == "expr" and k["name"] == "compute_column_kernel" and nxt == "df_fused":
            out[i] = ("DFP", "dyn-filter zone-map AST", first("DFP"))
            continue
        # ---------------- sorts / top-k
        if x in ("sort_first", "sort_pass", "sort_init"):
            role = "init" if x == "sort_init" else ("main" if x == "sort_first" and not seen["SORTMAIN"] else "pass")
            if role == "main":
                seen["SORTMAIN"] += 1
            out[i] = ("SORT", f"sort/top-k: {k['name']}", role)
            owner, owner_gathers = "SORT", 0
            continue
        if x == "sequence" and nxt in ("sort_first", "sort_init", "cast", "sequence"):
            out[i] = ("SORT", "thrust::sequence of row indices before sort", "init")
            continue
        if x == "cast" and nxt in ("sort_first", "sort_init"):
            out[i] = ("SORT", "sort key transform", "pass")
            continue
        # ---------------- reductions (ungrouped aggregate) and fills
        if x in ("reduce_big", "reduce_tile", "minmax_big", "minmax_tile"):
            if x.endswith("tile") and i and K[i - 1] in ("reduce_big", "minmax_big"):
                out[i] = ("RED", "cub DeviceReduce second (single-tile) pass", "pass")
            elif x.startswith("minmax"):
                out[i] = ("RED", "cudf::minmax pre-check (+readback)", "pass")
            else:
                out[i] = ("RED", "cudf::reduce (cub DeviceReduce)", first("RED"))
            owner, owner_gathers = "RED", 0
            continue
        if x == "single_thread":
            out[i] = ("RED", "single_thread_kernel (minmax result / get_element)", "init")
            continue
        if x == "fill":
            out[i] = ("FILL", "fill / make_column_from_scalar", "init")
            continue
        if x == "sequence":
            out[i] = ("FILL", "cudf::sequence", "init")
            continue
        # ---------------- concatenate
        if x in ("concat", "concat_offsets"):
            out[i] = ("CONCAT", f"cudf::concatenate: {k['name']}", "pass" if x == "concat_offsets" else first("CONCAT"))
            owner, owner_gathers = "CONCAT", 0
            continue
        # ---------------- expressions
        if x in ("expr", "binop", "for_each_other", "transform_other", "search"):
            prev_expr = i and out[i - 1] is not None and out[i - 1][0] == "EXPR"
            out[i] = ("EXPR", f"expression: {k['name']} {'(' + x + ')'}", "column" if prev_expr else "main")
            owner, owner_gathers = "EXPR", 0
            continue
        if x in ("tiny_init",):
            out[i] = ("EXPR", f"expression bookkeeping: {k['name']}", "init")
            continue
        if x == "batch_memcpy":
            out[i] = ("EXPR", f"strings make_chars_buffer: {k['name']}", "pass")
            continue
        # ---------------- compaction
        if x == "compact_init":
            out[i] = ("COMPACT", "apply_boolean_mask/copy_if: tile init", "init")
            continue
        if x == "compact":
            out[i] = ("COMPACT", "apply_boolean_mask/copy_if: select sweep (+size readback)", "pass")
            owner, owner_gathers = "COMPACT", 0
            continue
        # ---------------- gathers / casts / strings
        if x == "scan_init":
            out[i] = ("GATHER", "strings offsets: scan tile init", "init")
            continue
        if x == "scan":
            out[i] = ("GATHER", "strings offsets: size scan (+total-bytes readback)", "pass")
            continue
        if x == "str_chars":
            out[i] = ("GATHER", f"strings gather chars ({k['name']})", gather_role())
            continue
        if x == "valid_if":
            out[i] = ("GATHER", "gather null masks valid_if_n (+null-count readback)", "init")
            continue
        if x == "gather":
            out[i] = ("GATHER", "cudf::gather of one column (transform_kernel)", gather_role())
            continue
        if x == "cast":
            out[i] = ("GATHER", "cast of one column (transform_kernel)", "column")
            continue
        if x in ("dict_encode", "gb_aux", "slot_init", "rbk_init", "sorted_check", "sorted_check_init", "hll"):
            out[i] = ("GB", f"group-by/distinct helper: {x}", "pass" if x not in ("slot_init", "rbk_init", "sorted_check_init") else "init")
            continue
        out[i] = ("OTHER", k["name"], "main")
    return out


def families_in_order(lab):
    seq = []
    for fam, _, _ in lab:
        if fam in ("GATHER", "FILL"):
            continue
        if not seq or seq[-1] != fam:
            seq.append(fam)
    return seq


def can(op, fam):
    return fam in CAN.get(op, set())


def chain_of(p):
    ops = list(p["ops"])
    return ops


def upstream_ops(p, byid, types):
    """Operators of the given types in pipelines upstream of p (BFS over inputs), nearest first."""
    out, seen, frontier = [], set(), [x[0] for x in p["inputs"]]
    while frontier:
        nxt = []
        for u in frontier:
            if u in seen or u not in byid:
                continue
            seen.add(u)
            out += [(o, u) for o in reversed(byid[u]["ops"]) if o[0] in types]
            nxt += [x[0] for x in byid[u]["inputs"]]
        frontier = nxt
    return out


def walk(p, lab, passthrough=frozenset(), byid=None):
    """Map each labelled kernel onto an operator of pipeline p. Returns (assign list, misfit score).
    passthrough: operator ids that cannot launch kernels here (MERGE_GROUP_BY/MERGE_AGGREGATE fed by one partial)."""
    ops = [o for o in p["ops"] if o[1] not in passthrough]
    to_build = p["out"] is not None and p["out"][1] == "build"
    pos, assign, bad = 0, [], 0.0
    last, compacted = None, False
    for fam, call, role in lab:
        if fam == "DFB":
            bf = [o for o in ops if o[0] == "BUILD_FILTER"]
            if bf:
                assign.append(bf[0])
            elif to_build:
                assign.append(("DYNAMIC_FILTER_PUBLISH->" + p["out"][0], ops[-1][1] if ops else -1))
            else:
                hj = [o for o in ops if o[0] == "HASH_JOIN"]
                assign.append(("DYNAMIC_FILTER_PUBLISH", hj[0][1] if hj else (ops[-1][1] if ops else -1)))
                bad += 0.25
            continue
        if fam == "DFP":
            j = next((k for k in range(pos, len(ops)) if ops[k][0] == "DYNAMIC_FILTER"), None)
            if j is None:
                j = next((k for k in range(pos, len(ops)) if ops[k][0] == "GPU_SCAN"), None)
            if j is None and byid is not None:
                up = upstream_ops(p, byid, ("DYNAMIC_FILTER",))
                if up:
                    (o, u) = up[0]
                    last = ("DEFERRED:P%d:%s" % (u, o[0]), o[1])
                    assign.append(last)
                    compacted = False
                    continue
            if j is None:
                hj = [o for o in ops if o[0] in ("HASH_JOIN", "MERGE_GROUP_BY")]
                if hj:
                    last = ("DYNAMIC_FILTER_EDGE@" + hj[0][0], hj[0][1])
                    assign.append(last)
                    compacted = False
                    continue
                assign.append(None); bad += 1
                continue
            pos, last, compacted = j, ops[j], False
            assign.append(last)
            continue
        if fam in ("GATHER", "FILL") and last is not None:
            assign.append(last)
            continue
        if fam == "COMPACT" and last is not None and (can(last[0], fam) or "DYNAMIC_FILTER" in last[0]
                                                      or last[0] in ("HASH_GROUP_BY", "MERGE_GROUP_BY")):
            compacted = True
            assign.append(last)
            continue
        start = pos
        if fam == "EXPR" and compacted:
            nxt = next((k for k in range(pos + 1, len(ops)) if can(ops[k][0], fam)), None)
            if nxt is not None:
                start = nxt
        j = next((k for k in range(start, len(ops)) if can(ops[k][0], fam)), None)
        if j is None:
            cand = [k for k in range(len(ops)) if can(ops[k][0], fam)]
            if cand:
                j = cand[0]
                bad += 0.5
            else:
                assign.append(None); bad += 1
                continue
        if ops[j] != last:
            compacted = False
        pos, last = j, ops[j]
        if fam == "COMPACT":
            compacted = True
        assign.append(last)
    return assign, bad


def passthrough_ops(p, byid, used):
    """MERGE_GROUP_BY / MERGE_AGGREGATE whose partials come from a single task are pass-through
    (sirius_physical_grouped_aggregate_merge.cpp:275 / :283): they cannot launch kernels."""
    out = set()
    for t, i in p["ops"]:
        if t not in ("MERGE_GROUP_BY", "MERGE_AGGREGATE"):
            continue
        seen, stack, n = set(), [x[0] for x in p["inputs"]], 0
        while stack:
            u = stack.pop()
            if u in seen or u not in byid:
                continue
            seen.add(u)
            if any(o[0] in ("HASH_GROUP_BY", "UNGROUPED_AGGREGATE") for o in byid[u]["ops"]):
                n += len(used.get(u, []))
            else:
                stack += [x[0] for x in byid[u]["inputs"]]
        if n <= 1:
            out.add(i)
    return frozenset(out)


def match(T, P):
    """Assign each task with kernels to a pipeline. Returns {task idx: (pid, confidence, repeat_of)}."""
    byid = {p["pid"]: p for p in P}
    assigned = {}
    used = collections.defaultdict(list)   # pid -> task idx list
    sigs = {}
    for t in T:
        ks = ksig(t)
        if not ks:
            continue
        lab = label(ks, t["task_stream"])
        t["_lab"] = lab
        sig = tuple(k["name"] for k in ks)
        gsum = sum(k["grid"] for k in ks)
        # candidates
        cands = []
        for p in P:
            a, bad = walk(p, lab, passthrough_ops(p, byid, used), byid)
            if bad == 0:
                cands.append(p["pid"])
        rep = None
        grids = [k["grid"] for k in ks]
        kt_order = [x["idx"] for x in T if ksig(x)]
        for ti, (s2, g2, pid2) in sigs.items():
            last_of_pid = max(used[pid2]) if used[pid2] else ti
            near = kt_order.index(t["idx"]) - kt_order.index(last_of_pid) <= 4
            if s2 == sig and near and len(sig) >= 3 and all(0.5 <= a / max(b, 1) <= 2.0 or abs(a - b) <= 2
                                                   for a, b in zip(grids, g2)):
                rep = (ti, pid2)
        free = [c for c in cands if not used[c]]
        twin = False
        if rep is not None and rep[1] in cands and not twin and (byid[rep[1]]["ops"][0][0] == "GPU_SCAN" or not free):
            pid, conf, rof = rep[1], "high", rep[0]
        elif free:
            pid = free[0]
            conf = "high" if len(free) == 1 else "medium"
            rof = None
        elif cands:
            pid, conf, rof = cands[-1], "low", None
        else:
            # best partial fit
            best = min(P, key=lambda p: (walk(p, lab, passthrough_ops(p, byid, used), byid)[1], len(used[p["pid"]]) > 0, p["pid"]))
            pid, conf, rof = best["pid"], "low", None
        used[pid].append(t["idx"])
        assigned[t["idx"]] = (pid, conf, rof)
        if rof is None:
            sigs[t["idx"]] = (sig, [k["grid"] for k in ks], pid)
    return assigned, used


def readbacks(t):
    """Host round trips inside a task: a D2H copy (any size <= 4 KiB) followed, before the next kernel launch on
    this thread, by a stream/event synchronize. Also counts all syncs and H2D+sync pairs."""
    ev = t["events"]
    rb, h2d_sync, syncs = 0, 0, 0
    for i, e in enumerate(ev):
        if e["kind"] == "SYNC":
            syncs += 1
        if e["kind"] in ("D2H", "H2D") and e.get("bytes", 0) <= 4096:
            for f in ev[i + 1:]:
                if f["kind"] == "K":
                    break
                if f["kind"] == "SYNC":
                    if e["kind"] == "D2H":
                        rb += 1
                    else:
                        h2d_sync += 1
                    break
    return rb, h2d_sync, syncs


FAM_DEFAULT = {"EXPR": "FILTER/PROJECTION expr", "COMPACT": "FILTER", "GATHER": "PROJECTION", "JOIN": "HASH_JOIN",
               "GB": "HASH_GROUP_BY", "SORT": "TOP_N/ORDER_BY", "RED": "UNGROUPED_AGGREGATE", "FILL": "UNGROUPED_AGGREGATE",
               "DFP": "DYNAMIC_FILTER probe", "DFB": "DYNAMIC_FILTER build", "CONCAT": "CONCAT", "DCJ": "DENSE_COUNT_JOIN",
               "OTHER": "OTHER"}


def norm_type(op, fam):
    if op is None:
        return FAM_DEFAULT.get(fam, fam) + " (unattributed)"
    t = op[0]
    if "PUBLISH" in t or t == "BUILD_FILTER":
        return "DYNAMIC_FILTER build"
    if "DYNAMIC_FILTER" in t:
        return "DYNAMIC_FILTER probe"
    return t


def run(q):
    T, E = tasks(q)
    P = plan(q)
    byid = {p["pid"]: p for p in P}
    assigned, used = match(T, P)
    insts = collections.OrderedDict()
    launches = []
    task_rows = []
    for t in T:
        ks = ksig(t)
        rb, h2s, sy = readbacks(t)
        task_rows.append(dict(task=t["idx"], thread=t["thread"], kernels=len(ks), d2h_readback_syncs=rb,
                              h2d_then_sync=h2s, syncs=sy, pipeline=assigned.get(t["idx"], (None,))[0]))
        if not ks:
            continue
        pid, conf, rof = assigned[t["idx"]]
        p = byid[pid]
        lab = t["_lab"]
        asg, bad = walk(p, lab, passthrough_ops(p, byid, used), byid)
        batch_no = used[pid].index(t["idx"]) + 1
        blk, cur_op, cur_has_main = 0, None, False
        for k, (fam, call, role), op in zip(ks, lab, asg):
            cause = CAUSE[role]
            if op is not None and (op[0] in MERGE_OPS or op[0].startswith("CONCAT")):
                cause = "per-batch"
            if batch_no > 1:
                cause = "per-batch"
            restart = cur_has_main and (call.startswith(("cuco static_set/filtered_join ctor", "cudf::hash_join CSR: hash_csr_build_count"))
                                         or (fam in ("DFP", "SORT", "EXPR") and role == "main" and cur_op == op and fam != "EXPR")
                                         or (fam == "GB" and role in ("pass", "init") and call.startswith(("keys_ascending", "approx", "sums_to_widen"))))
            if op != cur_op or restart:
                blk += 1
                cur_op, cur_has_main = op, False
            if role == "main":
                cur_has_main = True
            otype = norm_type(op, fam)
            key = f"P{pid}:{op[0]}({op[1]})" if op else f"P{pid}:UNATTRIBUTED"
            c = conf if op else "none"
            rec = dict(name=k["name"][:120], short=k["name"], grid=k["grid"], block=k["block"], dur_ns=k["dur_ns"],
                       stream=k["stream"], thread=t["thread"], task=t["idx"], batch=batch_no, exec_block=f"t{t['idx']}b{blk}",
                       op_type=otype, family=fam, call=call, role=role, cause=cause, confidence=c, t_launch=k["t"],
                       other_stream=k["stream"] != t["task_stream"])
            launches.append(rec)
            insts.setdefault(key, dict(pipeline=pid, op_type=otype, op_id=op[1] if op else None,
                                       pipeline_ops=[f"{a}({b})" for a, b in p["ops"]], confidence=c,
                                       tasks=[], launches=[]))
            if t["idx"] not in insts[key]["tasks"]:
                insts[key]["tasks"].append(t["idx"])
            insts[key]["launches"].append(rec)
    return dict(q=q, kernels=len(launches), tasks=task_rows, instances=insts, n_tasks=len(T),
                n_kernel_tasks=sum(1 for t in T if ksig(t)))


def main(qs):
    summ = {r["q"]: r for r in json.load(open(f"{RES}/summary/summary_data.json"))}
    allres, rows = {}, []
    for q in qs:
        r = run(q)
        allres[q] = r
        exp = summ[q]["kernels"]
        L = [x for v in r["instances"].values() for x in v["launches"]]
        assert len(L) == r["kernels"]
        ok = "OK" if len(L) == exp else "MISMATCH"
        un = sum(1 for x in L if x["confidence"] == "none")
        conf = collections.Counter(x["confidence"] for x in L)
        print(f"q{q}: {len(L)} launches (summary {exp}) {ok}; tasks {r['n_tasks']} ({r['n_kernel_tasks']} with kernels); "
              f"confidence {dict(conf)}")
        cc = collections.defaultdict(lambda: [0, 0.0])
        for x in L:
            cc[x["cause"]][0] += 1
            cc[x["cause"]][1] += x["dur_ns"]
        for cause in ("distinct", "multi-pass", "per-column", "per-batch", "bookkeeping"):
            rows.append(dict(q=q, cause=cause, launches=cc[cause][0], kernel_us=round(cc[cause][1] / 1e3, 2),
                             share_launches=round(cc[cause][0] / len(L), 4)))
    json.dump({str(q): r for q, r in allres.items()}, open(f"{HERE}/launch_attribution.json", "w"), indent=1,
              default=str)
    with open(f"{HERE}/launch_causes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return allres


if __name__ == "__main__":
    qs = [int(x) for x in sys.argv[1:]] or list(range(2, 23))
    main(qs)
