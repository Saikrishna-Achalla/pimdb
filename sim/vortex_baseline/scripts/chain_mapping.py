#!/usr/bin/env python3
"""Real-GPU launch sequence of Q6 (SF1, 3 scan batches) and Q1 (SF10, 12 scan batches + merge) from the
nsys/ncu warm kernel lists, grouped into kernel families, with the simulated kernel each maps to.
Writes results/mapping_q6.csv and results/mapping_q1.csv.
Sources (measured, real GPU):
  tpch_q1_analysis/analysis/results/q6/warm_kernel_list.json      (nsys, Q6 SF1, 47 launches)
  tpch_q1_analysis/analysis/results/q1/q1_warm_kernel_list.json   (ncu, Q1 SF10, 873 launches)"""
import csv, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxlog

R = '/home/sai/cs254_project/tpch_q1_analysis/analysis/results'

# (family regex, family label, simulated kernel(s) per batch, sim launches per batch, status/note)
Q6 = [
    (r'compute_column_kernel', 'AST compute_column (whole WHERE -> bool mask)', 'filter_conj', 1,
     'mirrored: one general conjunctive-range kernel over the 3 columns'),
    (r'DeviceCompactInitKernel', 'cub select: tile-state init', '-', 0,
     'omitted (bookkeeping; our count/scan/scatter has no tile state); modeled as empty-kernel cost'),
    (r'DeviceSelectSweepKernel<select::policy_selector_from_types<cuda::counting_iterator', 'cub select sweep (mask -> int32 indices, count read back)',
     'mask_count + scan_tiles + mask_scatter', 3, 'mirrored as count/scan/scatter (3 launches for cub\'s 1 single-pass)'),
    (r'permutation_iterator<const int \*', 'gather int32 (per column)', 'gather_i32', 2, 'mirrored (price, discount)'),
    (r'device_cast<int, long>', 'cast decimal32 -> decimal64 (per column)', 'cast_i32_i64', 2, 'mirrored'),
    (r'binops::Mul', 'binary op Mul', 'binop_i64 (mul)', 1, 'mirrored'),
    (r'DeviceReduceKernel<reduce::policy_selector_from_types<reduction::<unnamed>::minmax_pair', 'Sirius SUM pre-check: min/max reduce (blocks)', 'reduce_minmax_i64', 1, 'mirrored'),
    (r'DeviceReduceSingleTileKernel<reduce::policy_selector_from_types<reduction::<unnamed>::minmax_pair', 'min/max reduce (single tile)', 'reduce_minmax_final', 1, 'mirrored'),
    (r'single_thread_kernel', 'assign_min_max (1 thread)', '-', 0, 'omitted (1-thread bookkeeping); modeled as empty-kernel cost'),
    (r'DeviceReduceKernel<reduce::policy_selector_from_types<long, unsigned int, cudf::cast_functor_fn', 'SUM reduce (blocks)', 'reduce_sum_i64', 1, 'mirrored'),
    (r'DeviceReduceSingleTileKernel<reduce::policy_selector_from_types<long,', 'SUM reduce (single tile)', 'reduce_sum_final', 1, 'mirrored'),
    (r'copy_range_kernel<256, cuda::constant_iterator<long', 'copy_range fill of the 1-row result', '-', 0, 'omitted (1 row); modeled as empty-kernel cost'),
    (r'__int128', 'final merge: widen to decimal128, sum, fill (1 row, once per query)', '-', 0, 'omitted (once per query, 1 row); modeled as empty-kernel cost'),
]
Q1 = [
    (r'binops::LessEqual', 'binary op LessEqual (shipdate filter -> bool mask)', 'cmp_i16', 1, 'mirrored'),
    (r'DeviceCompactInitKernel', 'cub select: tile-state init (filter and group-by key extraction)', '-', 0, 'omitted (bookkeeping); modeled'),
    (r'DeviceSelectSweepKernel<select::policy_selector_from_types<cuda::counting_iterator', 'cub select sweep (mask -> indices)', 'mask_count + scan_tiles + mask_scatter', 3, 'mirrored as count/scan/scatter'),
    (r'permutation_iterator<const int \*, cudf::input_indexalator', 'gather int32 (qty, price, disc, tax)', 'gather_i32', 4, 'mirrored'),
    (r'string_offsets_fn', 'strings gather: offsets scan (init + scan)', 'str_gather_len + tile_sum_i32 + scan_tiles + tile_scan_apply_i32', 8, 'mirrored as lengths + 3-launch scan per string column (cub: 2 launches)'),
    (r'gather_chars_fn', 'strings gather: characters', 'str_gather_chars', 2, 'mirrored (row-parallel copy; cuDF is char-parallel)'),
    (r'batch_memcpy', 'strings gather: batched memcpy (large-string path)', '-', 0, 'omitted: not needed for 1-byte strings in our layout; cost unknown'),
    (r'device_cast<int, long>', 'cast decimal32 -> decimal64', 'cast_i32_i64', 4, 'mirrored'),
    (r'unary_cast<long>', 'cast of SUM inputs (int32 -> int64)', 'cast_i32_i64', 2, 'mirrored (quantity, discount again)'),
    (r'binops::Sub|binops::Add', 'binary op with scalar (1 - disc, 1 + tax)', 'binop_s_i64', 2, 'mirrored'),
    (r'binops::Mul', 'binary op Mul (disc_price, charge)', 'binop_i64 (mul)', 2, 'mirrored'),
    (r'DeviceReduceKernel<reduce::policy_selector_from_types<reduction::<unnamed>::minmax_pair', 'Sirius SUM pre-check min/max (blocks)', 'reduce_minmax_i64', 5, 'mirrored'),
    (r'DeviceReduceSingleTileKernel<reduce::policy_selector_from_types<reduction::<unnamed>::minmax_pair', 'min/max (single tile)', 'reduce_minmax_final', 5, 'mirrored'),
    (r'single_thread_kernel', 'assign_min_max (1 thread)', '-', 0, 'omitted; modeled'),
    (r'cuco::initialize_functor', 'cuco hash-set slot init', 'fill_i32', 1, 'mirrored (16-slot table)'),
    (r'__uninitialized_fill', 'uninitialized_fill (int)', '-', 0, 'omitted (bookkeeping); modeled'),
    (r'mapping_indices_kernel', 'group-by: insert/find keys -> slot per row', 'gb_map_str', 1, 'mirrored (string keys, CAS insert)'),
    (r'DeviceSelectSweepKernel<select::policy_selector_from_types<cuda::transform_iterator<open_addressing', 'group-by: extract occupied slots', '-', 0, 'omitted (tiny input: table slots); modeled'),
    (r'permutation_iterator<int \*, std::__wrap_iter', 'group-by: slot -> dense index scatter', '-', 0, 'omitted (tiny); modeled'),
    (r'compute_single_pass_aggs', 'group-by: for_each (single-pass prep)', '-', 0, 'omitted (unclear role; not on the row data in our model); modeled'),
    (r'return_constant<long>|return_constant<int>', 'fill of aggregation output columns', 'fill_i64', 1, 'mirrored as one fill of the accumulator table (real: ~7)'),
    (r'single_pass_shmem_aggs_kernel', 'group-by: shared-memory aggregation', 'gb_agg_sum', 1, 'mirrored (local 64-bit atomics, global atomics at block end)'),
    (r'.', 'other (merge group-by, concat, sort of <= 4 rows, decimal128 widen)', '-', 0, 'omitted (once per query on <= 48 rows); modeled'),
]


