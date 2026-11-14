# TPC-H Q12 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q12.sql`): shipmode IN ('TRUCK','REG AIR'), l_commitdate < l_receiptdate,
l_shipdate < l_commitdate, l_receiptdate in [1994-01-01, 1995-01-01); orders ⋈ lineitem on orderkey; group by l_shipmode (2 groups).

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| orders | 1,500,000 | o_orderkey, o_orderpriority | 24,600,320 |
| lineitem | 6,001,215 | l_orderkey, l_shipmode, l_commitdate, l_receiptdate, l_shipdate | 109,735,168 |
| **Total** | | | **134,335,488 B (134.34 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 24,600,320 after the orders pin, 134,335,488 after the lineitem pin
(delta 109,735,168). Pinned per row: orders 16.40 B, lineitem 18.29 B. Native widths (inferred from Parquet types, DuckDB-CPU: INTEGER keys, DATE = 4 B,
VARCHAR with mean length l_shipmode 4.29 chars, o_orderpriority 8.40 chars, plus an assumed 4 B offset per string): orders 4 + 8.40 + 4 = 16.4 B/row =
24.6 MB; lineitem 4 + 4.29 + 4 + 3×4 = 28.29 B/row = 169.8 MB; native total (inferred) ≈ 194.4 MB.

## Selectivities (DuckDB-CPU on the same Parquet)

- lineitem rows 6,001,215; shipmode IN (TRUCK, REG AIR): 1,713,866 (28.56%); additionally receiptdate in 1994: 259,905 (4.33%).
- l_commitdate < l_receiptdate: 3,793,296 (63.2%); l_shipdate < l_commitdate: 2,926,558 (48.8%).
- All lineitem predicates together: **30,912 rows (0.515%)**, touching 29,028 distinct orders (1.94% of 1,500,000 orders).
- Join: every qualifying lineitem row has an order (FK), so 30,912 rows reach the group-by; result = 2 groups (76 B CSV).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 134.34 MB | **199.9 µs** |
| A'. Same at native widths (inferred) | 194.4 MB | 289.2 µs |
| A-min. Only what predicates force (sector granularity ignored, inferred native widths): l_shipmode on all rows 6,001,215 × 8.29 B = 49.8 MB; three date columns of the 1,713,866 shipmode matches 20.6 MB; l_orderkey of 30,912 rows 0.1 MB; o_orderkey of all orders 6.0 MB; o_orderpriority of 29,028 matches 0.4 MB | ≈ 76.8 MB | 114.3 µs |
| B. A + materialising the filtered lineitem (30,912 rows) and the orders after the dynamic filter (29,028 rows), ~0.4 MB written + read (inferred) | ≈ 134.7 MB | ≈ 200.5 µs |

Q12 is a **~134 MB, ~200 µs** problem for the memory system (narrowed, read once): lineitem is 81.7% of pinned bytes and the five predicate columns
are the only lineitem columns present; after the predicates only 30,912 rows survive.

Compute: string compare on l_shipmode for 6.0 M rows (2 compares), 4 date compares on the survivors (~1.7 M rows), join probe of 30.9 K / 1.5 M rows,
priority string compares on 30.9 K rows, 2-group aggregation. ≈ 0.05 G simple ops; at ~14 T lane-ops/s that is **< 10 µs** (inferred).
Q12 is bandwidth-floor-bound at ~200 µs, but a real implementation is bounded by **latency and launch count**: the nsys run shows 86 kernels per
iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from Q2's analysis, not re-measured here) the GPU-side launch floor is
~0.17 ms (inferred; an implementation bound, reported separately).
