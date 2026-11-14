# TPC-H Q2 SF1 — physical floor (RTX 5070, all referenced columns pinned on GPU)

Computed from table statistics and the pinned footprint **before** reading any ncu profile.

Hardware: GDDR7 192-bit, **672 GB/s** DRAM peak; 48 SMs (sm_120), 4 SMSPs/SM; 48 MB L2.

## Inputs (measured)

| Table | Rows | Pinned columns | Pinned bytes (gpu_pool delta after each `pin_table`) |
|---|---:|---|---:|
| part | 200,000 | p_partkey, p_mfgr, p_size, p_type | 9,520,896 |
| supplier | 10,000 | s_suppkey, s_acctbal, s_name, s_address, s_phone, s_comment, s_nationkey | 1,437,440 |
| partsupp | 800,000 | ps_partkey, ps_suppkey, ps_supplycost | 8,000,000 |
| nation | 25 | n_nationkey, n_name, n_regionkey | 1,024 |
| region | 5 | r_regionkey, r_name | 768 |
| **Total** | | | **18,960,128 B (18.96 MB)** |

Source: `traces/sirius_log_timing/*.log`, `[gpu_pool] ... QueryEnd ... allocated=` after each of the five `pin_table` calls.
Sirius narrows carriers at pin time (`partsupp` = 10 B/row instead of 16 B native; `p_size` stored as int8, kernel names show
`signed char*`/`short*` carriers). Native widths (int32 keys, int64 decimals, string chars + int32 offsets) would be
24.45 MB: part 10.12 MB (p_type chars 4.12 MB, p_mfgr chars 2.80 MB, 2 × 0.8 MB offsets, 2 × 0.8 MB int32),
partsupp 12.80 MB, supplier 1.53 MB (1.21 MB of string chars), nation/region < 1 KB.

Selectivities (DuckDB on the same Parquet): `p_size = 41` keeps 4,022 of 200,000 parts (2.0%); `p_type LIKE '%NICKEL'` on top
of that keeps 834 (0.42%); EUROPE has 5 of 25 nations (1,987 of 10,000 suppliers); partsupp ⋈ EUROPE suppliers = 158,960 rows; restricted to the
qualifying parts = 662 rows; rows reaching ORDER BY/LIMIT = 485; result = 100 rows (16.5 KB as CSV).

## Floors

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Read every pinned column once (resident, narrowed) | 18.96 MB | **28.2 µs** |
| A'. Same at native widths | 24.45 MB | 36.4 µs |
| A-min. Only what the predicates force: p_size + p_type + p_partkey (5.92 MB), partsupp (8.0 MB), supplier (1.44 MB) | 15.4 MB | 22.9 µs |
| B. A + materialising join intermediates once (write + read) in a plan that does NOT push the part filter into the MIN subquery: the largest is partsupp ⋈ EUROPE suppliers (158,960 rows × 12 B); all others are < 5 K rows | ≈ 18.96 + 2 × 1.9 = 22.8 MB | 33.9 µs |

Intermediates are tiny because both selective predicates (part filter, EUROPE) can be applied before the large join:
with a semi-join filter on `ps_partkey ∈ {834 parts}` the MIN subquery touches 3,336 partsupp rows (662 of them in EUROPE). Q2 at SF1 is therefore a
**~20 MB, ~30 µs** problem for the memory system.

Compute: the heaviest per-row work is the `LIKE '%NICKEL'` suffix compare on 4.12 MB of `p_type` chars (or on only 4,022
strings after `p_size`), hashing 800 K partsupp keys (~20 integer ops each ≈ 16 M ops), and a top-100 over < 1 K rows.
Total < 0.1 G simple ops; at 48 SMs × 4 warp-inst/clk × 32 lanes × ~2.3 GHz (≈ 14 T lane-ops/s) that is **< 10 µs**.
Q2 is bandwidth-floor-bound at ~30 µs, but both floors are so small that a real implementation is bounded by
**latency and launch count**, not by bytes or FLOPs:

- A dependent chain of k kernels costs at least k × (launch + drain). Measured on this GPU, the smallest kernels in the
  warm iteration take ~1.7–2 µs of GPU time each (e.g. `DeviceScanInitKernel`), so any plan that needs ~100+ dependent
  kernels has a GPU-side floor of ~0.2–0.5 ms independent of data size. This is an implementation bound (inferred), not a
  physical one, and is reported separately in the report's gap analysis.

Measured values and the gap against these floors are in `REPORT_tpch_q2_sf1.md` (§4, §8).
