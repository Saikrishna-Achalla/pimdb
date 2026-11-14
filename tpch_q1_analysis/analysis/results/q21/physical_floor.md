# TPC-H Q21 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q21.sql`): supplier ⋈ lineitem l1 ⋈ orders (o_orderstatus = 'F') ⋈ nation (n_name = 'BRAZIL');
l1.l_receiptdate > l1.l_commitdate; `EXISTS` another lineitem l2 of the same order with a different l_suppkey; `NOT EXISTS` another lineitem l3 of the same order with a
different l_suppkey and l_receiptdate > l_commitdate; GROUP BY s_name; ORDER BY numwait DESC, s_name; LIMIT 100. lineitem is referenced three times.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| supplier | 10,000 | s_suppkey, s_nationkey, s_name | 250,880 |
| lineitem | 6,001,215 | l_suppkey, l_orderkey, l_receiptdate, l_commitdate | 60,013,568 |
| orders | 1,500,000 | o_orderkey, o_orderstatus | 13,500,416 |
| nation | 25 | n_nationkey, n_name | 768 |
| **Total** | | | **73,765,632 B (73.77 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 250,880 (supplier) → 60,264,448 (lineitem) → 73,764,864 (orders) → 73,765,632 (nation).
Pinned per row: lineitem 10.00 B, orders 9.00 B, supplier 25.09 B (Sirius narrows carriers). Native widths (inferred from Parquet types: INTEGER = 4 B, DATE = 4 B,
o_orderstatus VARCHAR 1 char + assumed 4 B offset = 5 B, s_name 18 chars + 4 B offset): lineitem 16 B/row = 96.02 MB; orders 9 B/row = 13.5 MB; supplier 30 B/row = 0.30 MB;
native total ≈ 109.82 MB.

## Selectivities and intermediate cardinalities (DuckDB-CPU on the same Parquet)

- lineitem rows 6,001,215; l_receiptdate > l_commitdate: 3,793,296 (63.2%).
- orders with o_orderstatus = 'F': 729,413 (48.6% of 1,500,000). nation BRAZIL: 1 row; suppliers in BRAZIL: 397 (of 10,000); their lineitem rows: 238,658, of which late: 150,857.
- l1 (late lineitem ⋈ F orders): 1,828,911 rows (30.5% of lineitem).
- orders with more than one distinct supplier: 1,285,803 of 1,500,000.
- l1 rows with EXISTS (another supplier on the order): 1,762,253; additionally NOT EXISTS (no other late supplier): 98,833 rows.
- After the supplier ⋈ nation join: **3,913 rows** reach the group-by; 397 candidate groups; result = 100 rows (LIMIT), 2,215 B CSV.
- Dynamic-filter build rows seen in the Sirius log (`traces/sirius_log_timing`): 1 (nation), 397 (supplier), 729,413 (orders).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 73.77 MB | **109.8 µs** |
| A'. Same at native widths (inferred): 96.02 + 13.50 + 0.30 MB | ≈ 109.82 MB | 163.4 µs |
| C. Every GPU scan reads its columns, native widths (inferred): l1 scan 16 B/row (96.02 MB), l3 scan 16 B/row (96.02 MB), l2 scan 8 B/row (48.01 MB), orders 13.5 MB, supplier 0.30 MB | ≈ 253.85 MB | **377.7 µs** |
| B. A + materialising the filtered/partitioned intermediates (l1 1.83 M rows × 8 B = 14.6 MB, l3 3.79 M × 8 B = 30.3 MB, l2 6.0 M × 8 B = 48.0 MB, written + read once, inferred) | ≈ 73.77 + 2 × 92.97 ≈ 259.7 MB | ≈ 386 µs |

Q21 is a **~74–260 MB, ~110–380 µs** problem for the memory system: the narrowed footprint is read once in 110 µs, but the plan has three GPU scans of lineitem, so the
realistic floor (scenario C) is ~0.38 ms. The 73.77 MB footprint plus the 232 MB high-water mark (from `pcie_verification.txt`) fit the 3 GB pool.

Compute: hash build on ~1.8 M l1 rows, three hash probes over up to 6.0 M rows each, an inequality (`<>`) semi/anti check per matched pair, partition/sort steps, a 397-group
aggregation: ≈ 0.3–0.5 G simple ops; at ~14 T lane-ops/s that is **≈ 20–40 µs** (inferred). Bandwidth-floor-bound at ~0.38 ms in principle, but a real implementation is bounded
by **latency and launch count**: the nsys run shows 166 kernels per iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from Q2's analysis, not re-measured
here) the GPU-side launch floor is ~0.33 ms (inferred; an implementation bound, reported separately).
