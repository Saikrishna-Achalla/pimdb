# TPC-H Q3 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query: customer (c_mktsegment = 'HOUSEHOLD') ⋈ orders (o_orderdate < 1995-03-25) ⋈ lineitem (l_shipdate > 1995-03-25),
GROUP BY l_orderkey, o_orderdate, o_shippriority, SUM(l_extendedprice*(1-l_discount)), ORDER BY revenue DESC, o_orderdate, LIMIT 10.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| customer | 150,000 | c_mktsegment, c_custkey | 2,549,760 (17.0 B/row) |
| orders | 1,500,000 | o_custkey, o_orderkey, o_orderdate, o_shippriority | 16,500,480 (11.0 B/row) |
| lineitem | 6,001,215 | l_orderkey, l_extendedprice, l_discount, l_shipdate | 84,017,920 (14.0 B/row) |
| **Total** | | | **103,068,160 B (103.07 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the three `pin_table` calls
(2,549,760 -> 19,050,240 -> 103,068,160). Sirius narrows carriers at pin time, so these are below native widths
(14 B/row for the 4 lineitem columns vs 24 B with int32 keys/dates + int64 decimals, inferred).

Selectivities / cardinalities (DuckDB-CPU on the same Parquet):
- c_mktsegment = 'HOUSEHOLD': 30,189 of 150,000 customers (20.1%)
- o_orderdate < 1995-03-25: 733,457 of 1,500,000 orders (48.9%)
- l_shipdate > 1995-03-25: 3,216,500 of 6,001,215 lineitems (53.6%)
- orders ⋈ qualifying customers (with date filter): 146,352 rows
- ⋈ lineitem (with ship filter): 30,004 rows
- groups: 11,295; result: 10 rows (376 B as CSV)

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 103.07 MB | **153.4 µs** |
| A-min (inferred widths). Only what predicates/join keys force: lineitem l_shipdate + l_orderkey for all rows (4+4 B × 6.0 M = 48.0 MB), l_extendedprice/l_discount only for the 30,004 matches (~0.5 MB), orders keys+date (12 B × 1.5 M = 18.0 MB), customer 2.55 MB | ≈ 69 MB | ≈ 103 µs |
| B (inferred). A + materialising the filtered lineitem (3.2165 M rows × ~12 B ≈ 38.6 MB) once as write + read, as a plan without pushed-down join filters would | ≈ 103.07 + 77.2 = 180 MB | ≈ 268 µs |

Intermediates after both selective joins are small (146 K, 30 K, 11 K rows); the dominant byte volume is the lineitem scan.
Q3 at SF1 is a **~100 MB, ~150 µs** problem for the memory system (≈ 5x Q2).

Compute: per-row work is two date compares on 7.2 M rows, hashing 733 K / 146 K build keys and 3.2 M probe keys (~20 integer ops each
≈ 80 M ops), an 11 K-group aggregation and a top-10 over 11 K rows. Total < 0.2 G simple ops; at 48 SMs × 4 warp-inst/clk × 32 lanes × ~2.3 GHz
(≈ 14 T lane-ops/s) that is **< 15 µs**. Q3 is bandwidth-floor-bound at ~150 µs, but a real implementation of a
multi-pipeline plan (16 Sirius pipelines, 3 hash-join/partition stages) is bounded by **latency and launch count**:

- A dependent chain of k kernels costs at least k × (launch + drain); the smallest kernels in a warm iteration take ~2 µs of GPU time each
  (Q2 measurement), so ~90 kernels imply a GPU-side floor of order 0.2 ms independent of data size. This is an implementation
  bound (inferred), reported in the gap analysis rather than as a physical floor.