def classify(names, table):
    counts = [0] * len(table)
    for n in names:
        for i, (rx, *_rest) in enumerate(table):
            if re.search(rx, n):
                counts[i] += 1
                break
    return counts


def main():
    out = []
    q6 = json.load(open(f'{R}/q6/warm_kernel_list.json'))
    q1 = json.load(open(f'{R}/q1/q1_warm_kernel_list.json'))
    q1 = q1 if isinstance(q1, list) else q1['kernels']
    for name, ks, table, batches, src in (('q6', q6, Q6, 3, 'q6/warm_kernel_list.json (SF1)'),
                                          ('q1', q1, Q1, 12, 'q1/q1_warm_kernel_list.json (SF10)')):
        counts = classify([k['name'] for k in ks], table)
        rows = []
        for (rx, fam, sim, simn, note), c in zip(table, counts):
            rows.append(dict(query=name, real_family=fam, real_launches_total=c, batches=batches,
                             real_launches_per_batch=round(c / batches, 2), sim_kernels=sim,
                             sim_launches_per_batch=simn, status=note, source=src))
        p = os.path.join(vxlog.ROOT, 'results', f'mapping_{name}.csv')
        with open(p, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        tot = sum(counts)
        omitted = sum(c for (rx, fam, sim, simn, note), c in zip(table, counts) if simn == 0)
        print(name, 'real launches', tot, 'per batch', round(tot / batches, 1), 'omitted (bookkeeping)', omitted,
              'sim per batch', sum(r['sim_launches_per_batch'] for r in rows))
        out.append((name, tot, omitted))
    return out


if __name__ == '__main__':
    main()
