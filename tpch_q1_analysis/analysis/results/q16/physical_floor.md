# TPC-H Q16 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

Query (read from `sirius/test/tpch_performance/tpch_queries/orig/q16.sql`): partsupp ⋈ part on partkey; p_brand <> 'Brand#21'; p_type NOT LIKE 'MEDIUM PLATED%';
p_size IN (38,2,8,31,44,5,14,24); ps_suppkey NOT IN (supplier with s_comment LIKE '%Customer%Complaints%'); group by (p_brand, p_type, p_size) with
count(distinct ps_suppkey); ORDER BY supplier_cnt desc, p_brand, p_type, p_size.
The plan (`query_plan.txt`) has 3 GPU_SCANs (ids 0, 3, 7), 2 hash joins (id 11, id 15 of type MARK), 1 dynamic filter (id 8), 1 hash group-by (id 19), 1 merge-group-by (id 21), order-by (id 22).

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| partsupp | 800,000 | ps_partkey, ps_suppkey | 4,800,000 |
| part | 200,000 | p_partkey, p_brand, p_type, p_size | 8,320,768 |
| supplier | 10,000 | s_suppkey, s_comment | 686,336 |
| **Total** | | | **13,807,104 B (13.81 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` 4,800,000 after the partsupp pin, 13,120,768 after part, 13,807,104 after supplier
(pin order partsupp, part, supplier). Pinned per row: partsupp 6.00 B, part 41.60 B, supplier 68.63 B. Native widths (inferred from Parquet types, DuckDB-CPU: INTEGER keys/size 4 B,
VARCHAR means p_brand 8.0, p_type 20.60, s_comment 62.57 chars, plus an assumed 4 B offset per string): partsupp 8 B/row = 6.40 MB; part 4+12+24.60+4 = 44.60 B/row = 8.92 MB;
supplier 4+66.57 = 70.57 B/row = 0.71 MB; native total (inferred) ≈ 16.03 MB.

## Selectivities and cardinalities (DuckDB-CPU on the same Parquet)

- part 200,000: p_brand <> 'Brand#21' 192,009; p_type NOT LIKE 'MEDIUM PLATED%' 193,311; p_size IN (...) 32,099; all three: **29,770 parts (14.9%)**.
- supplier 10,000: s_comment LIKE '%Customer%Complaints%' = **4 suppliers**.
- partsupp rows joining a qualifying part: **119,080** (14.9% of 800,000); after removing the 4 complaint suppliers: **119,033** (47 rows removed).
- Groups: **18,368** (25 distinct brands, 150 distinct types in part), supplier_cnt takes 15 distinct values (min 3, max 32). Result CSV 650,813 B (`result.csv`).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 13.81 MB | **20.5 µs** |
| A'. Same at native widths (inferred) | 16.03 MB | 23.8 µs |
| A-min. Only what the predicates force (inferred native widths): all part columns 8.92 MB (type LIKE on every row); ps_partkey 800,000 × 4 = 3.20 MB; ps_suppkey of the 119,080 joined rows 0.48 MB; supplier 0.71 MB | ≈ 13.30 MB | 19.8 µs |
| B. A + materialising the 119,033 joined rows (brand, type, size, suppkey ≈ 48.6 B/row = 5.79 MB) once written + once read (inferred) | ≈ 25.4 MB | ≈ 37.8 µs |

Q16 is a **~14 MB, ~20 µs** problem for the memory system (narrowed, read once); a ~38 µs floor with one materialisation. Part (60%) and partsupp (35%) hold the pinned bytes.
The result (18,368 rows, 650,813 B CSV) must also cross to the host once; at PCIe rates that transfer is outside this device-memory floor.

Compute: two substring scans (LIKE '%Customer%Complaints%' over 10,000 × 62.6 chars ≈ 0.63 MB of text; NOT LIKE prefix over 200,000 types), a join probe of 800,000 / 119,080 rows,
a MARK anti-join of 119,080 rows against 4 build keys, a count-distinct (dedupe of 119,033 (group, suppkey) pairs by sort or hash), and a sort of 18,368 rows by four keys.
≈ 0.05–0.1 G simple ops; at ~14 T lane-ops/s that is **< 10 µs** (inferred, rough).
A real implementation is bounded by **latency and launch count**: the nsys run shows 156 kernels per iteration (`pcie_verification.txt`); at ~2 µs per smallest kernel
(imported from earlier queries' analyses, not re-measured here) the GPU-side launch floor is ~0.31 ms (inferred; an implementation bound, reported separately).
