# TPC-H Q7 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| supplier | 10,000 | s_suppkey, s_nationkey | 30,464 |
| lineitem | 6,001,215 | l_suppkey, l_orderkey, l_shipdate, l_extendedprice, l_discount | 96,020,992 |
| orders | 1,500,000 | o_orderkey, o_custkey | 12,000,256 |
| customer | 150,000 | c_custkey, c_nationkey | 750,080 |
| nation | 25 | n_nationkey, n_name | 768 |
| **Total** | | | **108,802,560 B (108.80 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the five `pin_table` calls
(30,464 -> 96,051,456 -> 108,051,712 -> 108,801,792 -> 108,802,560). `nation` is scanned twice (n1, n2) from one pinned entry.
Sirius narrows carriers at pin time: lineitem = 16.0 B/row pinned (inferred native: 4+4+4+8+8 = 28 B/row = 168.03 MB, assuming
int32 keys/date and int64 decimals); orders = 8.0 B/row (no narrowing); customer 5.0 B/row; supplier 3.0 B/row.
Native-width total (inferred) = 168.03 + 12.00 + 1.20 + 0.08 + <0.001 = **181.3 MB**.

Selectivities (DuckDB-CPU on the same Parquet): `l_shipdate` in [1995-01-01, 1996-12-31] keeps 1,828,450 of 6,001,215 lineitem rows (30.5%);
nations EGYPT/UNITED STATES: 808 of 10,000 suppliers (8.1%), 11,978 of 150,000 customers (8.0%), 119,032 of 1.5 M orders (7.9%);
lineitem(date) ⋈ those suppliers = 148,529 rows (2.5% of lineitem; 8.1% of the date-filtered rows); ⋈ orders = 148,529; after
the customer join and the (EGYPT,US)/(US,EGYPT) pair predicate = 5,970 rows; result = 4 groups (195 B as CSV).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 108.80 MB | **161.9 µs** |
| A'. Same at native widths (inferred widths) | 181.3 MB | 269.8 µs |
| A-min. Only what the predicates force (sector granularity ignored): l_shipdate on all rows 24.0 MB, l_suppkey of the 1.83 M date-qualifying rows 7.3 MB, orderkey+price+discount of the 148,529 supplier-matches 3.0 MB, orders keys + customer + supplier + nation ≈ 1.5 MB | ≈ 35.8 MB | 53.3 µs |
| B. A + materialising the date-filtered lineitem once (1,828,450 rows × 24 B written + read = 87.8 MB), as the PARTITION/CONCAT plan does, plus the 148,529-row join output (~3.6 MB w+r) | ≈ 108.8 + 87.8 + 7.1 = 203.7 MB | 303.1 µs |

The only large stream is lineitem (88% of pinned bytes); every join after the first supplier/date semi-filter works on < 150 K rows.
Q7 at SF1 is therefore a **~110 MB, ~160 µs** problem for the memory system (narrowed, read once).

Compute: date predicate on 6.0 M rows (~2 ops), hash probes on 1.83 M rows (~30 ops incl. hash+compare) and 148 K / 119 K-row probes,
year extraction + volume multiply on 5,970 rows, group-by on 5,970 rows. Total ≈ 0.1 G simple ops; at 48 SMs × 4 warp-inst/clk × 32 lanes
× ~2.3 GHz (≈ 14 T lane-ops/s) that is **< 10 µs** (inferred). Q7 is bandwidth-floor-bound at ~160 µs, but a real implementation is bounded by
**latency and launch count**:

- A chain of k dependent kernels costs at least k × (launch + drain). The smallest kernels on this GPU take ~1.7–2 µs of GPU time
  (measured on Q2). The nsys run shows 207 kernels per iteration (`pcie_verification.txt`); at ~2 µs each the GPU-side launch floor is
  ~0.4 ms independent of data size (inferred; an implementation bound, not a physical one, reported separately in the gap analysis).

Measured values and the gap against these floors are in `REPORT_tpch_q7_sf1.md` (§5, §10).
