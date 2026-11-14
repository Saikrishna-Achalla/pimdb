# TPC-H Q10 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query constants (from `sirius/test/tpch_performance/tpch_queries/orig/q10.sql`): o_orderdate in [1994-03-01, 1994-06-01), l_returnflag = 'R',
group by 7 columns (c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment), ORDER BY revenue DESC LIMIT 20.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| customer | 150,000 | c_custkey, c_name, c_acctbal, c_address, c_phone, c_comment, c_nationkey | 23,334,912 |
| orders | 1,500,000 | o_custkey, o_orderkey, o_orderdate | 15,000,320 |
| lineitem | 6,001,215 | l_orderkey, l_extendedprice, l_discount, l_returnflag | 102,021,888 |
| nation | 25 | n_nationkey, n_name | 768 |
| **Total** | | | **140,357,888 B (140.36 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the four `pin_table` calls, in pin order
(23,334,912 -> 38,335,232 -> 140,357,120 -> 140,357,888). Deltas: customer 23,334,912; orders 15,000,320; lineitem 102,021,888; nation 768.
Per-row pinned width: lineitem 17.0 B/row, orders 10.0 B/row; customer 155.6 B/row because of four VARCHAR columns.
Customer string bytes (DuckDB-CPU on the Parquet): c_name 2,700,000 B, c_address 3,758,056 B, c_phone 2,250,000 B, c_comment 10,876,099 B =
19,584,155 chars (130.6 B/row); the largest pin-phase D2D copy in `pcie_verification.txt` (10,876,099 B) equals the c_comment char total.
Native-width total (inferred): lineitem 4+8+8+1 = 21 B/row = 126.03 MB (DECIMAL(15,2) assumed 8 B, returnflag 1 B, no offsets); orders 12 B/row =
18.00 MB; customer 19.58 MB chars + 4 offset arrays (4 x 150,001 x 4 B = 2.40 MB) + 16 B/row fixed (2.40 MB) = 24.38 MB; nation < 0.01 MB.
Native total = **168.41 MB**.

Selectivities (DuckDB-CPU on the same Parquet):
- o_orderdate in [1994-03-01, 1994-06-01): 57,420 of 1,500,000 orders (3.83%); these come from 42,567 distinct customers.
- l_returnflag = 'R': 1,478,870 of 6,001,215 lineitem rows (24.6%).
- lineitem rows that are 'R' AND belong to a date-qualifying order: 114,929 (1.92% of lineitem).
- Groups (distinct customers among those rows): 37,922; nation join adds no filtering (25 rows, every customer has a nation); result = 20 rows, 3,538 B as CSV.

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 140.36 MB | **208.9 µs** |
| A'. Same at native widths (inferred widths) | 168.41 MB | 250.6 µs |
| A-min. Only what predicates/joins force (sector granularity ignored): l_orderkey 24.0 MB + l_returnflag 6.0 MB on all lineitem, o_orderdate 6.0 MB on all orders, o_orderkey+o_custkey of 57,420 orders 0.46 MB, price+discount of 114,929 rows 1.84 MB, c_custkey 0.60 MB, string payload only for the 20 result rows (~0) | ≈ 38.9 MB | 57.9 µs |
| B. A + materialising the 114,929-row join intermediate (24 B/row written + read = 5.5 MB) + customer string payload gathered for those 114,929 rows (130.6 B/row x 114,929 = 15.0 MB read + 15.0 MB written, an upper bound if strings are gathered before the group-by) | ≈ 175.9 MB | 261.7 µs |

Lineitem is 72.7% of pinned bytes (102.02 of 140.36 MB); customer is 16.6% because of the wide string columns, which a late-materialising plan
would touch only for 20 rows but which the 7-column GROUP BY forces through the join/group-by path. Q10 at SF1 is a **~140 MB, ~210 µs** problem for the
memory system (narrowed, read once), ~260 µs if the string payload is materialised before the group-by.

Compute: returnflag compare on 6.0 M rows (~2 ops), date predicate on 1.5 M orders (~2 ops), hash probes of 6.0 M (filtered) and 57 K / 150 K rows
(~15 ops each), revenue multiply on 114,929 rows, group-by on 114,929 rows into 37,922 groups, top-20 over 37,922. Total ≈ 0.15 G simple ops; at
48 SMs x 4 warp-inst/clk x 32 lanes x ~2.3 GHz (≈ 14 T lane-ops/s) that is **< 15 µs** (inferred).
Q10 is bandwidth-floor-bound at ~210 µs, but a real implementation is bounded by **latency and launch count**:

- A chain of k dependent kernels costs at least k x (launch + drain). The smallest kernels on this GPU take ~1.7–2 µs of GPU time (measured on Q2;
  imported from the Q2 analysis, not re-measured here). The nsys run shows 238 kernels per iteration (`pcie_verification.txt`); at ~2 µs each
  the GPU-side launch floor is ~0.48 ms independent of data size (inferred; an implementation bound, not a physical one).

Measured values and the gap against these floors are in `REPORT_tpch_q10_sf1.md` (§5, §10).
