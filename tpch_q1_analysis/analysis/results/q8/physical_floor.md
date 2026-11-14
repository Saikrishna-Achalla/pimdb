# TPC-H Q8 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_partkey, l_suppkey, l_orderkey, l_extendedprice, l_discount | 108,023,296 |
| part | 200,000 | p_partkey, p_type | 5,720,320 |
| supplier | 10,000 | s_suppkey, s_nationkey | 30,464 |
| orders | 1,500,000 | o_orderkey, o_custkey, o_orderdate | 15,000,320 |
| customer | 150,000 | c_custkey, c_nationkey | 750,080 |
| nation | 25 | n_nationkey, n_regionkey, n_name | 1,024 |
| region | 5 | r_regionkey, r_name | 768 |
| **Total** | | | **129,526,272 B (129.53 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the seven `pin_table` calls, in pin order
(108,023,296 -> 113,743,616 -> 113,774,080 -> 128,774,400 -> 129,524,480 -> 129,525,504 -> 129,526,272). `nation` is scanned twice (n1, n2)
from one pinned entry (8 GPU_SCANs for 7 tables).
Sirius narrows carriers at pin time: lineitem = 18.0 B/row pinned (inferred native: 4+4+4+8+8 = 28 B/row = 168.03 MB from the Parquet column
types INTEGER x3, DECIMAL(15,2) x2, assuming 8-byte decimals); orders = 10.0 B/row pinned (inferred native 4+4+4 = 12 B/row = 18.0 MB);
customer 5.0 B/row, supplier 3.0 B/row; part = 28.6 B/row (p_type is VARCHAR; native width not available, pinned size used).
Native-width total (inferred) = 168.03 + 18.00 + 5.72 + 1.20 + 0.08 + <0.01 = **193.0 MB**.

Selectivities (DuckDB-CPU on the same Parquet):
- p_type = 'PROMO BRUSHED COPPER': 1,259 of 200,000 parts (0.63%); lineitem rows with such a part: 37,666 (0.63% of 6,001,215).
- o_orderdate in [1995-01-01, 1996-12-31]: 457,263 of 1,500,000 orders (30.5%).
- MIDDLE EAST customers: 29,904 of 150,000 (19.9%); orders that are in the date range AND from those customers: 90,488 (6.0%).
- All joins (part, date, region-of-customer; supplier/nation lookups add no filtering): 2,241 lineitem rows survive; result = 2 groups (68 B as CSV).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 129.53 MB | **192.7 µs** |
| A'. Same at native widths (inferred widths) | 193.0 MB | 287.2 µs |
| A-min. Only what the predicates force (sector granularity ignored): l_partkey on all rows 24.0 MB, p_type + p_partkey 5.7 + 0.8 MB, o_orderdate on all orders 6.0 MB, o_orderkey+o_custkey of the 457,263 date-qualifying orders 3.7 MB, l_suppkey/orderkey/price/discount of the 37,666 part-matches 0.6 MB, customer + supplier + nation + region 0.8 MB | ≈ 41.6 MB | 61.9 µs |
| B. A + materialising the date-filtered orders once (457,263 rows × 12 B written + read = 11.0 MB) and the 37,666-row lineitem∩part intermediate (~20 B × 2 = 1.5 MB) | ≈ 129.5 + 11.0 + 1.5 = 142.0 MB | 211.3 µs |

The only large stream is lineitem (83% of pinned bytes; its l_partkey column alone is the probe against a 1,259-key build side); everything after
the part semi-filter works on < 38 K rows. Q8 at SF1 is therefore a **~130 MB, ~190 µs** problem for the memory system (narrowed, read once).

Compute: l_partkey probe against a 1,259-row table on 6.0 M rows (~15 ops incl. hash+compare), date predicate on 1.5 M orders (~2 ops), probes on
457 K / 37.7 K / 29.9 K-row sets, year extraction + volume multiply + CASE on 2,241 rows, group-by on 2,241 rows. Total ≈ 0.15 G simple ops; at
48 SMs × 4 warp-inst/clk × 32 lanes × ~2.3 GHz (≈ 14 T lane-ops/s) that is **< 15 µs** (inferred). Q8 is bandwidth-floor-bound at ~190 µs, but a
real implementation is bounded by **latency and launch count**:

- A chain of k dependent kernels costs at least k × (launch + drain). The smallest kernels on this GPU take ~1.7–2 µs of GPU time (measured on Q2;
  imported from the Q2 analysis, not re-measured here). The nsys run shows 172 kernels per iteration (`pcie_verification.txt`); at ~2 µs each
  the GPU-side launch floor is ~0.34 ms independent of data size (inferred; an implementation bound, not a physical one, reported separately in the
  gap analysis).

Measured values and the gap against these floors are in `REPORT_tpch_q8_sf1.md` (§5, §10).
