# RUNBOOK — profiling one TPC-H query (SF1) on Sirius with GPU-resident data

This directory holds a query-generic pipeline. One command produces a complete, validated
`analysis/results/q<N>/` for TPC-H query N; you then write two documents by hand
(`physical_floor.md`, `REPORT_tpch_q<N>_sf1.md`) using Q2 as the template.

Paths used below:
```
P=/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1        # this directory
R=/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q<N>   # per-query output
```

## 0. Before you start (every query)

1. Only one GPU process at a time. Check: `nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader`
   must print nothing (the pipeline also refuses to run otherwise). Never start a second pipeline in parallel.
2. `sudo -n /usr/local/cuda/bin/ncu --version` must work without a password (NOPASSWD is set for ncu only;
   do not use sudo for anything else).
3. Do not modify or rebuild Sirius/cuDF, do not git-commit, do not use LD_PRELOAD.
4. Do not edit the pipeline scripts while a pipeline is running (bash reads scripts lazily; an edit
   mid-run caused `syntax error near unexpected token` once).

## 1. Run it

```bash
N=3; R=/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q$N
mkdir -p $R && /home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1/profile_query.sh $N > $R/pipeline_run.log 2>&1
```
Run it in the background (it takes minutes; it is a single process tree, never start a second one) and wait for it to
exit. Then read `$R/pipeline_run.log`.

Exit status 0 = every stage passed and `validate_query.py` printed no FAIL. Non-zero = read the last
`ERROR q<N>: ...` line of the log.

**Expected wall time**: about `1 min + 1.5 s × (kernels given --set full)`. That is all warm-iteration launches
when there are ≤ `NCU_FULL_MAX` (1000) of them, otherwise the launches of the families covering 90% of warm GPU time
(the light pass over all kernels is a single ncu pass and nearly free). Q2 (229 warm kernels, full on all):
**6.4 min** total — sql 0 s, timing 1 s, pcie 6 s, list 29 s, detail 335 s, extract 10 s
(`analysis/results/q2/pipeline_run.log`). The 1000 threshold keeps the worst full_all case near 26 min.

Stages (each writes its outputs, then `$R/.done_<stage>` with its duration in seconds):

