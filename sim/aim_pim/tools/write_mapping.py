#!/usr/bin/env python3
"""Mapping table: real Sirius/libcudf launches of Q6 (SF1) and Q1 (SF10) -> DB-PU operators of the PIM chains.
Counts are read from the measured warm-iteration kernel lists (nsys); the PIM side refers to workloads.py.
Writes results/sirius_to_pim_mapping.csv."""
import csv, json, os, re
R = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "sirius_to_pim_mapping.csv")

Q6 = [  # (regex on kernel name, sirius role, PIM side, note)
    (r"compute_column_kernel", "AST predicate (4 conditions) -> bool8 mask", "PCMP x3 (SET, AND, AND) -> mask register M0 (1 bit/record, stays in the bank)", "mapped"),
    (r"DeviceCompactInitKernel|DeviceSelectSweepKernel", "compaction mask -> row indices (+1 size read-back per batch)", "none: consumers take the mask in the bank (operands are row-aligned in the same row-tile)", "removed (no PIM equivalent needed)"),
    (r"permutation_iterator<const int \*", "gather int32 price / discount by indices", "none (gather is not executable at bank level, and not needed)", "removed"),
    (r"device_cast<int, long>", "cast int32 -> int64 (price, discount)", "folded into the 32x32->64 multiply (q6_main); explicit EW widen in q6_mirror_sirius", "mapped (variant)"),
    (r"binops::Mul", "multiply int64 x int64", "MMAC (q6_main) / MUL with write-back (q6_mulwb_sum, q6_mirror_sirius)", "mapped"),
    (r"minmax|assign_min_max", "Sirius SUM-widening pre-check (min/max of the product)", "not mapped (planner policy; PIM accumulates in 64 bit, GPU combines in int128)", "left out"),
    (r"cast_functor_fn<long, cudf::DeviceSum>", "sum reduction", "MMAC accumulators / SUM + RD_MAC read-out (4 x 32 B per channel)", "mapped"),
    (r"copy_range_kernel|device_cast<long, __int128>|__int128", "merge of batch partials, int128 result", "GPU: add 16 x channels partials in int128", "host/GPU side"),
]
Q1 = [
    (r"binops::LessEqual", "predicate shipdate <= date -> bool8", "PCMP -> M0", "mapped"),
    (r"DeviceCompactInitKernel|DeviceSelectSweepKernel<select::policy_selector_from_types<cuda::counting", "compaction (+ size read-back)", "none (masked group aggregation)", "removed"),
    (r"permutation_iterator<const int \*|gather_chars|string_offsets|batch_memcpy|BatchMemcpy|InitTileState", "gathers of 4 numeric + 2 string columns", "none", "removed"),
    (r"device_cast<int, long>|unary_cast<long>", "casts int32 -> int64", "folded into EW/MUL output width (int64)", "mapped (folded)"),
    (r"binops::Sub", "1 - discount", "EW rsub_c (write-back int32)", "mapped"),
    (r"binops::Mul", "price*(1-disc), *(1+tax)", "MUL 32x32->64 and 64x32->64 (write-back)", "mapped"),
    (r"binops::Add", "1 + tax", "EW add_c (write-back int32)", "mapped"),
    (r"minmax|assign_min_max", "SUM-widening pre-checks", "not mapped (planner policy)", "left out"),
    (r"cuco::initialize_functor|__uninitialized_fill|mapping_indices|get_slot|compute_single_pass_aggs|shmem_aggs|__return_constant|policy_selector_from_types<0, 1, std::tuple<cuda::counting_iterator<int",
     "hash group-by (set init, key mapping, key retrieval, shared-memory aggregation; group-count and fallback-flag read-backs)",
     "EW add_shl (key = rf*2+ls) + GAGG x5 + count (8 group accumulators, no hash table)", "mapped"),
    (r"fused_concatenate|chars_size|__int128|Div|unary_cast<double>|fixed_point_unary_cast|compute_column_kernel|MergeSort|const double \*|const long \*, cuda::transform",
     "merge of batch partials, avg division, sort of <= 6 groups, output gathers", "GPU/host from the 16 x channels x 8 partials", "host/GPU side"),
]


def count(kfile, table):
    ks = json.load(open(kfile))
    ks = ks if isinstance(ks, list) else ks.get("kernels", ks)
    used, rows = set(), []
    for rx, role, pim, status in table:
        n = 0
        for i, k in enumerate(ks):
            if i not in used and re.search(rx, k["name"]):
                used.add(i); n += 1
        rows.append((rx, role, n, pim, status))
    rest = [k["name"][:80] for i, k in enumerate(ks) if i not in used]
    return rows, len(ks), rest


with open(OUT, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["query", "sirius_kernel_regex", "sirius_role", "launches_in_warm_iteration", "pim_side", "status"])
    for q, kf, tab, nb in (("Q6 SF1 (3 scan batches)", f"{R}/q6/warm_kernel_list.json", Q6, 3),
                           ("Q1 SF10 (13 batches)", f"{R}/q1/q1_warm_kernel_list.json", Q1, 13)):
        rows, tot, rest = count(kf, tab)
        for rx, role, n, pim, st in rows:
            w.writerow([q, rx, role, n, pim, st])
        w.writerow([q, "(unmatched)", "; ".join(sorted(set(rest)))[:300], len(rest), "-", "-"])
        w.writerow([q, "(total)", "", tot, "", ""])
        print(q, "total", tot, "unmatched", len(rest), sorted(set(rest))[:5])
print("wrote", os.path.abspath(OUT))
