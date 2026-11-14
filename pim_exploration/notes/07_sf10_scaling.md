# SF1 to SF10 scaling

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## SF10 scaling: findings (all 8 queries ran on the GPU path, with fallback off)

Queries: Q1, Q3, Q6, Q9, Q10, Q13, Q16, Q18. **None failed.** Each SF10 run went through the copied pipeline (`sql timing pcie selftest`):
- PCIe/residency check `OVERALL: PASS` (pinned tier, one pinned entry per scan, fs_cache zero, pool counters, memcpy limits, UM).
- Negative control `SELFTEST: PASS` for all 8.
- The result equals DuckDB-CPU: 23 runs `exact`, 2 (Q1) `ordered-with-tolerance`, max relative difference 1.4e-16.

**Confound I found and controlled (measured, `settings_probe_*.txt`).** Sirius sets its batch size to GPU capacity / 40. The SF1 pipeline yaml (0.25 pool) gives **77 MB** batches. The 0.85 pool that SF10 needs gives **262 MB** batches. So each query ran in 4 configurations (rows of `scaling_table.csv`):

| Config | Scale | Batch | Notes |
|---|---|---|---|
| `sf10_main` | SF10 | 262 MB | 0.85 pool |
| `sf1_main` | SF1 | 262 MB | same yaml as `sf10_main` |
| `sf10_b77` | SF10 | 77 MB | batch settings forced to the SF1 pipeline's values |
| `sf1_pipe` | SF1 | 77 MB | existing SF1 results; Q1 re-run with the SF1 pipeline yaml |

The "fixed config" comparison below is `sf1_main` → `sf10_main`, so only the data size changes.

### 1. Main findings

1. **Launch count is almost entirely a per-batch cost: it grows with data ÷ batch size, not with the data alone (measured).**
   - Q1 launches about 67 kernels per batch at every point: 186/3 batches, 465/7, 873/13 and 3865/57. The batch count is the number of `single_pass_shmem_aggs_kernel` launches.
   - Q6 launches about 15 per batch: 15/1, 47/3, 108/7, 423/28.
   - At fixed config, SF1→SF10 launches grow ×1.12 (Q16) to ×7.2 (Q6). With 77 MB batches they grow ×1.34 to ×9.0.
   - Families whose launches stay flat are the once-per-query steps: final sort, build side of small joins, string gathers after the top-N. Examples: Q3/Q13/Q16 `DeviceMergeSortBlockSortKernel` 2→2, Q9 `insert_if_n` 7→7, Q10 `gather_chars_fn_string_parallel` 8→8.
   - Families that grow are the per-batch scan/filter/aggregate chains: Q1 `shmem_aggs` 3→13, Q6 `compute_column_kernel` 1→7, Q18 `transform_kernel` 51→104, Q3 `fused_membership_mask` 2→8.
   - Source: `scaling_summary.json` → `comparisons.fixed_config_main.families`.
   - On a larger GPU, Sirius would choose larger batches (≈2 GB on 80 GB), so the count depends on configuration as much as on data.

2. **Extra launches are cheap in wall time (inferred).** Same SF10 data with 3.4× smaller batches (`sf10_b77` − `sf10_main`, `scaling_summary.json` → `sf10_batch_size_effect`):
   - Q1: +2,992 launches cost +8.5 ms wall (2.8 µs per launch) and +1.3 ms GPU busy.
   - Q6: +315 launches, +2 ms.
   - Q9 (+494), Q13 (+48) and Q10 (+230): 0 to −0.5 ms.
   - Q3, Q16 and Q18 got faster with more launches (−2 to −3 ms; the timer has 1 ms resolution).
   - So most of the launch overhead overlaps GPU work across the 4 pipeline threads. Launch count alone does not set the idle time.

3. **Hypothesis 2 (GPU idle most of the wall time) is mostly a small-data effect (measured, `scaling_table.csv`).**
   - GPU-busy share of warm wall time at fixed config, SF1→SF10:
     - Q1 47→80%, Q6 23→56%, Q9 17→56%, Q10 22→50%, Q13 15→51%, Q16 44→52%, Q18 23→65%.
     - Q3 is the exception at 25→29%.
   - Wall time grows only ×1.9–5.3 for 10× data, while GPU busy grows ×2.3–14.7.
   - Idle time (wall − busy) grows ×1.15–2.9: Q1 4.0→6.9 ms, Q3 3.8→11.0, Q9 7.4→13.7, Q18 6.1→14.7 ms. It is not constant: planning alone goes from 1–3 to 2–8 ms (Q3 2→7.5, Q18 2.5→8, from the Sirius log). I do not know why planning grows.
   - Wall time per table row falls 2–5×, e.g. Q13 1.82→0.36 ns/row and Q9 1.06→0.36 ns/row.