| Stage | What it does | Main outputs in `$R` |
|---|---|---|
| `sql` | `gen_sql.py`: views over exactly the pin-glob files, `pin_table(tier='gpu')` for every referenced table (from Sirius's `tpch_pin_columns.py`), `.mode csv`, `.timer on`, query × iterations | `sql/q<N>_{timing,cpu,ncu_x3,ncu_x4,ncu_x5,nsys}.sql` |
| `timing` | pinned Sirius run: 3 warmup + 12 timed iterations; DuckDB-CPU run of the same 15 iterations; parse | `timing.json`, `timing_summary.txt`, `result.csv`, `query_plan.txt`, `traces/timing_run.txt`, `traces/duckdb_cpu_run.txt`, `traces/sirius_log_timing/` |
| `pcie` | nsys 2025.5 CUDA trace (+ unified-memory page-fault collection) of pin + 3 warmup + 5 measured iterations (0.3 s `.shell sleep` gaps); `pcie_verify.py` (SQL tier, Sirius-log residency checks on the timing AND nsys runs, memcpy by memory kind, UM, decode kernels); `nsys_breakdown.py` | `pcie_verification.txt`, `pcie.json`, `nsys_iteration_breakdown.{txt,json}`, `traces/q<N>_nsys.{nsys-rep,sqlite}`, `traces/sirius_log_{timing,nsys}/` |
| `selftest` | negative control: the same nsys run with the largest referenced table NOT pinned; `pcie_verify.py` must fail (~15 s) | `selftest_negative_control.txt`, `selftest/` |
| `list` | three cheap ncu passes (pin+3/4/5 iterations, 4 metrics, `--log-file` CSV), each with its own Sirius log dir → residency log checks (`check_ncu_logs.py`), launch counts, stability check, warm (5th) iteration kernel list, profiling plan | `warm_kernel_list.json`, `warm_kernel_summary.txt`, `ncu_plan.json`, `ncu_log_checks_list.{txt,json}`, `traces/ncu_list_x{3,4,5}.csv`, `traces/sirius_log_ncu_list_x{3,4,5}/` |
| `detail` | refuses unless `ncu_plan.json` says stable; ncu on the warm iteration only (`-s skip -c count`): policy `full_all` = `--set full --import-source yes` on all warm kernels; policy `light_plus_families` = 1-pass light metrics (incl. SM sysmem-aperture counters) on all + `--set full` on the families covering ≥ 90% of time; then `check_slice.py`, `check_ncu_logs.py detail`, `check_sysmem.py` | `profiles/q<N>_warm_full.ncu-rep` or `profiles/q<N>_warm_{light,families_full}.ncu-rep`, `ncu_slice_check.{txt,json}`, `ncu_log_checks_detail.{txt,json}`, `ncu_sysmem_check.{txt,json}`, `traces/sirius_log_ncu_detail_*/` |
| `extract` | `extract_ncu.py`, `breakdown.py`, `sass_top.py` (SASS hotspots for the top 2 families' longest launches), `make_plots.py` | `ncu_warm_metrics.json`, `ncu_extract_summary.txt`, `phase_breakdown.{txt,json}`, `operator_breakdown.txt`, `top_kernel_details.txt`, `sass/*`, `plots/q<N>_{phase_breakdown,kernel_sequence,roofline,stalls}.png` |
| `validate` | `validate_query.py <N> --pipeline` | `validate_pipeline.txt` |

Rerunning: completed stages are skipped (`.done_<stage>` exists). `REDO=1 $P/profile_query.sh <N>` reruns all;
`REDO=1 $P/profile_query.sh <N> extract validate` reruns only those stages (later stages read earlier outputs).
Running any stage deletes the `.done_*` markers of all LATER stages, and the validator fails
(`outputs_newer_than_inputs`) if an output is older than its input, so a partial rerun cannot leave stale results.
CPU-only negative tests of the checks: `python3 -I $P/selftest_checks.py $R <scratch_dir>` (edits copies of real logs,
SQL, sqlite and ncu exports and asserts that each check fails for the intended reason).
ncu writes root-owned files; the pipeline deletes and rewrites them (`-f`), which works because the
directories are owned by you.

## 2. If the query cannot run on the GPU

The `timing` stage writes `$R/ERROR.txt` (error lines + tail of the run) and exits non-zero when the
Sirius run fails (`enable_duckdb_fallback=false`, so unsupported operators/OOM raise an error instead of
silently running on the CPU). **Stop for that query**: do not work around it, do not change the query, the pin
map, or Sirius. Report the exact error from `ERROR.txt`.

If `pcie` fails (`pcie_verification.txt` ends with `OVERALL: FAIL`, `ERROR.txt` written), residency is not proven.
Read which check failed:
- `*:pinned_entry_per_gpu_scan` / `*:fs_cache_zero_every_iteration` / `no_parquet_decode_kernels` → a referenced table or
  column is not served from the pin (a missing pin-map column is a SILENT cache miss in Sirius; pin map in
  `tpch_pin_columns.py` incomplete, or view/glob mismatch). Report it; do not edit Sirius files.
- `*:pin_tier_gpu` / `sql:pin_tier_gpu` → a pin is not `tier='gpu'` (e.g. `SIRIUS_PIN_TIER` leaked in; gen_sql forces gpu).
- `*:no_downgrade_or_spill`, `*:pool_counters_stable`, large `h2d/d2h`, `*:no_host_staged_filter_publication` → memory
  pressure or host-staged transfers; see knobs (§5).
- `unified_memory` → the trace lacks UM fault collection, or managed memory was used.
If only the determinism check fails (exit 3, "determinism, not PCIe"), kernel counts differ between nsys iterations.
If `list` fails with "not deterministic", the warm-iteration slice cannot be profiled; report it (ERROR.txt).
If `detail` fails in `check_sysmem.py`, a kernel read/wrote mapped host memory in place (no memcpy) — report it.

## 3. Reading validate_query.py output

`python3 -I $P/validate_query.py <N>` (without `--pipeline` after the report is written) prints one line per check:
`PASS|FAIL|PENDING <check> -- <detail>` and a final `SUMMARY q<N>: a PASS, b FAIL, c PENDING`.
- `PENDING` only appears with `--pipeline`, for the hand-written files (`physical_floor.md`, report).
- The final deliverable needs **0 FAIL and 0 PENDING** from `python3 -I $P/validate_query.py <N>`.

Checks, grouped: SQL files pin every table with `tier='gpu'`; no `ERROR.txt`; timing (≥3 warmup, ≥10 timed, positive);
result consistent across iterations and equal to DuckDB-CPU (numeric rel. tolerance 1e-9; ordered, else as a multiset
for ORDER BY ties — `timing.json` records the mode and max relative difference); every PCIe/residency sub-check;
PCIE_* byte limits equal their defaults (or the report names the override); negative-control self-test PASS; nsys
breakdown sane; launch counts stable; ncu kernels per iteration = nsys; residency log checks of every ncu run (list +
detail); zero SM sysmem-aperture sectors in every profiled kernel; ncu report multiset = expected slice; metrics kernel
count = warm count; percentages in range (raw hit rates ≤ 150%; ncu reads up to 114% on tiny kernels); kernels carrying `--set full` data = kernels in the
full/families report and cover ≥ 90% of warm time; outputs newer than inputs; SASS files; 4 plots; report sections.

What the slice check can and cannot catch: it catches wrong counts and windows that reach into the pin phase or
past the run. A shift *inside* the steady state is harmless and undetectable by design: every window of
`count` consecutive steady-state launches contains exactly one iteration's multiset of kernels.

## 4. Known pitfalls (all hit while building this on Q2)

| Pitfall | Symptom | What the pipeline does |
|---|---|---|
| `/usr/local/cuda/bin/nsys` is 2025.1.3 and cannot decode CUDA 13 runtime traces | "Unknown runtime API function index", ~2 kernels recorded | uses `/home/sai/nsight-systems-2025.5/.../nsys` (2025.5.2) |
| nsys CPU sampling breaks `pin_table` | `io_request.hpp:274: Operation canceled` | `-s none --cpuctxsw=none --backtrace=none` |
| ncu replay saves/restores all device-accessible memory per profiled kernel | 6.8 s/kernel with the Q1 yaml (0.85 GPU pool, 8 GB registered host pools) | `sirius.yaml` here: 0.25 GPU, 1 GB / 2 host pools → 1.35 s/kernel; light set is 1 pass (no replay) |
| ncu `--csv` to stdout mixes with the query's CSV output | corrupt kernel list | `--log-file` |
| `-k regex:` reports print simplified names (`NullType` vs `cub::NullType`) | name multiset mismatch | family report checked/merged on (function base, grid, block) |
| ncu renders one kernel's demangled name differently live (`--csv`) and from a saved report (Q3: `__uninitialized_fill::functor<int *, int>` vs `cuda_cub::functor<int *, int>`) | slice check "missing 1, unexpected 1" although the window is aligned | `check_slice.py` reconciles differing names on (function base, grid, block); `ncu_slice_check.txt` reports how many were reconciled |
| 4 pipeline threads interleave launches | launch *order* differs by a few positions between runs/iterations | counts and multisets are stable (checked); order is not relied on |
| ncu times are serialized, clock-locked (~2.29 GHz vs ~3.09 GHz boost) and taken after an L2 flush (`--cache-control all` default) | ncu kernel sum > nsys GPU busy; DRAM bytes are cold-L2 traffic | report both; wall-clock only from `.timer` / Sirius log / nsys; say "cold-L2" when quoting ncu DRAM bytes or hit rates |
| `.timer` has 1 ms resolution at SF1 | timings like 9/10/11 ms | report median/min/max; nsys gives µs-level GPU busy |
| fs_cache `cache summary` is printed at the START of a query (`prepare_for_query`) and once at shutdown | the summary inside iteration i describes iteration i-1 (the one inside iteration 1 shows the pin's reads) | require iterations + 1 summaries; summaries 2..n+1 (incl. shutdown) must be zero, covering every iteration |
| A missing pin-map column makes Sirius silently read Parquet for that scan (no error line) | fewer `assigned pinned entry` lines | require one per GPU_SCAN operator in the iteration's plan |
| A `tier='host'` pin logs the same `assigned pinned entry` line | — | tier checked in the generated SQL and in the pin SQL echoed by the log |
| Mapped pinned-host memory can be read by kernels with no memcpy | invisible to nsys memcpy tables | `check_sysmem.py`: SM (tex) sysmem-aperture sectors must be 0 for every profiled kernel. The all-source counter `syslts__t_sectors_aperture_sysmem_lookup_miss.sum` reads 265-292 sectors for EVERY kernel (non-SM per-launch traffic) and is recorded only |
| nsys writes `CUDA_UM_*_PAGE_FAULT_EVENTS` only when a fault happened | no table even with UM tracing on | the check reads the capture flags from META_DATA_CAPTURE, counts faults if the tables exist, and requires zero managed-memory API calls |
| Dynamic Bloom / IN-list filters (Q4) log "published through peer copies" | looks like a transfer | peer-copy transport is device-side; only "HOST staging" publication fails (`no_host_staged_filter_publication`); Q4's measured iterations show no copy ≥ 115,200 B |
| `[downgrade]` success is logged only at DEBUG | a downgrade could be invisible | `pool_counters_stable`: gpu_pool allocated = pinned footprint, host_pool allocated/peak unchanged in iterations ≥ 2 |
| The run that crosses midnight writes two daily log files; old dirs accumulated runs | wrong/partial log parsed | one log dir per Sirius process; `siriuslog.read_run` concatenates all files and takes the last process |
| `gpu_pool peak=` is a process-lifetime high-water mark | peak never drops | report it as "≤ high-water"; pinned footprint = `allocated=` after the last pin |
| nsys roughly doubles the engine window (12 vs 6 ms on Q2) | engine_ms in `nsys_iteration_breakdown.txt` > timing log | use nsys for GPU busy / counts, the timing log for wall split |
| `lts__t_sector_hit_rate` reads 103–105% on a few tiny kernels | out-of-range percentage | `extract_ncu.py` clamps hit rates to 100 and keeps `*_raw`; the validator fails only above 150% (114% seen on Q2); mention it in Limitations |
| Light and families reports come from different runs whose launch order differs | metrics attached to the wrong launch | merge on exact mangled name + grid + block (closest duration breaks ties); SASS export selected by mangled name inside its own report and verified by duration |
| A subagent harness may refuse to write a file named `REPORT_*.md` | Write tool error "Subagents should return findings as text" | do not work around it: return the report text to your caller and say where it belongs |
| Many SF1 kernels are 1-CTA, sub-wave, < 5 µs | DRAM% ≈ 0 for most kernels | say so with counts (phase_breakdown.txt footer) instead of a bandwidth story |

## 5. Per-query knobs (environment variables)

| Variable | Default | When to change |
|---|---|---|
| `NCU_FULL_MAX` | 1000 | warm launches above this switch to light + families. Keep. |
| `NCU_COVERAGE` | 0.90 | do not lower (validator requires 90%) |
| `SASS_TOP` | 2 | number of kernel families with SASS hotspots |
| `WARMUP` / `TIMED` / `NSYS_MEASURED` | 3 / 12 / 5 | keep |
| `PCIE_H2D_MAX_SINGLE` / `PCIE_H2D_MAX_ITER` / `PCIE_D2H_MAX_ITER` | min(64 KiB, rows/2 of the smallest pinned table with ≥ 8192 rows) / 1 MiB / max(256 KiB, 4 × result CSV bytes) | only if a legitimately large result set fails the D2H check; the validator fails unless the report names the PCIE_* variable and justifies it. Tables with < 8192 rows rest on the log + sysmem evidence (stated in pcie_verification.txt) |
| `RESULT_REL_TOL` | 1e-9 | numeric tolerance for GPU vs DuckDB-CPU results; do not raise without explaining why |
| `sirius.yaml` `usage_limit_fraction` | 0.25 (3 GB) | only if a query downgrades/spills (PCIe check fails with `[downgrade]`): copy the yaml, raise it, and say so in the report — larger pools make ncu slower |

## 6. Writing the report (checklist)

Template: `/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q2/REPORT_tpch_q2_sf1.md` and
`.../q2/physical_floor.md`. Write `physical_floor.md` FIRST, from table statistics only:

1. Pinned bytes per table: `grep "gpu_pool.*QueryEnd" $R/traces/sirius_log_timing/*.log` — the `allocated=` delta after
   each `CALL pin_table` (Sirius narrows carriers, so this is below native widths).
2. Row counts, selectivities, intermediate cardinalities: run the predicate pieces on DuckDB-CPU against the Parquet
   (`$SIRIUS/sirius-duckdb/build/release/duckdb -no-agent -csv -c "..."`; no GPU involved).
3. Floors = bytes ÷ 672 GB/s for: all pinned bytes once; native widths; minimal (predicate columns only);
   + unavoidable materialization. Add a compute estimate. Add the launch-count bound as *inferred*.

Then the report, mirroring Q2's sections. Every number must come from a file in `$R`:

| Report section | Source files |
|---|---|
| Executive summary | `timing_summary.txt`, `nsys_iteration_breakdown.txt`, `warm_kernel_summary.txt`, `phase_breakdown.txt`, `physical_floor.md` |
| Workload / plan / row counts / footprint | `query_plan.txt`, DuckDB-CPU counts, `pcie_verification.txt` (GPU memory line) |
| PCIe verification | `pcie_verification.txt` (quote the PASS lines and the per-iteration H2D/D2H numbers) |
| Environment | copy from Q2, update only if something changed |
| Floor vs measured gap | `physical_floor.md`, `timing.json` (wall), `nsys_iteration_breakdown.txt` (GPU busy at real clocks), `ncu_extract_summary.txt` (serialized) |
| Kernel / phase / operator breakdown | `phase_breakdown.txt`, `operator_breakdown.txt`, `warm_kernel_summary.txt`, plots |
| Top kernels with ncu evidence | `top_kernel_details.txt`, `ncu_warm_metrics.json` |
| Instruction-level evidence (#1 kernel) | `sass/<family>_hotspots.txt` (top instructions with stall reason, context windows around the 3 hottest PCs, instruction-class mix) |
| Root cause (≥ 3 whys, number behind every claim) | all of the above |
| Limitations | ncu clock lock/serialization/L2 flush, 1 ms timer, sampling counts, what was inferred, tables below the byte limit |

Embed the four plots as images, not just as file names: `![Phase breakdown](plots/q<N>_phase_breakdown.png)` and
`![Kernel sequence](plots/q<N>_kernel_sequence.png)` at the end of section 6, `![Stall mix](plots/q<N>_stalls.png)` and
`![Roofline](plots/q<N>_roofline.png)` at the end of section 7 (the validator checks `report_embeds_plots`).

Errors an independent review found in the Q3-Q6 reports - check your draft against each before handing it back:
- **Register-level dependency chains.** Before writing "instruction X waits on load Y", confirm X actually reads the
  register Y writes, and that both are in the same context window of `sass/*_hotspots.txt`. If the stalled register is
  loaded outside the quoted window, say so instead of inventing the producer.
- **Never-executed code.** A block whose instructions show `exe=0` costs nothing; do not put it in a per-row chain.
- **Interpretations are inferred.** What a load "is" (node record, validity bit, filter word, descriptor), why lanes are
  inactive (divergence, null checks), and what a small copy carries are inferences from shape; the counts are measured.
- **Recompute every derived number** (ratios to the floor, sums of table rows, differences, shares) from the files right
  before output, and keep ncu (serialized, cold-L2) and nsys (real-clock) values apart in the same sentence or table row.
- **Checks that saw nothing prove nothing.** E.g. `no_host_staged_filter_publication` with "0 dynamic-filter
  publications" does not show how filters are transferred; quote what the check line says.
- Family-wide averages vs single launches: do not quote the best launch's GB/s for a whole family.
- **`fused_membership_mask_kernel` has two probe rounds.** The low-lane block around +0x12600…+0x12c30 loads a fresh key
  from another kernel parameter and re-hashes it with the seed: it is a second fused probe round taken by surviving rows,
  not an open-addressing collision retry. The probe-continuation PCs (around +0x03650/+0x036e0/+0x03770) are where lanes
  thin out. Do not splice instructions from the two regions into one chain.
  The second-round block does not execute in every launch (Q19: every instruction in +0x12600…+0x12c30 has exe=0, and
  the low-lane PCs around +0x03630…+0x037d0 are the in-bucket probe continuation). Check `exe` before naming a round,
  and do not describe this kernel's lane behaviour at all unless its SASS was exported for your query.
- **`thread_eff` is a lane count, not a percentage.** It is `smsp__thread_inst_executed_per_inst_executed.ratio`: the
  average number of active lanes per executed warp instruction, 0–32 (32.0 = all lanes active). Write "14.1 of 32 lanes
  active (44%)", never "14.1% thread efficiency".
- **Dynamic-filter publication check.** The Sirius log has two kinds of lines: "dynamic-filter publication: pushed N
  dynamic filter(s) … (M build rows …)" (every filter) and "published through peer copies / HOST staging" (only filters
  that take the accumulated-Bloom path, e.g. Q4). The check counts only the second kind. If it says "0 dynamic-filter
  publications" while the log has "pushed" lines, it shows nothing about transport for those filters: say so, give the
  publication count and build rows from the log, and rest the no-PCIe claim on the H2D byte bound and the sysmem check.
- "Each sync waits for a µs-scale kernel" is inferred; nsys measures only call counts and summed CPU time.
- Count columns, joins and dynamic filters from `physical_floor.md` / `query_plan.txt`, not from memory; quote medians and
  per-family averages from the full ncu pass (`phase_breakdown.txt`, `operator_breakdown.txt`), not the list pass, or name
  the list pass as the source.

Rules: label each claim **measured** or **inferred**; do NOT recommend query-specific kernel fusion (cuDF kernels stay
general-purpose library operators; fusion may be mentioned as context only); at SF1 many kernels are tiny — state counts
(< 5 µs, < 1 wave, 1-CTA) rather than forcing a bandwidth story. Finish with
`python3 -I $P/validate_query.py <N>` → 0 FAIL, 0 PENDING.

## 6b. Cross-query summary

`<venv>/bin/python -I make_summary.py` reads every `results/q<N>/` and regenerates `results/SUMMARY_tpch_sf1.md`, three
charts in `results/summary/` and `results/summary/summary_data.json`. Rerun it after any query is re-profiled.

## 7. Files in this directory

`profile_query.sh` (entry point), `run_sirius.sh`, `gen_sql.py`, `parse_timing.py`, `siriuslog.py` (shared Sirius-log
parsing + residency checks), `pcie_verify.py`, `check_ncu_logs.py`, `check_sysmem.py`, `selftest_checks.py`,
`nsys_breakdown.py`, `kernel_list.py`, `check_slice.py`, `extract_ncu.py`, `breakdown.py`, `kclass.py`
(query-generic kernel → phase/operator classifier; extend its RULES if `operator_breakdown.txt` shows large
`other: <name>` rows), `sass_top.py`, `sass_hotspots.py`, `make_plots.py`, `validate_query.py`, `sirius.yaml`.
Testing hook: `RESULTS_DIR=/some/scratch/q<N>` redirects outputs.
