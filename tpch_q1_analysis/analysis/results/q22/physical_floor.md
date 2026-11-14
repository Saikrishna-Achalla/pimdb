# TPC-H Q22 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q22.sql`): country codes substring(c_phone,1,2) IN
('24','31','11','16','21','20','34') used as a filter and as the group key; scalar subquery avg(c_acctbal) over customers with
c_acctbal > 0 and the same code list; NOT EXISTS anti-join against orders on o_custkey; group by cntrycode (7 groups), ORDER BY cntrycode.
Plan (`query_plan.txt`): 3 GPU_SCAN operators (ids 0, 8, 22): id 0 and id 8 scan customer, id 22 scans orders.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| customer | 150,000 | c_custkey, c_phone, c_acctbal | 4,050,432 |
| orders | 1,500,000 | o_custkey | 6,000,128 |
| **Total** | | | **10,050,560 B (10.05 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 4,050,432 after the customer pin, 10,050,560 after the orders pin
(delta 6,000,128). Pinned per row: customer 27.00 B, orders 4.00 B. Native widths (inferred from Parquet types via DuckDB `describe`: c_custkey INTEGER 4 B,
c_phone VARCHAR (mean length 15.0 chars) + an assumed 4 B offset = 19 B, c_acctbal DECIMAL(15,2) assumed 8 B, o_custkey INTEGER 4 B): customer 31 B/row = 4.65 MB,
orders 6.00 MB; native total (inferred) 10.65 MB.

## Selectivities and cardinalities (DuckDB-CPU on the same Parquet)

- customer rows 150,000; code in the 7-code list: 42,030 (28.0%); additionally c_acctbal > 0: 38,176 rows, avg(c_acctbal) = 5011.385 (the scalar subquery input).
- code in list AND c_acctbal > avg: 19,125 rows; of those with no order: **6,424 rows** reach the group-by (sum of the 7 numcust in `result.csv` = 6,424).
- orders 1,500,000 rows, 99,996 distinct o_custkey; customers with no order (all 150,000 customers): 50,004 (33.3%).
- Result: 7 groups.

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 10.05 MB | **15.0 µs** |
| A'. Same at native widths (inferred) | 10.65 MB | 15.8 µs |
| A-min. Predicate/join columns only: every referenced column is used (phone, acctbal for the subquery and filter, custkey for the join, o_custkey for the anti-join), so A-min = A' (inferred) | 10.65 MB | 15.8 µs |
| B. A + materialising the filtered customer rows (≤ 42,030 rows x ~12 B ≈ 0.5 MB written + read, inferred) | ≈ 11.1 MB | ≈ 16.5 µs |

Q22 is a **~10 MB, ~15 µs** problem for the memory system: 60% of the pinned bytes are the orders o_custkey column (6.0 of 10.05 MB). Only a few
dozen thousand customer rows survive the filters.

Compute: substring + 7-way string IN-test on 150,000 phones (twice, for two scans), a decimal compare and avg over 42,030 rows, a hash anti-join of
~19 K probe keys against 1.5 M order keys, a 7-group aggregation and a 7-row sort ≈ 0.01 G simple ops; at ~14 T lane-ops/s that is **< 5 µs** (inferred).
Q22 is bandwidth-floor-bound at ~15 µs, but a real implementation is bounded by **latency and launch count**: the nsys run shows 124 kernels per
iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from earlier analyses, not re-measured here) the GPU-side launch floor is
~0.25 ms (inferred; an implementation bound, reported separately).
