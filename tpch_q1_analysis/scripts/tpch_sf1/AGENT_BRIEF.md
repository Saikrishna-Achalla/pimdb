# Brief for the agent profiling one TPC-H query (SF1) on Sirius

You were given a query number **N** and possibly query-specific notes. Everywhere below, `<N>` is that number.

You are profiling **TPC-H Q<N> at scale factor 1** on Sirius (a GPU SQL engine on DuckDB + libcudf) with a ready-made
pipeline, then writing the analysis.

## Setup (already built, hardened and validated — do not rebuild anything)

- Pipeline + runbook: `/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1/` — **read `RUNBOOK.md` in full before
  doing anything**; it has the exact commands, stages, expected times, output files, failure triage, pitfalls and the
  report checklist. Its report section lists errors an independent review found in earlier reports (register-level
  dependency chains, never-executed code, inferred-vs-measured labels, arithmetic, the two probe rounds of
  `fused_membership_mask_kernel`, operator counts taken from memory); check your draft against every item of that list
  before handing it back.
- Output directory: `R=/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q<N>`
- Worked examples (complete result directories with `physical_floor.md` and `REPORT_tpch_q<M>_sf1.md`):
  `/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q2/ … q13/`. Use q12's report as the template for structure
  and level of evidence unless your notes name a closer one.
- Machine: one RTX 5070 (12 GB, 672 GB/s peak DRAM bandwidth, sm_120, 48 SMs). You are the only GPU user. Never start
  two GPU processes at once. `sudo -n /usr/local/cuda/bin/ncu` is the only sudo allowed (the pipeline does it for you).
- The requirement behind this campaign: all table data must be resident in GPU memory (`pin_table(tier='gpu')`) so that
  nothing crosses the PCIe bus in the measured iterations. The pipeline proves or disproves this; report exactly what it
  found.
- Read the query text yourself (`/home/sai/cs254_project/sirius/test/tpch_performance/tpch_queries/orig/q<N>.sql`) — do
  not assume the standard TPC-H constants.
- CPU fallback is disabled (`enable_duckdb_fallback=false`): if Sirius cannot run the query on the GPU, the timing stage
  fails and writes `$R/ERROR.txt`. If that happens, stop and report the exact error; do not change the query or work
  around it.
- If the warm iteration has more than 1000 kernel launches the pipeline switches to the light + families ncu policy —
  say which branch it took.

## Steps

1. Run the first stages (well under a minute):
   `mkdir -p $R && /home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1/profile_query.sh <N> sql timing pcie selftest > $R/pipeline_run.log 2>&1`.
   If it exits non-zero, read the log, `$R/ERROR.txt` and `$R/pcie_verification.txt`, follow the RUNBOOK's failure
   triage, and stop.
2. Write `$R/physical_floor.md` NOW, before looking at any ncu output, following the RUNBOOK's report section and the
   layout of `q12/physical_floor.md`: pinned bytes per table from the Sirius log, row counts / selectivities /
   intermediate cardinalities from DuckDB-CPU queries on the Parquet files, floors = bytes ÷ 672 GB/s for the scenarios
   listed there, plus a compute estimate.
3. Run the rest: `/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1/profile_query.sh <N> >> $R/pipeline_run.log 2>&1`
   in the background and wait for it to exit (completed stages are skipped). Expect roughly 1 min + 1.5 s per
   warm-iteration kernel launch. Do not start anything else on the GPU meanwhile and do not edit any pipeline script
   while it runs. When waiting, do not use `pgrep -f profile_query.sh` in a loop (it matches itself); wait on the
   background job or poll for `$R/.done_validate` / the "pipeline finished" or "ERROR" line in the log.
4. Check `$R/validate_pipeline.txt`: 0 FAIL (PENDING for the report is expected). If `$R/operator_breakdown.txt` has
   `other: <name>` rows totalling more than ~5% of GPU time, add rules for those kernel names to `kclass.py` (the only
   pipeline file you may edit, and only while no pipeline is running), then rerun
   `REDO=1 .../profile_query.sh <N> extract validate`.
5. **If any stage or check fails: stop, do not edit other scripts and do not bypass the check.** Diagnose precisely
   (the failing check's output and what you compared), say whether it looks like a real violation or a too-strict
   check, and report.
6. Analyse the outputs and compose the report.

## The report

Do NOT write the report to a file — the harness blocks subagents from writing `REPORT_*.md`, and you must not work
around that (no alternative file name either). The orchestrator files it as `$R/REPORT_tpch_q<N>_sf1.md` by extracting
it from your transcript (relative links assume that location).

Keep it under ~220 lines of Markdown, dense with numbers. Start with the title line and the header block (Date
2026-11-13, GPU, Workload, Framework, Pipeline + wall time, Labels) exactly as in the Q12 report, then the same 14
sections: 1 Executive Summary (incl. a where-the-wall-time-goes table); 2 Workload Description; 3 PCIe Verification;
4 Environment; 5 Physical Floor vs Measured; 6 Kernel, Phase and Operator Breakdown; 7 Top Kernels (ncu `--set full`);
8 Instruction-Level Evidence for the #1 kernel (hot SASS instructions → stall reason → the dependency chain, quoted as
SASS); 9 Root Cause Analysis (for the top 2–3 time sinks: symptom → WHY → WHY → WHY → ROOT with a number and a
measured/inferred label on every step); 10 Gap Analysis; 11 Optimization Directions; 12 Determinism and Profiling
Method; 13 Limitations; 14 Raw Data.

