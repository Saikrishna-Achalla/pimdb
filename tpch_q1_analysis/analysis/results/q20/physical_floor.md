# TPC-H Q20 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q20.sql`): suppliers of nation 'KENYA' whose `s_suppkey IN (partsupp rows whose
`ps_partkey IN (parts with p_name LIKE 'antique%')` AND `ps_availqty > 0.5 * sum(l_quantity)` over lineitem rows with the same (partkey, suppkey) and
`l_shipdate` in [1993-01-01, 1994-01-01))`; ORDER BY s_name. Two IN-semi-joins plus one correlated scalar subquery; 5 tables.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) | B/row |
|---|---:|---|---:|---:|
| supplier | 10,000 | s_suppkey, s_name, s_address, s_nationkey | 540,928 | 54.09 |
| partsupp | 800,000 | ps_suppkey, ps_partkey, ps_availqty | 6,400,000 | 8.00 |
| part | 200,000 | p_partkey, p_name | 8,150,528 | 40.75 |
| lineitem | 6,001,215 | l_partkey, l_suppkey, l_quantity, l_shipdate | 72,015,360 | 12.00 |
| nation | 25 | n_nationkey, n_name | 768 | 30.72 |
| **Total** | | | **87,107,584 B (87.11 MB)** | |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 540,928 / 6,940,928 / 15,091,456 / 87,106,816 / 87,107,584 after the
supplier / partsupp / part / lineitem / nation pins (pin order of `sql/q20_timing.sql`). lineitem is 82.7% of pinned bytes. Sirius narrows carriers, so the
pinned widths are below native (lineitem 12.00 B/row pinned vs 20 B/row native; the per-column narrowing is not in the log, so it is not claimed here).
Native widths (inferred from Parquet types via DuckDB-CPU: INTEGER keys 4 B, DATE 4 B, `l_quantity` DECIMAL(15,2) assumed 8 B, ps_availqty INTEGER; string mean
lengths p_name 32.75, s_name 18.00, s_address 24.98, n_name 7.08 chars, + 4 B offset per string): lineitem 120.02 MB, partsupp 9.60 MB, part 8.15 MB,
supplier 0.59 MB, nation ~0.0005 MB; native total (inferred) ≈ 138.36 MB.

## Selectivities and intermediate cardinalities (DuckDB-CPU on the same Parquet)

- part: `p_name LIKE 'antique%'` 2,186 of 200,000 (1.09%). partsupp rows of those parts: 8,744 (1.09% of 800,000).
- lineitem in [1993-01-01, 1994-01-01): 908,721 (15.14%); of those with an antique part: 9,919 (0.165% of lineitem); distinct (l_partkey, l_suppkey)
  groups of the year: 542,941, of antique parts: 5,947.
- partsupp rows (antique) with ps_availqty > 0.5 × sum: 5,935 of 8,744; distinct suppliers among them: 4,515 (of 10,000).
- nation 'KENYA' suppliers: 376. Result = **181 rows** (`result.csv`).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 87.11 MB | **129.6 µs** |
| A'. Same at native widths (inferred) | 138.36 MB | 205.9 µs |
| A-min. Only what predicates force (inferred native widths): l_shipdate on all rows 24.0 MB; l_partkey of the 908,721 date matches 3.6 MB; l_suppkey+l_quantity of 9,919 rows 0.12 MB; p_name+offset on all parts 7.35 MB; ps_partkey of all partsupp 3.2 MB; ps_suppkey+ps_availqty of 8,744 rows 0.07 MB; supplier/nation columns of the 376 KENYA rows ≈ 0.05 MB (sector granularity ignored) | ≈ 38.4 MB | 57.2 µs |
| B1. A + write+read of intermediates if the semi-join filters cut lineitem to 9,919 rows before the group-by (9,919×12 B + 5,947×16 B + 8,744×12 B, written and read, inferred) | ≈ 87.75 MB | ≈ 130.6 µs |
| B2. A + write+read of the 908,721 date-qualified lineitem rows × 12 B (if no filter reaches the lineitem scan; inferred) | ≈ 108.9 MB | ≈ 162.1 µs |

Q20 is an **~87 MB, ~130 µs** problem (narrowed, read once): lineitem is 82.7% of the pinned bytes, but only 0.165% of its rows survive the nested semi-joins;
the plan's DYNAMIC_FILTER operators (ids 4, 29, 41, 42, 47 in `query_plan.txt`) can cut them early. Only 181 rows come out.

Compute: LIKE prefix compare on 200 K names, date range compare on 6.0 M rows, hash join / group-by of 908,721 (or 9,919) rows into 542,941 (or 5,947)
groups, 5 hash joins in all, ORDER BY of 181 rows. ≈ 0.05 G simple ops; at ~14 T lane-ops/s that is **< 10 µs** (inferred).
The plan has 5 GPU_SCAN, 5 HASH_JOIN (ids 7, 18, 32, 45, 50) and 2 HASH_GROUP_BY operators (ids 23, 35); the nsys run shows 142 kernels per
iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (an assumption, not measured here) the launch-count bound is ~0.28 ms (inferred; an
implementation bound, reported separately).
