# TPC-H Q5 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Native bytes/row (DuckDB types) | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|---:|
| lineitem | 6,001,215 | l_orderkey, l_suppkey, l_extendedprice, l_discount | 24 (4+4+8+8; DECIMAL(15,2) as int64) | 84,017,920 (14.0 B/row) |
| orders | 1,500,000 | o_custkey, o_orderkey, o_orderdate | 12 | 15,000,320 (10.0 B/row) |
| customer | 150,000 | c_custkey, c_nationkey | 8 | 750,080 (5.0 B/row) |
| supplier | 10,000 | s_suppkey, s_nationkey | 8 | 30,464 |
| nation | 25 | n_nationkey, n_name, n_regionkey | 8 + 177 name chars + offsets | 1,024 |
| region | 5 | r_regionkey, r_name | 4 + 34 name chars + offsets | 768 |
| **Total** | | | | **99,800,576 B (99.80 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each `pin_table` (pin order orders, lineitem,
supplier, nation, region, customer: 15,000,320 / 99,018,240 / 99,048,704 / 99,049,728 / 99,050,496 / 99,800,576). Column types from
DuckDB `describe` on the Parquet. Sirius narrows carriers at pin time (lineitem 14 B/row vs 24 native), so the pinned total is below native.
Native-width total: 144.03 + 18.00 + 1.20 + 0.08 + <0.001 = **163.3 MB**. Every column of every table is read by the query
(there are no pinned-but-unused columns).

Selectivities / cardinalities (DuckDB-CPU on the same Parquet):
- `o_orderdate` in 1997: 227,783 of 1,500,000 orders (15.2%).
- EUROPE: 5 of 25 nations; 1,987 of 10,000 suppliers (19.9%); 30,197 of 150,000 customers (20.1%).
- 1997 orders of EUROPE customers: 45,677.
- lineitem rows with an EUROPE supplier: 1,191,757 (19.9%); with a 1997 order: 910,019 (15.2%); both: 180,756 (3.0%).
- Final join (incl. the `c_nationkey = s_nationkey` condition): **7,246 rows** -> 5 groups (result CSV 130 B).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 99.80 MB | **148.5 µs** |
| A'. Same at native widths | 163.3 MB | 243 µs |
| A-min. Late materialisation at native widths: read the two lineitem key columns (48.0 MB) for all rows, gather price/discount only for the 180,756 qualifying rows (2.9 MB), orders 18.0 MB, customer 1.2 MB, supplier 0.08 MB | 70.2 MB | 104.5 µs |
| B. A + materialising the largest join intermediate once (write + read). Assumes the lineitem x EUROPE-supplier stream, 1,191,757 rows x ~16 B (orderkey, price, discount, suppkey narrowed) = 19.1 MB, is written and re-read; all other intermediates are < 5 MB | 99.80 + 2 x 19.1 = 138 MB | 205 µs |

Q5 at SF1 is therefore a **~100-165 MB, ~150-240 µs** problem for the memory system; lineitem is 84% of the pinned bytes. The plan
is dominated by one streaming pass over lineitem (probe against a small hash table / dynamic filter built from <= 46 K orders and 2 K suppliers).

Compute: per lineitem row, one hash + probe on the order key (~20-30 integer ops), one supplier-key probe, and for the 3% survivors
the revenue multiply (`price * (100 - discount)`) and a 5-group aggregate. Order: 6.0 M x ~50 ops = 0.3 G ops, plus hash builds of
228 K / 30 K / 2 K keys (< 0.02 G). At 48 SMs x 4 warp-inst/clk x 32 lanes x ~2.3 GHz (~14 T lane-ops/s) that is **~20-25 µs**, below
the memory floor, so Q5 is bandwidth-floor-bound at ~150 µs (*inferred* — probes are random 4-8 B reads into tables that fit the 48 MB L2).

Latency/launch bound (*inferred*): the plan has 36 pipelines (`query_plan.txt`) with partition/concat between every join. A dependent chain of
k kernels costs at least k x (launch + drain); the smallest kernels take ~2 µs of GPU time, so ~130 dependent kernels give a GPU-side floor of
~0.25-0.5 ms regardless of data size — larger than the byte floor above. Reported separately in the gap analysis of the report.
