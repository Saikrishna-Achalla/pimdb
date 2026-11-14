# TPC-H Q11 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q11.sql`): `partsupp ⋈ supplier ⋈ nation` with `n_name = 'GERMANY'`,
`GROUP BY ps_partkey HAVING sum(ps_supplycost*ps_availqty) > (same join, sum(...) * 0.00001)`, `ORDER BY value DESC`. The constant is 0.00001
as written in the file (not the standard 0.0001/SF).

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| partsupp | 800,000 | ps_partkey, ps_suppkey, ps_supplycost, ps_availqty | 9,600,000 |
| supplier | 10,000 | s_suppkey, s_nationkey | 30,464 |
| nation | 25 | n_nationkey, n_name | 768 |
| **Total** | | | **9,631,232 B (9.63 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the three `pin_table` calls, in pin order
(9,600,000 -> 9,630,464 -> 9,631,232). The plan has **6 GPU_SCANs** (partsupp, supplier, nation each twice: outer query and HAVING subquery;
`query_plan.txt`), all served from the three pinned entries.
Sirius narrows carriers at pin time: partsupp = 12.0 B/row pinned; supplier = 3.05 B/row. Inferred native widths from the Parquet types
(INTEGER, INTEGER, DECIMAL(15,2), INTEGER; assuming 8-byte decimals): partsupp 4+4+8+4 = 20 B/row = 16.0 MB; supplier 8 B/row = 0.08 MB;
nation (VARCHAR n_name, native width not available) pinned size 768 B used. Native-width total (inferred) = 16.0 + 0.08 + <0.01 = **16.08 MB**.

Cardinalities (DuckDB-CPU on the same Parquet):
- n_name = 'GERMANY': 1 of 25 nations; suppliers in Germany: 396 of 10,000 (3.96%).
- partsupp rows joining a German supplier: 31,680 of 800,000 (3.96%); distinct ps_partkey among them: 29,818 (group count).
- sum(ps_supplycost*ps_availqty) over those rows = 78,741,031,094.05; HAVING threshold (x 0.00001) = 787,410.31.
- Groups surviving HAVING = result rows: 21,953 of 29,818 (73.6%); result CSV = 381,659 B (`result.csv`).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 9.63 MB | **14.3 µs** |
| A2. Same, twice (the plan scans each table twice: 2 x 9,631,232 B) | 19.26 MB | **28.7 µs** |
| A'. A at native widths (inferred widths) | 16.08 MB | 23.9 µs |
| A'2. A' twice | 32.16 MB | 47.9 µs |
| A-min. Only what the predicates force, one evaluation of the join: ps_suppkey on all 800,000 rows (4 B) 3.2 MB + ps_partkey/supplycost/availqty of the 31,680 matches (16 B) 0.51 MB + supplier + nation 0.08 MB | ≈ 3.79 MB | 5.6 µs |
| B. A2 + materialising the 31,680-row join output twice (16 B, write + read, per evaluation = 2.03 MB), the 29,818-group aggregate (12 B write + read = 0.72 MB) and the 21,953-row result (12 B write + read = 0.53 MB) | ≈ 22.53 MB | 33.5 µs |

The whole problem is **~10–20 MB, ~15–35 µs** for the memory system. partsupp is 99.7% of pinned bytes; everything after the supplier/nation
semijoin works on 31,680 rows (3.96% of partsupp) and the 396-row German supplier set.

Compute: hash probe of 800,000 ps_suppkey against a 396-key build side (~15 ops), multiply of 31,680 rows, hash group-by of 31,680 rows into
29,818 groups, ungrouped sum, a 21,953-row filter and sort; two evaluations of the join. Total ≈ 0.04 G simple ops; at 48 SMs x 4 warp-inst/clk
x 32 lanes x ~2.3 GHz (≈ 14 T lane-ops/s) that is **< 5 µs** (inferred). Q11 is bandwidth-floor-bound at ~15–35 µs, but a real implementation
is bounded by **latency and launch count**:

- A chain of k dependent kernels costs at least k x (launch + drain). The nsys run shows 168 kernels per iteration (`pcie_verification.txt`);
  at ~2 µs each (the smallest-kernel figure measured on Q2, imported from the Q2 analysis via the Q8 floor note, not re-measured here) the
  GPU-side launch floor is ~0.34 ms independent of data size (inferred; an implementation bound, not a physical one, reported separately in the
  gap analysis).

Measured values and the gap against these floors are in `REPORT_tpch_q11_sf1.md` (§5, §10).