4. **GPU kernel time scales faster than the data in several queries: an L2/cache effect, which is another way SF1 misleads (measured).**
   - Q18 busy grows ×14.7 for 10× data and Q9 ×11.1.
   - Q9 hash-join build `insert_if_n` (the `rhs_index_type` build, 7.22 of 7.25 ms): same 7 launches, time ×65 (111→7,263 µs).
   - ncu (cold-L2) L2 hit rate for that family falls from 77% to 52%, and long_scoreboard stalls rise to 96%.
   - At SF1 the build table fits in the 48 MB L2; at SF10 it does not.
   - Busy time against the pinned-bytes floor (pinned bytes ÷ 672 GB/s) is 2.2–25× at SF10 (Q16 74×), versus 3.3–17× at SF1 (Q16 366×).

5. **Memory-boundedness at SF10 is mixed (ncu `--set full`, cold-L2, clock-locked; `q{6,3,9,18}/ncu_families_summary.txt`).** Values are % of 672 GB/s, SF1 → SF10.
   - **Bandwidth-bound at SF10:** the sort-based group-by and gather pieces.
     - Q18 `transform_kernel` (unique_copy / gather / cast): 59→78%, ~0.11 instructions per byte.
     - Q18 `_kernel_agent` (thrust reduce_by_key): 82→81%.
     - Q18 `static_kernel`: 50→64%.
     - Q9 `transform_kernel`: 47→70%.
   - **Latency- or issue-bound, and not because the data are small:**
     - Q6 `compute_column_kernel` (AST interpreter; 90% of Q6's kernel time): 11→13% with 155 waves, 2.6 instructions per byte, long_scoreboard 38%, wait 25%.
     - Q9 hash build `insert_if_n`: 31→21%, long_scoreboard 96%. Random probes of a hash table larger than L2.
     - Q3 `fused_membership_mask`: 20→28%, L2 hit 58%, long_scoreboard 54%.
     - Q6 `DeviceSelectSweepKernel`: 20→25%, barrier stalls 30%.
     - From the earlier Q1 SF10 study: `single_pass_shmem_aggs_kernel` runs at 11–22%.
   - **Still too small to tell:** `DeviceMergeSortBlockSortKernel` in Q3 runs 0.08–0.14 waves (2 launches, 0.5% of peak) and in Q16 runs on grids of 28 and 5 CTAs. It stays a near-serial sort of a result-sized input.

6. **Modeled extrapolation (`extrapolation_modeled` in `scaling_summary.json`).** Two-point linear fits at fixed config; the pool high-water is scaled linearly with SF.
   - The largest scale that fits 12 GB is about SF29–46 for the lineitem queries.
   - At that point the GPU-busy share is about 31% (Q3) to 86% (Q1); 65–73% for Q6, Q9, Q13 and Q18.
   - On an 80 GB HBM-class GPU with about 5× the bandwidth, at SF100, assuming busy time shrinks 5× and host time stays: busy share falls back to 8% (Q3), 22–36% (Q6, Q9, Q10, Q16, Q18), 46% (Q13) and 59% (Q1).
   - So the idle share reappears whenever the GPU side gets faster. This is a modeled upper bound, from 2 points only, and it ignores that Sirius picks about 8× larger batches on an 80 GB GPU.

### 2. Supporting tables (`scaling_table.csv`; fixed config = `sf1_main` → `sf10_main`)

| Q | wall ms SF1→SF10 | busy ms SF1→SF10 | busy % of wall | launches | idle ms | pool high-water SF10 (MB) | DuckDB-CPU SF10 ms |
|---|---|---|---|---|---|---|---|
| 1 | 7.5→34 | 3.54→27.1 | 47→80 | 186→873 | 4.0→6.9 | 3,566 | 84 |
| 3 | 5→15.5 (12–22) | 1.24→4.53 | 25→29 | 85→138 | 3.8→11.0 | 2,675 | 134 |
| 6 | 3→12 | 0.69→6.76 | 23→56 | 15→108 | 2.3→5.2 | 2,348 | 40 |
| 9 | 9→31 | 1.56→17.3 | 17→56 | 124→212 | 7.4→13.7 | 3,674 | 274 |
| 10 | 9→26 | 1.98→13.1 | 22→50 | 229→300 | 7.0→12.9 | 3,384 | 246 |
| 13 | 3→6 | 0.44→3.06 | 15→51 | 30→48 | 2.6→2.9 | 2,734 | 326 |
| 16 | 17→33 | 7.52→17.1 | 44→52 | 156→175 | 9.5→16.0 | 404 | 81.5 |
| 18 | 8→42 | 1.86→27.3 | 23→65 | 127→291 | 6.1→14.7 | 2,811 | 209 |

- The pool high-water is the process-lifetime peak and includes the pin phase.
- Against the existing SF1 results (`sf1_pipe` → `sf10_main`), launch ratios are ×1.12–2.30 and busy-share changes are similar (`asked_sf10main_vs_sf1pipeline`).
- At SF10, launches under 5 µs are still 39–68% of all launches (e.g. Q1 511 of 873).

Top kernel families by real-clock time at SF10 (nsys, one warm iteration; launches SF1→SF10, time ratio):

| Query | Family | Launches | Time |
|---|---|---|---|
| Q1 | `shmem_aggs` | 3→13 | ×13.6 |
| Q1 | `transform_kernel` | 65→295 | ×13.3 |
| Q6 | `compute_column_kernel` | 1→7 | ×10.0 |
| Q9 | `insert_if_n` | 7→7 | ×65 |
| Q9 | `transform_kernel` | 50→101 | ×16 |
| Q3 | `fused_membership_mask` | 2→8 | ×9.1 |
| Q3 | merge-sort block sort | 2→2 | ×1.0 |
| Q13 | `like_multiliteral` | 1→4 | ×8.8 |
| Q16 | block sort | 2→2 | ×1.4 |
| Q16 | merge | 8→12 | ×3.4 |
| Q18 | `transform_kernel` | 51→104 | ×19 |
| Q18 | `static_kernel` | 14→34 | ×21 |

### 3. What I could not determine
- **Q16 and Q1 ncu at SF10 were not run.** I stopped on your instruction before Q16's run began; Q1 relies on the earlier SF10 study. Q10 and Q13 were never in the ncu set.
- **Some families were only partly covered by ncu:** first 40 of 104 Q18 `transform_kernel` launches (82% of its nsys time) and first 40 of 101 Q9 `transform_kernel` launches (35%). The others are complete, and every profiled (name, grid) multiset matches the nsys warm iteration.
- **ncu bandwidth figures** are serialized, clock-locked and cold-L2. Real-clock bandwidth of the same families is not measured.
- **Why planning time grows ×2–4 with SF** — no CPU sampling was taken (it breaks `pin_table`).
- **Wall times have 1 ms resolution**, so the per-launch costs in finding 2 are ±1 ms over the whole run. Q3's wall time is noisy (12–22 ms).
- **The 12 GB and 80 GB numbers are two-point models,** not measurements.

### 4. What I would measure next
- One SF20 or SF30 run per query, to test the linear fits.
- An SF10 run with batch settings of about 1–2 GB, to imitate an 80 GB GPU's batching.
- nsys `cudaLaunchKernel` / sync CPU time per thread at SF10, to split idle time into planning, launch, sync and result handling.
- The hash-build working-set size against L2 (48 MB) for Q9 as SF goes from 1 to 10.

### 5. Files written (all under `pim_exploration/sf10_scaling/`)
- **Scripts in `scripts/`:**
  - Pipeline copies: `profile_query.sh` (SF, CFG and output dir, flock), `run_sirius.sh` (`SIRIUS_YAML`), `gen_sql.py` and `pcie_verify.py` (SF10 default), plus `sirius.yaml` (0.85 pool) and `sirius_b77.yaml`.
  - New: `probe_settings.sh`, `run_all.sh`, `scaling_extract.py`, `scaling_compare.py`, `run_extract.sh`, `ncu_plan_families.py`, `ncu_families.sh`, `ncu_extract_families.py`, `run_ncu_all.sh`. The other pipeline files are unmodified copies.
- **Outputs:**
  - `scaling_summary.json`, `scaling_table.csv` and `compare_out.txt` (printed tables).
  - `settings_probe_{sf10yaml,b77yaml,sf1pipeline_yaml}.txt`, `run_all.log`, `ncu_all.log`, `extract_run.log`.
  - Per-query directories `q<N>/` (SF10 main), each with `timing.json`, `pcie_verification.txt`, `nsys_iteration_breakdown.*`, `selftest_negative_control.txt`, `scaling_metrics.json`, `sf1_pipeline_metrics.json`, `traces/` and `sql/`.
  - Subdirectories `q<N>/sf1_main/` and `q<N>/sf10_b77/`, plus `q1/sf1_sf1pipe/`.
  - ncu results in `q{3,6,9,18}/ncu_families_{plan.json,metrics.json,summary.txt}` and `profiles/`.
- **Large binaries:** `*.ncu-rep` + `*.nsys-rep` total 592.6 MB. The nsys `*.sqlite` exports add 155 MB and are not covered by the git-ignore patterns. The directory is 840 MB in total.
