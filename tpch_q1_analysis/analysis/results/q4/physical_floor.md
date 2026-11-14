# TPC-H Q4 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Native type | Pinned bytes (gpu_pool `allocated=` delta after each `pin_table`) |
|---|---:|---|---|---:|
| orders | 1,500,000 | o_orderkey, o_orderdate, o_orderpriority | INT32, DATE, VARCHAR (12,599,829 chars, max 15) | 27,600,384 |
| lineitem | 6,001,215 | l_orderkey, l_commitdate, l_receiptdate | INT32, DATE, DATE | 48,009,984 (8.0 B/row) |
| **Total** | | | | **75,610,368 B (75.61 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after `pin_table` for orders (27,600,384; this is the first allocation, baseline 0)
and after lineitem (75,610,368). Sirius narrows carriers (lineitem 8 B/row instead of 12 B native). Native widths would be
lineitem 72.01 MB + orders (12.0 MB keys/dates + 12.60 MB priority chars + 6.0 MB int32 offsets = 30.6 MB) = **102.6 MB**.

Cardinalities (DuckDB-CPU on the same Parquet):
- `o_orderdate in [1996-10-01, 1997-01-01)` keeps 57,515 of 1,500,000 orders (3.83%).
- `l_commitdate < l_receiptdate` keeps 3,793,296 of 6,001,215 lineitem rows (63.2%); 1,375,365 distinct order keys among them.
- lineitem rows whose l_orderkey is in the 57,515 qualifying-date orders = 230,667 (3.84%); of those with commit < receipt = 145,479.
- Orders that satisfy both predicates (EXISTS true) = 52,802 (91.8% of date-qualified orders).
- Result = 5 groups (o_orderpriority), 105 B as CSV.

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 75.61 MB | **112.5 µs** |
| A'. Same at native widths | 102.6 MB | 152.7 µs |
| A-min. What the predicates/join force at native widths: all 3 lineitem columns (72.0 MB), o_orderkey + o_orderdate (12.0 MB), o_orderpriority only for the 57,515 date-qualified orders (~1 MB incl. offsets) | ≈ 85 MB | 126 µs |
| B. A + materialising the filtered lineitem keys once (write + read) in a plan with no dynamic/Bloom filter on the probe side: 3,793,296 × 4 B = 15.2 MB, ×2 | ≈ 75.61 + 30.3 = 105.9 MB | 157.6 µs |

Selectivity helps only on the orders side. lineitem has no selective predicate of its own (63% pass), so all 6.0 M rows of three columns
must be read at least once; the 3.84% selectivity appears only after the join key is known (hash/Bloom on the 57,515 orders keys, 230,667 probe survivors).
Intermediates are small (57,515 × ~19 B ≈ 1.1 MB for qualifying orders; 230,667 × 4 B ≈ 0.9 MB for surviving lineitem keys) so Q4 at SF1 is a
**~76–105 MB, ~110–160 µs** problem for the memory system.

Compute: 6.0 M lineitem rows × (date compare + hash probe/Bloom test ≈ 20–30 integer ops) + 1.5 M orders rows × (date range + hash insert) ≈ 0.2 G simple ops;
at 48 SMs × 4 warp-inst/clk × 32 lanes × ~2.3 GHz (≈ 14 T lane-ops/s) that is **~15 µs**, well below the bandwidth floor (hash-table random access adds latency, not bytes, at this size: the build table of 57,515 keys fits in L2).
Q4 is therefore bandwidth-floor-bound at ~110–160 µs; there is no compute-bound floor.

Launch-count bound (inferred): the nsys run shows 56 kernels per iteration; the smallest kernels take ~2 µs each, so a dependent chain of 56 kernels
has an implementation floor of order 0.1 ms independent of bytes (same magnitude as the byte floor). This is an implementation bound, not a physical one.

Measured values and the gap against these floors are reported in the Q4 report.
