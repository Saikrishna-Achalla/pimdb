# TPC-H Q17 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q17.sql`): `sum(l_extendedprice)/7.0` over lineitem ⋈ part with
p_brand = 'Brand#13' and p_container = 'JUMBO CAN' and `l_quantity < (select 0.2*avg(l_quantity) from lineitem l2 where l2.l_partkey = p.p_partkey)`.
Brand/container constants are not the standard TPC-H ones. Result: one DOUBLE row, 376087.5371428571 (`result.csv`).

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_partkey, l_extendedprice, l_quantity | 72,015,360 |
| part | 200,000 | p_partkey, p_brand, p_container | 5,515,520 |
| **Total** | | | **77,530,880 B (77.53 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 72,015,360 after the first pin (lineitem), 77,530,880 after the second
(delta 5,515,520). Pinned per row: lineitem 12.00 B, part 27.58 B. Native widths (inferred from Parquet types via DuckDB-CPU: l_partkey INTEGER,
l_quantity and l_extendedprice DECIMAL(15,2) assumed 8 B each, p_partkey INTEGER, mean string lengths p_brand 8.0 and p_container 7.575, plus an assumed 4 B
offset per string): lineitem 20 B/row = 120.02 MB; part 4 + 12.0 + 11.575 = 27.575 B/row = 5.515 MB (equals the pinned figure); native total (inferred) ≈ 125.54 MB.

## Selectivities and intermediate cardinalities (DuckDB-CPU on the same Parquet)

- part rows 200,000; p_brand = 'Brand#13' AND p_container = 'JUMBO CAN': **231 parts** (0.1155%).
- lineitem rows 6,001,215; rows joining those 231 parts: **6,984** (0.116%); distinct l_partkey in lineitem: 200,000.
- Per-part average over those rows (the decorrelated subquery) has 231 groups; rows surviving `l_quantity < 0.2*avg`: **636**.
- Final: one row, 376087.5371428571.
- Sirius plan (`query_plan.txt`): GPU_SCAN ids 0 and 3 (two scans: part, lineitem), one DYNAMIC_FILTER (id 4) on the lineitem scan, HASH_JOIN id 7
  (part ⋈ lineitem) feeding a CTE (id 10) that is consumed twice: by HASH_GROUP_BY id 12 (avg per partkey) and by the probe side of HASH_JOIN id 21; lineitem is scanned once.

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 77.53 MB | **115.4 µs** |
| A'. Same at native widths (inferred) | ≈ 125.54 MB | ≈ 186.8 µs |
| A-min. Only what predicates force (sector granularity ignored, inferred native widths): l_partkey on all rows 6,001,215 × 4 B = 24.0 MB; part 5.52 MB; l_quantity + l_extendedprice of the 6,984 matches × 16 B = 0.11 MB | ≈ 29.6 MB | 44.1 µs |
| B. A + materialising the 6,984 joined rows (20 B each) once written and once read (~0.28 MB, inferred) | ≈ 77.81 MB | ≈ 115.8 µs |

Q17 is a **~78 MB, ~115 µs** problem for the memory system (narrowed, read once): lineitem is 92.9% of pinned bytes, but only l_partkey of it has to be read in
full; after the part semijoin 6,984 rows (0.116%) survive.

Compute: 6.0 M hash probes of l_partkey (build side 231 keys), a 6,984-row/231-group average, a 6,984-row second join and one reduction ≈ 0.03 G simple ops;
at ~14 T lane-ops/s that is **< 10 µs** (inferred). Q17 is bandwidth-floor-bound at ~115 µs, but a real implementation is bounded by **latency and launch count**:
the nsys run shows 74 kernels per iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from Q2's analysis, not re-measured here) the GPU-side
launch floor is ~0.15 ms (inferred; an implementation bound, reported separately).
