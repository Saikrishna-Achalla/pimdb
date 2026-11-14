# TPC-H Q9 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.
Note: the generated query (`sql/q9_timing.sql`) uses `p.p_name LIKE '%yellow%'` (the pipeline's substitution parameter), not `%green%`; all selectivities below are for `yellow`.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_suppkey, l_partkey, l_orderkey, l_extendedprice, l_discount, l_quantity | 132,028,416 |
| part | 200,000 | p_partkey, p_name | 8,150,528 |
| partsupp | 800,000 | ps_suppkey, ps_partkey, ps_supplycost | 8,000,000 |
| orders | 1,500,000 | o_orderkey, o_orderdate | 9,000,192 |
| supplier | 10,000 | s_suppkey, s_nationkey | 30,464 |
| nation | 25 | n_nationkey, n_name | 768 |
| **Total** | | | **157,210,368 B (157.21 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the six `pin_table` calls in pin order part, supplier, lineitem,
partsupp, orders, nation (8,150,528 -> 8,180,992 -> 140,209,408 -> 148,209,408 -> 157,209,600 -> 157,210,368; first value is the first QueryEnd line seen after the pin of part, the part delta is taken from it).
Sirius narrows carriers at pin time: lineitem = 22.0 B/row pinned (inferred native: 4+4+4+8+8+8 = 36 B/row = 216.04 MB, DECIMAL(15,2) x3 assumed 8 B);
partsupp = 10.0 B/row (native 4+4+8 = 16 B/row = 12.8 MB); orders = 6.0 B/row (native 4+4 = 8 B/row = 12.0 MB); part: p_name is VARCHAR, total characters 6,550,221 B
(DuckDB-CPU `sum(length(p_name))`, avg 32.75 B) + 0.8 MB int keys, pinned 8.15 MB used as is. Native-width total (inferred) = 216.04 + 12.8 + 12.0 + 8.15 + 0.08 = **249.1 MB**.

Selectivities / cardinalities (DuckDB-CPU on the same Parquet, measured):
- `p_name LIKE '%yellow%'`: 10,992 of 200,000 parts (5.50%); partsupp rows of such parts: 43,968 (5.50%); lineitem rows of such parts: 330,610 (5.51% of 6,001,215).
- lineitem ⨝ part ⨝ partsupp(ps_partkey, ps_suppkey): 330,610 rows (every lineitem row has exactly one partsupp match; no further reduction).
- distinct orders touched: 296,782 of 1,500,000 (19.8%). supplier and nation joins are lookups (no reduction).
- Group-by (nation, o_year): 25 nations x 7 years -> 175 groups (176 lines incl. header in `result.csv`).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 157.21 MB | **233.9 µs** |
| A'. Same at native widths (inferred widths) | 249.1 MB | 370.6 µs |
| A-min. Only what predicates/joins force (sector granularity ignored): p_name + p_partkey 8.15 MB, l_partkey on all rows 24.0 MB, other 5 lineitem columns of the 330,610 survivors 10.6 MB (32 B), ps_partkey+ps_suppkey 6.4 MB + ps_supplycost of 43,968 rows 0.35 MB, o_orderkey 6.0 MB + o_orderdate of 296,782 orders 1.2 MB, supplier+nation 0.08 MB | ≈ 56.8 MB | 84.5 µs |
| B. A + materialising three 330,610-row intermediates (~36 B/row, written once and read once = 3 x 23.8 MB) | ≈ 157.2 + 71.4 = 228.6 MB | 340.2 µs |

Largest stream is lineitem (84% of pinned bytes), then part's p_name (full scan for LIKE), orders and partsupp. Unlike a very selective query, 5.5% of lineitem survives
(330,610 rows), so the join intermediates are not negligible. Q9 at SF1 is therefore a **~157 MB, ~234 µs** problem for the memory system (narrowed, read once), ~340 µs with intermediates.

Compute: LIKE over 6.55 M characters (~11-character pattern, ~72 M char compares worst case), l_partkey probe of 6.0 M rows (~15 ops incl. hash), composite-key probe of
330 K rows into an 800 K-row table, orders probe, supplier/nation lookups, amount arithmetic and group-by on 330,610 rows (~50 ops each). Total ≈ 0.25 G simple ops; at
48 SMs x 4 warp-inst/clk x 32 lanes x ~2.3 GHz (≈ 14 T lane-ops/s) that is **< 20 µs** (inferred). The floor is bandwidth, but a real implementation is bounded by
**latency and launch count**: the nsys run shows 144 kernels per iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (measured on Q2, imported, not re-measured here)
the GPU-side launch floor is ~0.29 ms independent of data size (inferred; an implementation bound reported separately in the gap analysis).

Measured values and the gap against these floors are in `REPORT_tpch_q9_sf1.md` (§5, §10).
