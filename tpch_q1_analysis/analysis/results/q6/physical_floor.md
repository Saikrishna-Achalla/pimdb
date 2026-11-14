# TPC-H Q6 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after `pin_table`) |
|---|---:|---|---:|
| lineitem | 6,001,215 | l_extendedprice, l_discount, l_shipdate, l_quantity | 84,018,176 (14.0 B/row) |
| **Total** | | | **84,018,176 B (84.02 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after the single `pin_table` call (0 -> 84,018,176 B;
`pcie_verification.txt` "GPU memory" line gives the same footprint). Parquet types (DuckDB `describe`): three DECIMAL(15,2) columns + DATE.
Native widths (int64 decimals, int32 date) = 3 x 8 + 4 = 28 B/row = 168.03 MB; Sirius narrows carriers at pin time to 14.0 B/row
(the split across columns is not read from a file here; inferred from the total).

Selectivities (DuckDB-CPU on the same Parquet, 6,001,215 rows): shipdate in 1997 = 911,395 (15.2%); discount in [0.02,0.04] = 1,637,011 (27.3%);
quantity < 24 = 2,758,822 (46.0%); date AND discount = 248,415 (4.1%); all four = **114,271 rows (1.90%)**; result = 1 row (22 B CSV).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 84.02 MB | **125.0 us** |
| A'. Same at native widths | 168.03 MB | 250.0 us |
| A-min. Only l_shipdate (first predicate; 15.2% selectivity but rows are not clustered so every sector is touched) | ~24 MB if 4 B | ~35.7 us (not attainable: the other 3 columns are needed for the 114,271 survivors, scattered across the table) |
| B. A + a 1 B/row selection mask written and re-read (2 x 6.0 MB) | 96.0 MB | 142.9 us |

Output materialisation is negligible: 114,271 survivors x 16 B = 1.8 MB if gathered, one scalar result.
Q6 at SF1 is a **~84 MB, ~125 us** problem for the memory system (A is the realistic floor: a streaming filter+reduce).

Compute: per row ~2 date compares, 2 discount compares, 1 quantity compare, one multiply, one add into a reduction = ~10 integer ops,
6.0 M rows -> ~60 M lane-ops; at 48 SMs x 4 warp-inst/clk x 32 lanes x ~2.3 GHz (~14 T lane-ops/s) that is **< 5 us**.
The query is bandwidth-bound by a wide margin (compute ~ 4% of the byte floor).

Launch-count bound (inferred): the plan has one GPU_SCAN -> PROJECTION -> UNGROUPED_AGGREGATE pipeline, a MERGE_AGGREGATE and a RESULT_COLLECTOR.
A well-formed implementation needs very few kernels; each dependent kernel costs >= ~2 us of GPU time (smallest kernels seen in Q2), so the
launch floor is tens of us, below the 125 us byte floor. Whatever kernel count is measured above that is overhead, reported in the gap analysis.

Measured values and the gap against these floors are in `REPORT_tpch_q6_sf1.md` (§5, §10).
