# TPC-H Q13 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q13.sql`): customer LEFT OUTER JOIN orders ON c_custkey = o_custkey AND
o_comment NOT LIKE '%special%requests%'; count(o_orderkey) per customer; then group by that count (c_count) with count(*) (custdist);
ORDER BY custdist DESC, c_count DESC.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| customer | 150,000 | c_custkey | 600,064 |
| orders | 1,500,000 | o_custkey, o_orderkey, o_comment | 90,771,456 |
| **Total** | | | **91,371,520 B (91.37 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 600,064 after the customer pin, 91,371,520 after the orders pin
(delta 90,771,456). Pinned per row: customer 4.00 B, orders 60.51 B; o_comment alone is 48.51 chars/row mean (DuckDB-CPU, 72,770,808 chars total,
min 19, max 78). Native widths (inferred: INTEGER keys 4 B — DuckDB typeof — plus string bytes plus an assumed 4 B offset per string):
orders 4 + 4 + 48.51 + 4 = 60.51 B/row = 90.77 MB; customer 600,000 B; native total (inferred) ≈ 91.37 MB, i.e. equal to the pinned footprint
(strings are not narrowed). **o_comment (chars + offsets, 78.77 MB) is 86.2% of the pinned bytes.**

## Selectivities and intermediate cardinalities (DuckDB-CPU on the same Parquet)

- orders rows matching '%special%requests%': 16,082 (1.07%); rows surviving NOT LIKE: 1,483,918 (98.93%); rows matching '%special%' alone: 138,881 (9.26%).
- Distinct o_custkey over all orders 99,996; over the surviving rows 99,995.
- Join output: 1,483,918 matched rows + 50,005 customers with no surviving order (c_count = 0) -> 150,000 per-customer groups (all customers).
- Inner group-by result: 150,000 rows; outer group-by: 42 distinct c_count values (max 41); sum(c_count) = 1,483,918. Result 42 rows (c_count = 0: 50,005 customers).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident) | 91.37 MB | **136.0 µs** |
| A'. Same at native widths (inferred) | 91.37 MB | 136.0 µs |
| A-min. Only what the query forces (inferred): o_comment 78.77 MB (all rows, the predicate), o_custkey 6.0 MB, c_custkey 0.6 MB (o_orderkey not needed: non-null) | 85.37 MB | 127.0 µs |
| B. A + materialising the surviving o_custkey (1,483,918 × 4 B written + read, 11.87 MB) and the 150,000-row per-customer table (8 B/row, written + read, 2.40 MB) (inferred) | ≈ 105.64 MB | ≈ 157.2 µs |

Q13 is a **~91 MB, ~136 µs** problem for the memory system: string bytes dominate; 98.9% of orders survive the predicate, so there is no selectivity to exploit.

Compute: the two-literal LIKE touches 72.8 M characters; at ~1–2 byte-compares per character per literal that is ≈ 0.15 G byte-ops;
join/count over 1.48 M rows, a 150 K-row group-by and a 42-row sort add ≈ 0.01 G more. At ~14 T lane-ops/s that is **< 20 µs** if perfectly
parallel; string scans are not perfectly parallel (variable-length rows), so this is a lower bound (inferred).
Launch-count bound: the nsys run shows 36 kernels per iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel (imported from Q2's
analysis, not re-measured here) the launch floor is ~0.07 ms (inferred; an implementation bound, reported separately).
