# TPC-H Q19 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q19.sql`): lineitem ⋈ part on partkey under a three-branch OR. Every branch has
`l_shipmode IN ('AIR','AIR REG')` and `l_shipinstruct = 'DELIVER IN PERSON'`; branch 1: `p_brand='Brand#41'`, container IN (SM CASE, SM BOX, SM PACK, SM PKG),
quantity 2..12, size 1..5; branch 2: `Brand#13`, MED BAG/BOX/PKG/PACK, quantity 14..24, size 1..10; branch 3: `Brand#55`, LG CASE/BOX/PACK/PKG,
quantity 23..33, size 1..15. One ungrouped `sum(l_extendedprice*(1-l_discount))`. Constants differ from standard TPC-H (Brand#41/13/55, quantities 2/14/23).

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_partkey, l_extendedprice, l_discount, l_quantity, l_shipmode, l_shipinstruct | 241,758,208 |
| part | 200,000 | p_partkey, p_brand, p_container, p_size | 5,715,712 |
| **Total** | | | **247,473,920 B (247.47 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 241,758,208 after the lineitem pin, 247,473,920 after the part pin
(delta 5,715,712). Pinned per row: lineitem 40.28 B, part 28.58 B; lineitem is 97.69% of pinned bytes. Native widths (inferred from Parquet types via DuckDB-CPU:
INTEGER keys/size 4 B, DECIMAL(15,2) assumed 8 B, VARCHAR with mean lengths l_shipmode 4.29, l_shipinstruct 12.00, p_brand 8.00, p_container 7.57 chars, plus an
assumed 4 B offset per string): lineitem 4+8+8+8+(4.29+4)+(12.00+4) = 52.28 B/row = 313.8 MB; part 4+(8+4)+(7.57+4)+4 = 31.57 B/row = 6.3 MB; native total (inferred)
≈ 320.1 MB. String data (inferred) is 24.29 of 52.28 native B/row (46.5%) of lineitem including offsets, 16.29 B (31.2%) characters only.
(The pinned size is below native, so Sirius narrows carriers; the split between string and numeric pinned bytes is not in the log.)

## Selectivities and cardinalities (DuckDB-CPU on the same Parquet)

- lineitem rows 6,001,215. `l_shipmode IN (AIR, AIR REG)`: 858,104 (14.30%); `l_shipinstruct = DELIVER IN PERSON`: 1,500,048 (24.99%); both: **214,377 (3.572%)**;
  both plus the union of the three quantity ranges (2..12, 14..24, 23..33): 132,726 (2.212%).
- part rows 200,000. Part-side predicate (the 3 brand/container/size conjunctions OR-ed): **510 rows (0.255%)** — matches the "510 build rows" of the dynamic-filter
  publication line in the Sirius log; brand alone in the three brands: 24,026 (12.0%).
- Join with both sides pre-filtered (but without per-branch quantity ranges): 583 rows; final rows satisfying the full OR predicate: **138 rows** (23.7% of 583).
- Result: 1 row (`revenue` = 4332821.7153, 21 B CSV).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 247.47 MB | **368.3 µs** |
| A'. Same at native widths (inferred) | 320.1 MB | 476.3 µs |
| A-min. Only what predicates force (inferred native widths): both lineitem string columns on all rows (24.29 B × 6,001,215 = 145.7 MB), 4 numeric columns of the 214,377 string survivors (6.0 MB), all part columns for 200,000 rows (6.3 MB) | ≈ 158.1 MB | 235.2 µs |
| B. A + materialising the 214,377 string-filter survivors (4 columns × ~7 B, written + read, 12.0 MB) (inferred) | ≈ 259.5 MB | ≈ 386.1 µs |

Q19 is a **~247 MB, ~370 µs** problem for the memory system (narrowed, read once). 97.7% of the bytes are lineitem; the two string predicates (shipmode, shipinstruct)
cut it to 3.57% before the join; the part side is 0.255% after its filter.

Compute: string tests on 6.0 M rows × 2 columns (an IN-list of 2 and an equality), part-side tests on 200 K rows (brand ×3, container IN ×12, size), a hash/semi-join
probe of ≤ 214 K rows against 510 build rows, per-branch quantity/size residual on 583 rows, one reduction. ≈ 0.05 G simple ops; at ~14 T lane-ops/s that is **< 10 µs** (inferred).
Q19 is bandwidth-floor-bound at ~370 µs, but a real implementation is bounded by **latency and launch count**: the nsys run shows 175 kernels per iteration
(`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from Q2's analysis, not re-measured here) the GPU-side launch floor is ~0.35 ms (inferred; reported separately).
