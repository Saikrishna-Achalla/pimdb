# TPC-H Q1 SF10 — physical floor (RTX 5070, lineitem pinned on GPU)

Hardware peaks: GDDR7 192-bit @ 28 Gbps = 672 GB/s DRAM; 48 SMs (sm_120).

Setup: `CALL pin_table(<lineitem parquet>, tier='gpu', name='lineitem', cols=[7 Q1 columns])`.
The pin decodes the 1.67 GB Parquet file once (177 ms, one-off) and keeps the 7 columns resident in GPU memory.
Sirius's default `enable_compressed_materialization: true` stores eligible integer/DECIMAL columns in
narrower carriers, so the resident footprint is **1,679.6 MB** (GPU pool `allocated=1679621120` between
queries; 1,783 MB peak while pinning) instead of ~2,759 MB at native widths (46 B/row).

Input per query: 59,986,052 rows; the filter keeps 31,569,869 (52.6%); output is 4 groups.
No bytes cross PCIe and no Parquet is decoded per query: the Sirius log reports
`fs_cache … last_cycle[reads=0 hits=0 h2d=0]` for all 14 timed queries.

| Scenario | Bytes | Floor @ 672 GB/s |
|---|---:|---:|
| A. Fused filter + aggregate over the resident (narrowed) columns, read once | 1,680 MB | **2.50 ms** |
| A'. Same, at native widths (no narrowing) | 2,759 MB | 4.11 ms |
| B. Materialised: read columns, write the filtered copy (52.6% of 2,759 MB), read it once for the group-by | 1,680 + 1,452 + 1,452 = 4,584 MB | 6.82 ms |

Compute: ~31.6M qualifying rows × ~12 integer ops ≈ 0.38 G int-ops → < 0.05 ms. Q1 is bandwidth-bound.

Measured values and the gap against these floors are in `REPORT_tpch_q1_sf10.md` §8.5.