Rules:
- Embed the four plots as images: `![Phase breakdown](plots/q<N>_phase_breakdown.png)` and
  `![Kernel sequence](plots/q<N>_kernel_sequence.png)` at the end of section 6;
  `![Stall mix](plots/q<N>_stalls.png)` and `![Roofline](plots/q<N>_roofline.png)` at the end of section 7.
- Every number must come from a file in `$R` — name the file. If something is not available, say so; do not estimate
  silently. Label claims *measured* or *inferred*. Do not import numbers or mechanisms from other queries' reports
  without saying so. Recompute every derived number (sums, differences, ratios, per-row and per-byte figures) right
  before output. Count operators (scans, joins, dynamic filters) by their distinct ids in `query_plan.txt` — the file
  names each operator more than once.
- For a dependency chain, confirm register by register that the stalled instruction reads what the quoted load writes,
  within one context window of the hotspots file; otherwise say the producer is outside the window. Code with `exe=0`
  is not part of any per-row chain. What a load "is" and why lanes are inactive are inferences — label them.
- For the PCIe section use the wording of the checks in your own `pcie_verification.txt`, `ncu_sysmem_check.txt`,
  `ncu_log_checks_*.txt` and `selftest_negative_control.txt`; a check that saw zero events proves nothing about how
  those events would be handled — quote what the line says.
- Never write "nothing crosses PCIe": small control copies do, every iteration. Write "no table data cross PCIe" and give
  the per-iteration H2D and D2H copy counts and bytes. When you say which kernels "fill the GPU", list every family
  that reaches ≥ 1 wave (from `ncu_warm_metrics.json`), and take "best DRAM%" from the maximum over all kernels.
  `thread_eff` / `active_lanes_per_inst` is a lane count (0–32), never a percentage; one warp instruction serves up to
  32 rows, so convert warp instructions to per-row figures explicitly. Never subtract an ncu number from an nsys number.
- No surface-level explanations ("slow because of memory stalls"): tie stalls to specific instructions and dependency
  chains.
- At SF1 many kernels are tiny (single CTA, sub-wave, < 5 µs): state the counts instead of forcing a bandwidth story;
  where a kernel does fill the GPU, compare it against the bandwidth/throughput ceilings. ncu durations are serialized,
  clock-locked and taken with the L2 cache flushed before each kernel — say so, use nsys for real-clock times, and
  never mix the two in one sum.
- Project rule: do NOT recommend query-specific kernel fusion; cuDF kernels stay general-purpose library operators
  (fusion may be mentioned as context only).

## Constraints

- Do not modify or rebuild Sirius or cuDF, do not git-commit, no LD_PRELOAD. Write only inside `$R` (plus `kclass.py`
  rules as described). No extra scripts or planning documents.
- Run long commands in the background and wait; never run two pipelines at once.

## How to hand the work back (two separate messages — this matters)

A. First output the complete report as an ordinary assistant text message (NOT your final message): a line containing
   only `<<<REPORT`, the full Markdown report, a line containing only `REPORT>>>`. Immediately after that message, run
   one more tool call: `ls $R | wc -l`.
B. Then send your final message, which must NOT repeat the report and must not contain the marker strings. It contains
   only (plain facts, ≤ 35 lines): pipeline exit status and total wall time with per-stage seconds; the
   `SUMMARY q<N>: ...` line from validate and any FAIL lines verbatim; PCIe verdict with per-iteration H2D/D2H bytes and
   largest single copy, GPU scan count vs pinned-entry assignments, sysmem-aperture result and negative-control result;
   GPU pool high-water mark; warm kernel launch count and ncu policy branch; warm median vs DuckDB-CPU and the result
   compare mode; GPU busy per iteration (nsys); the top 3 kernel families with their share of real-clock kernel time
   and a one-line mechanism each; physical floor and the wall/GPU-busy ratios to it; whether you edited `kclass.py`
   (what you added); anything that went wrong, that you could not verify, or that you inferred rather than measured;
   and any sentence in the report you already know needs correcting, with the exact old text and the corrected text.
   If the query failed on the GPU path, the final message is the exact error and the stage it came from, and there is
   no report.
