# TPC-H Q15 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q15.sql`): CTE `revenue_view` = per-`l_suppkey` sum(l_extendedprice*(1-l_discount)) over
lineitem with l_shipdate in [1993-05-01, 1993-08-01); the CTE is joined to supplier on s_suppkey and filtered by `total_revenue = (select max(total_revenue) from revenue_view)`;
ORDER BY s_suppkey. The CTE is referenced twice, but `query_plan.txt` has one GPU_SCAN of lineitem (id=0) feeding a CTE operator (id=6) and one GPU_SCAN of supplier (id=17).

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_suppkey, l_extendedprice, l_discount, l_shipdate | 72,015,360 |
| supplier | 10,000 | s_suppkey, s_name, s_address, s_phone | 720,896 |
| **Total** | | | **72,736,256 B (72.74 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 72,015,360 after the lineitem pin, 72,736,256 after the supplier pin (delta 720,896).
Pinned per row: lineitem 12.00 B, supplier 72.09 B. Native widths (DuckDB-CPU types: l_suppkey INTEGER, l_extendedprice/l_discount DECIMAL(15,2) = 8 B each as int64 (inferred storage width), l_shipdate DATE = 4 B):
lineitem 4+8+8+4 = 24 B/row = 144,029,160 B; supplier mean string lengths 18.0 / 24.98 / 15.0 chars + 4 B key + 3×4 B offsets (assumed) ≈ 74 B/row = 0.74 MB; native total (inferred) ≈ 144.77 MB.
Sirius pins lineitem at 12 B/row (narrowed carriers; how the decimals are narrowed was not inspected).

## Selectivities and cardinalities (DuckDB-CPU on the same Parquet)

- lineitem rows 6,001,215; l_shipdate in [1993-05-01, 1993-08-01): **227,694 rows (3.79%)**.
- Distinct l_suppkey in lineitem 10,000; groups after the CTE group-by: **10,000** (every supplier has shipments in the window).
- max(total_revenue) = 1882892.8342, attained by exactly 1 supplier (ties = 1); join with supplier (10,000 rows, PK) -> **1 result row** (supplier 5890; result CSV 122 B).
- The equality `total_revenue = max(total_revenue)` compares DECIMAL aggregates; no tolerance is involved in the engine.

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 72.74 MB | **108.2 µs** |
| A'. Same at native widths (inferred) | ≈ 144.77 MB | ≈ 215.4 µs |
| A-min. Only what predicates force (inferred native widths): l_shipdate of all rows 6,001,215 × 4 = 24.00 MB; l_suppkey + price + discount (20 B) of the 227,694 matches 4.55 MB; s_suppkey 0.04 MB (sector granularity ignored) | ≈ 28.60 MB | 42.6 µs |
| B. A + materialising the 10,000-group aggregate (12 B/group, ~120 KB) written and re-read about 4 times for max, join build and sort (inferred) | ≈ 73.2 MB | ≈ 109.0 µs |

Q15 is a **~73 MB, ~108 µs** problem for the memory system (narrowed, read once); lineitem is 99.0% of pinned bytes and only 3.79% of its rows survive the date predicate.

Compute: 6.0 M date compares, 227,694 × (1−d)·price multiplies and a 10,000-group hash/sort aggregate, a max over 10,000 values, a 10,000-row join and 1-row sort ≈ 0.02 G simple ops;
at ~14 T lane-ops/s that is **< 5 µs** (inferred).
Q15 is bandwidth-floor-bound at ~108 µs, but a real implementation is bounded by **latency and launch count**: the nsys run shows 112 kernels per iteration (`pcie_verification.txt`);
at ~2 µs per smallest kernel (an imported assumption from the Q2 analysis, not re-measured here) the GPU-side launch floor is ~0.22 ms (inferred; an implementation bound, reported separately).
