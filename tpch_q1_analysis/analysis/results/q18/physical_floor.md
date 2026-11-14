# TPC-H Q18 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q18.sql`): `o_orderkey IN (select l_orderkey from lineitem group by l_orderkey having
sum(l_quantity) > 300)`, customer ⋈ orders ⋈ lineitem, group by (c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice), sum(l_quantity),
ORDER BY o_totalprice DESC, o_orderdate LIMIT 100. The threshold is 300 as written in the file.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| customer | 150,000 | c_name, c_custkey | 3,900,160 |
| orders | 1,500,000 | o_orderkey, o_custkey, o_orderdate, o_totalprice | 21,000,448 |
| lineitem | 6,001,215 | l_orderkey, l_quantity | 48,009,728 |
| **Total** | | | **72,910,336 B (72.91 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 3,900,160 after the customer pin, 24,900,608 after orders, 72,910,336 after
lineitem (deltas 21,000,448 and 48,009,728). Pinned per row: customer 26.00 B, orders 14.00 B, lineitem 8.00 B. Native widths (inferred from Parquet types via DuckDB-CPU:
INTEGER keys 4 B, DATE 4 B, DECIMAL(15,2) 8 B, c_name mean length 18.0 chars + assumed 4 B offset): customer 4 + 22 = 26 B/row = 3.9 MB; orders 4+4+4+8 = 20 B/row = 30.0 MB;
lineitem 4 + 8 = 12 B/row = 72.0 MB; native total (inferred) ≈ 105.9 MB. Sirius narrows the two DECIMAL columns (lineitem 8.00 B/row and orders 14.00 B/row imply 4 B each for l_quantity and o_totalprice; inferred).

## Cardinalities (DuckDB-CPU on the same Parquet)

- lineitem rows 6,001,215; distinct l_orderkey 1,500,000 -> the inner group-by has **1,500,000 groups** (4.0 rows per group on average).
- Groups with sum(l_quantity) > 300: **57** (0.0038% of groups); for reference > 250 would give 6,621 (not the query).
- Orders matching the IN: 57; customers of those orders: 57; lineitem rows of those orders: **399** (0.0066% of 6,001,215).
- Result: 57 rows (fewer than LIMIT 100), 3,558 B of CSV (`result.csv`).
- Plan (`query_plan.txt`, counted by distinct ids): 4 GPU_SCANs (ids 0 customer, 3 lineitem, 10 orders, 20 lineitem), 3 HASH_JOINs (14, 17, 24), 2 DYNAMIC_FILTERs (11, 21), 2 HASH_GROUP_BYs (4, 27), 1 TOP_N (31).
  lineitem is scanned **twice** (ids 3 and 20), table assignment taken from the "assigned pinned entry" lines of the Sirius log.

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 72.91 MB | **108.5 µs** |
| A'. Same at native widths (inferred) | 105.9 MB | 157.6 µs |
| A''. As planned: lineitem pinned columns read in both scans (2 × 48.01 MB) + orders + customer | 120.92 MB | 179.9 µs |
| A-min. Only what the predicates force (narrowed): scan 1 of lineitem (l_orderkey + l_quantity, all rows) 48.01 MB; o_orderkey of all orders 6.0 MB; scan 2 of lineitem l_orderkey only 24.0 MB (the 399 quantities, 57 orders, 57 customers are negligible) | ≈ 78.0 MB | 116.1 µs |

Q18 is a **~73-121 MB, ~110-180 µs** problem for the memory system. Compute: the inner group-by is 6.0 M hash-aggregate updates into 1.5 M groups (a hash table of
1.5 M × (key + sum) ≈ 18 MB at 12 B/entry, inferred) plus a 1.5 M-row filter; one sort-based or hash group-by over 6.0 M rows is of order 6 M × ~50 simple ops = 0.3 G ops, at ~14 T lane-ops/s
≈ 20 µs (inferred). The random hash-table traffic (6.0 M random 4-8 B updates into an ~18 MB table that fits the 48 MB L2) adds L2-bound work not counted in bytes: a single
32 B sector per update gives at most 6.0 M × 32 B = 192 MB of L2 sector traffic (inferred upper bound, ≈ 0.29 ms at the DRAM rate if it all missed). The final join side is only 57-399 rows.
The nsys run shows 127 kernels per iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from Q2's analysis, not re-measured here) the launch floor is ~0.25 ms (inferred; an implementation bound, reported separately).
