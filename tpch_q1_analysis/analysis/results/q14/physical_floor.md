# TPC-H Q14 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q14.sql`): `100.00 * sum(case when p_type like 'PROMO%' then l_extendedprice*(1-l_discount) else 0 end) / sum(l_extendedprice*(1-l_discount))`,
lineitem ⋈ part on partkey, l_shipdate in [1994-08-01, 1994-09-01); one DOUBLE result row.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_partkey, l_extendedprice, l_discount, l_shipdate | 84,017,920 |
| part | 200,000 | p_partkey, p_type | 5,720,320 |
| **Total** | | | **89,738,240 B (89.74 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 84,017,920 after the lineitem pin (first in `sql/q14_timing.sql`), 89,738,240 after the part pin
(delta 5,720,320). Pinned per row: lineitem 14.00 B, part 28.60 B. Native widths (inferred from Parquet types via DuckDB-CPU `typeof`: INTEGER, DECIMAL(15,2) x2 assumed 8 B each,
DATE 4 B; p_type VARCHAR mean length 20.60 chars + assumed 4 B offset): lineitem 4+8+8+4 = 24 B/row = 144.03 MB; part 4 + 20.60 + 4 = 28.6 B/row = 5.72 MB (equals the pinned
size, so part is already at native width); native total (inferred) ≈ 149.75 MB. Lineitem is 93.6% of the pinned bytes.

## Selectivities (DuckDB-CPU on the same Parquet)

- lineitem rows 6,001,215; l_shipdate in [1994-08-01, 1994-09-01): 77,041 (1.284%); distinct l_partkey among them: 63,924 (of 200,000 parts).
- part rows 200,000; p_type LIKE 'PROMO%': 33,174 (16.59%).
- Join is a FK match, so all 77,041 filtered rows reach the aggregate; of them 12,665 (16.44%) have a PROMO part. Result 1 row, 1 DOUBLE (`result.csv`: 16.45836327537756).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 89.74 MB | **133.5 µs** |
| A'. Same at native widths (inferred) | 149.75 MB | 222.8 µs |
| A-min. Only what predicates force (inferred native widths, sector granularity ignored): l_shipdate on all rows 24.0 MB; l_partkey+price+discount of 77,041 rows 1.54 MB; p_partkey of all parts 0.80 MB; p_type of 63,924 probed parts 1.57 MB | ≈ 27.9 MB | 41.5 µs |
| B. A + materialising the filtered lineitem (77,041 rows x ~12 B written + read, ~1.85 MB, inferred) | ≈ 91.6 MB | ≈ 136.3 µs |

Note on B: 89,738,240 + 77,041 × 12 B × 2 (= 1,848,984) B ≈ 91.59 MB → 136.3 µs. Q14 is a **~90 MB, ~134 µs** problem for the memory system (narrowed, read once).

Compute: date range compare on 6.0 M rows (2 compares), hash build of 200 K keys, probe of 77 K rows, LIKE 'PROMO%' prefix compare on 200 K (or 64 K) strings,
two multiply-adds and two sums over 77 K rows. ≈ 0.02 G simple ops; at ~14 T lane-ops/s that is **< 5 µs** (inferred).
Q14 is bandwidth-floor-bound at ~134 µs, but a real implementation is bounded by **latency and launch count**: the nsys run shows 46 kernels per iteration
(`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from earlier queries' analyses, not re-measured here) the GPU-side launch floor is
~0.09 ms (inferred; an implementation bound, reported separately).
