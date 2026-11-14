#!/usr/bin/env bash
# Profile TPC-H query N at SF1 on Sirius with all referenced columns pinned in GPU memory.
#
# Usage: profile_query.sh <N> [stage ...]
#   stages (default, in order): sql timing pcie selftest list detail extract validate
#   detailcheck (on demand) = re-verify existing ncu reports with the current checks, no re-profiling
#   selftest = negative control: the largest referenced table left unpinned => pcie_verify.py MUST fail (~15 s GPU)
# Env:   REDO=1         rerun stages even if their .done marker exists (running a stage always invalidates the
#                       .done markers of every LATER stage, so their outputs are rebuilt on the next run)
#        NCU_FULL_MAX   max warm-iteration launches for `--set full` on ALL warm kernels (default 1000; ~1.5 s/kernel)
#        NCU_COVERAGE   time coverage of the families given --set full otherwise (default 0.90)
#        WARMUP (3), TIMED (12), NSYS_MEASURED (5)
# Output: /home/sai/cs254_project/tpch_q1_analysis/analysis/results/q<N>/   (see RUNBOOK.md)
# A failing stage stops the run with a non-zero exit; failures that make the query's data unusable write ERROR.txt.
set -euo pipefail
N="${1:?usage: profile_query.sh <N> [stage...]}"; shift
ORDER="sql timing pcie selftest list detail extract validate"
STAGES="${*:-$ORDER}"
P="$(cd "$(dirname "$0")" && pwd)"
A=/home/sai/cs254_project/tpch_q1_analysis
# sf10_scaling copy: SF selects the dataset (default 10). Output: SF10 + CFG=main -> sf10_scaling/q<N>/, otherwise
# sf10_scaling/q<N>/sf<SF>_<CFG>/. Every GPU process runs under flock $GPULOCK (shared with another agent).
SF=${SF:-10}
export TPCH_PARQUET_DIR=/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf$SF
E=/home/sai/cs254_project/pim_exploration/sf10_scaling
GPULOCK=/home/sai/cs254_project/pim_exploration/.gpu.lock
# CFG selects the Sirius config: main = sirius.yaml (0.85 pool, derived batch 262 MB); b77 = sirius_b77.yaml (0.85 pool,
# batch settings forced to the SF1 pipeline's derived values, 77 MB); sf1pipe = the original tpch_sf1/sirius.yaml.
CFG=${CFG:-main}
case $CFG in main) Y=$P/sirius.yaml;; b77) Y=$P/sirius_b77.yaml;; sf1pipe) Y=/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1/sirius.yaml;; *) echo "bad CFG"; exit 2;; esac
export SIRIUS_YAML=$Y
if [ "$SF" = 10 ] && [ "$CFG" = main ]; then R=${RESULTS_DIR:-$E/q$N}
else R=${RESULTS_DIR:-$E/q$N/sf${SF}_$CFG}; fi
PY="$A/venv/bin/python -I"
SIRIUS=/home/sai/cs254_project/sirius
DUCKDB=$SIRIUS/sirius-duckdb/build/release/duckdb
NCU="sudo -n /usr/local/cuda/bin/ncu"
NSYS=/home/sai/nsight-systems-2025.5/opt/nvidia/nsight-systems/2025.5.2/target-linux-x64/nsys  # 2025.1.3 in /usr/local/cuda cannot decode CUDA 13 traces
# -s none / --cpuctxsw none: CPU sampling signals cancel Sirius's io_uring reads during pin_table.
# UM page-fault tracing: without it unified-memory traffic would be invisible (pcie_verify.py requires the tables).
NSYS_ARGS=(profile -t cuda -s none --cpuctxsw=none --backtrace=none --cuda-um-cpu-page-faults=true --cuda-um-gpu-page-faults=true -f true --export sqlite)
WARMUP=${WARMUP:-3}; TIMED=${TIMED:-12}; NSYS_MEASURED=${NSYS_MEASURED:-5}
NCU_FULL_MAX=${NCU_FULL_MAX:-1000}; NCU_COVERAGE=${NCU_COVERAGE:-0.90}
ITERS=$((WARMUP + TIMED))
TABLES=$(python3 -I "$P/gen_sql.py" tables "$N")
mkdir -p "$R"/{sql,traces,profiles,sass,plots}
# light set: ONE ncu pass (no replay -> nearly free; measured on Q2). It includes the aggregate SM (tex) sysmem-aperture
# sector counter so the light branch also proves "no in-place access to mapped host memory" (check_sysmem.py); adding the
# four per-op counters (read/write/atom/red) would make it 3 replay passes (~0.7 s/kernel), so they come from --set full only.
LM=gpu__time_duration.sum,dram__bytes_op_read.sum,dram__bytes_op_write.sum,launch__grid_size,launch__block_size,launch__registers_per_thread,launch__waves_per_multiprocessor,smsp__inst_executed.sum,sm__cycles_elapsed.avg.per_second,syslts__t_sectors_srcunit_tex_aperture_sysmem_lookup_miss.sum

log() { echo "[$(date +%H:%M:%S)] q$N $*"; }
die() { echo "ERROR q$N: $*" >&2; exit 1; }
error_file() { { echo "q$N stage '$1' failed at $(date): $2"; } > "$R/ERROR.txt"; die "$2 (see $R/ERROR.txt)"; }
gpu_idle() { :; }  # sf10_scaling copy: exclusivity comes from flock $GPULOCK in run_logged (another agent shares the GPU)
fail_query() {  # record a GPU-path failure (unsupported operator, OOM, ...) and stop
  { echo "q$N failed on the Sirius GPU path during stage '$1' at $(date)"; echo "--- error lines ---";
    grep -iE "error|exception|not implemented|unsupported|out of memory" "$2" | head -40; echo "--- tail of $2 ---"; tail -40 "$2"; } > "$R/ERROR.txt"
  die "query failed on the GPU path; see $R/ERROR.txt"
}
run_stage() {
  local s=$1 later=0 x
  if [ -f "$R/.done_$s" ] && [ "${REDO:-0}" != 1 ]; then log "stage $s: done earlier (REDO=1 to rerun)"; return; fi
  for x in $ORDER; do [ $later = 1 ] && rm -f "$R/.done_$x"; [ "$x" = "$s" ] && later=1; done
  local t0=$SECONDS; log "stage $s: start"; rm -f "$R/.done_$s"
  "stage_$s"
  echo "$((SECONDS - t0))" > "$R/.done_$s"; log "stage $s: ok ($((SECONDS - t0)) s)"
}
# run Sirius under a prefix into a FRESH per-run log directory (one Sirius process per directory)
run_logged() { local sql=$1 logdir=$2; shift 2; rm -rf "${logdir:?}"; flock "$GPULOCK" "$P/run_sirius.sh" "$sql" "$logdir" "$@"; }

stage_sql() {
  python3 -I "$P/gen_sql.py" "$N" "$ITERS" pin > "$R/sql/q${N}_timing.sql"
  python3 -I "$P/gen_sql.py" "$N" "$ITERS" cpu > "$R/sql/q${N}_cpu.sql"
  for k in 3 4 5; do python3 -I "$P/gen_sql.py" "$N" $k pin > "$R/sql/q${N}_ncu_x$k.sql"; done
  python3 -I "$P/gen_sql.py" "$N" $((WARMUP + NSYS_MEASURED)) pin --sleep 0.3 > "$R/sql/q${N}_nsys.sql"
}

stage_timing() {
  gpu_idle; rm -f "$R/ERROR.txt"
  run_logged "$R/sql/q${N}_timing.sql" "$R/traces/sirius_log_timing" > "$R/traces/timing_run.txt" 2>&1 \
    || fail_query timing "$R/traces/timing_run.txt"
  grep -qiE "^(Error|Invalid Error|.*Exception)" "$R/traces/timing_run.txt" && fail_query timing "$R/traces/timing_run.txt"
  "$DUCKDB" -no-agent -bail < "$R/sql/q${N}_cpu.sql" > "$R/traces/duckdb_cpu_run.txt" 2>&1 || die "DuckDB CPU run failed"
  local rc=0
  python3 -I "$P/parse_timing.py" "$R/traces/timing_run.txt" "$R/traces/duckdb_cpu_run.txt" \
    "$R/traces/sirius_log_timing" "$WARMUP" "$R" || rc=$?
  [ $rc = 2 ] && error_file timing "GPU result differs from DuckDB-CPU or between iterations (timing_summary.txt)"
  [ $rc = 0 ] || die "parse_timing.py failed ($rc)"
}

stage_pcie() {
  gpu_idle
  rm -f "$R"/traces/q${N}_nsys.{nsys-rep,sqlite}
  run_logged "$R/sql/q${N}_nsys.sql" "$R/traces/sirius_log_nsys" "$NSYS" "${NSYS_ARGS[@]}" -o "$R/traces/q${N}_nsys" \
    > "$R/traces/nsys_run.txt" 2> "$R/traces/nsys_run.err" || fail_query pcie "$R/traces/nsys_run.txt"
  [ -s "$R/traces/q${N}_nsys.sqlite" ] || die "nsys produced no sqlite export (see traces/nsys_run.err)"
  local rc=0
  python3 -I "$P/pcie_verify.py" "$N" "$R" "$R/traces/sirius_log_timing" "$R/traces/sirius_log_nsys" \
    "$R/traces/q${N}_nsys.sqlite" "$WARMUP" $TABLES || rc=$?
  [ $rc = 3 ] && error_file pcie "kernel launches per measured iteration differ in the nsys run (determinism, not PCIe; see pcie_verification.txt)"
  [ $rc = 0 ] || error_file pcie "PCIe/residency verification FAILED (see pcie_verification.txt)"
  python3 -I "$P/nsys_breakdown.py" "$R"
}

stage_list() {
  local M=gpu__time_duration.sum,launch__grid_size,launch__block_size,launch__registers_per_thread k
  rm -rf "$R"/traces/sirius_log_ncu_list   # pre-hardening single shared directory
  for k in 3 4 5; do
    gpu_idle
    rm -f "$R/traces/ncu_list_x$k.csv"
    run_logged "$R/sql/q${N}_ncu_x$k.sql" "$R/traces/sirius_log_ncu_list_x$k" \
      $NCU --metrics $M --csv --print-units base --log-file "$R/traces/ncu_list_x$k.csv" \
      > "$R/traces/ncu_list_x$k.stdout" 2>&1 || die "ncu list pass x$k failed (see traces/ncu_list_x$k.stdout)"
  done
  python3 -I "$P/check_ncu_logs.py" "$R" list $TABLES || error_file list "residency log checks failed for an ncu list run (ncu_log_checks_list.txt)"
  $PY "$P/kernel_list.py" "$R"/traces/ncu_list_x{3,4,5}.csv "$R" "$NCU_FULL_MAX" "$NCU_COVERAGE" \
    || die "kernel launch list is not deterministic (ERROR.txt, warm_kernel_summary.txt)"
}

stage_detail() {
  local stable skip count policy rx rs rc
  read -r stable skip count policy rx rs rc < <($PY -c "import json;p=json.load(open('$R/ncu_plan.json'));print(p['stable'],p['skip'],p['count'],p['policy'],p['full_regex'],p['full_regex_skip'],p['full_regex_count'])")
  [ "$stable" = True ] || die "ncu_plan.json says launch counts are not stable; refusing to profile a slice that cannot be trusted"
  rm -f "$R"/profiles/q${N}_warm_*.ncu-rep
  rm -rf "$R"/traces/sirius_log_ncu_detail "$R"/traces/sirius_log_ncu_detail_*
  gpu_idle
  if [ "$policy" = full_all ]; then
    log "ncu --set full on all $count warm kernels (skip $skip)"
    run_logged "$R/sql/q${N}_ncu_x5.sql" "$R/traces/sirius_log_ncu_detail_full" \
      $NCU --set full --import-source yes -s "$skip" -c "$count" -o "$R/profiles/q${N}_warm_full" -f \
      > "$R/traces/ncu_detail_full.log" 2>&1 || die "ncu full pass failed (traces/ncu_detail_full.log)"
  else
    log "ncu light metrics on all $count warm kernels; --set full on $rc kernels of families $rx (skip $rs)"
    run_logged "$R/sql/q${N}_ncu_x5.sql" "$R/traces/sirius_log_ncu_detail_light" \
      $NCU --metrics "$LM" -s "$skip" -c "$count" -o "$R/profiles/q${N}_warm_light" -f \
      > "$R/traces/ncu_detail_light.log" 2>&1 || die "ncu light pass failed (traces/ncu_detail_light.log)"
    gpu_idle
    run_logged "$R/sql/q${N}_ncu_x5.sql" "$R/traces/sirius_log_ncu_detail_families" \
      $NCU --set full --import-source yes -k "regex:$rx" -s "$rs" -c "$rc" \
      -o "$R/profiles/q${N}_warm_families_full" -f \
      > "$R/traces/ncu_detail_families.log" 2>&1 || die "ncu family pass failed (traces/ncu_detail_families.log)"
  fi
  detail_checks
}

detail_checks() {  # post-ncu checks on the reports + the Sirius logs of the runs that produced them
  $PY "$P/check_slice.py" "$R" || die "ncu report kernels do not match the expected warm-iteration slice (misaligned skip?)"
  python3 -I "$P/check_ncu_logs.py" "$R" detail $TABLES || error_file detail "residency log checks failed for an ncu detail run (ncu_log_checks_detail.txt)"
  python3 -I "$P/check_sysmem.py" "$R" || error_file detail "a profiled kernel accessed system memory through the sysmem aperture, or the metric is missing (ncu_sysmem_check.txt)"
}

# Re-verify EXISTING detail reports with the current checks instead of re-profiling (on demand; not in the default
# order). Requires the Sirius log of the run that produced each report. One-time migration for results made before
# per-run log dirs: traces/sirius_log_ncu_detail (one full_all run) -> traces/sirius_log_ncu_detail_full.
# On success it marks stage detail done (the reports are accepted as the detail-stage output).
stage_detailcheck() {
  if [ -d "$R/traces/sirius_log_ncu_detail" ] && [ ! -d "$R/traces/sirius_log_ncu_detail_full" ] && [ -f "$R/profiles/q${N}_warm_full.ncu-rep" ]; then
    mv "$R/traces/sirius_log_ncu_detail" "$R/traces/sirius_log_ncu_detail_full"
  fi
  detail_checks
  echo "detailcheck" > "$R/.done_detail"
}

stage_extract() {
  find "$R/sass" "$R/plots" -type f -delete   # never mix files from an earlier extraction
  $PY "$P/extract_ncu.py" "$R" > "$R/ncu_extract_summary.txt"; cat "$R/ncu_extract_summary.txt"
  $PY "$P/breakdown.py" "$R"
  $PY "$P/sass_top.py" "$R" "${SASS_TOP:-2}"
  $PY "$P/make_plots.py" "$R" "$N"
}

stage_validate() { python3 -I "$P/validate_query.py" "$N" --pipeline | tee "$R/validate_pipeline.txt"; }

stage_selftest() {  # negative control: the largest referenced table unpinned => pcie_verify.py MUST fail
  local T=$R/selftest big rc=0
  big=$(python3 -I "$P/gen_sql.py" largest "$N")
  rm -rf "${T:?}"; mkdir -p "$T/sql" "$T/traces"
  python3 -c "import json,sys;t=json.load(open(sys.argv[1]));t['iterations']=int(sys.argv[3]);json.dump(t,open(sys.argv[2],'w'))" \
    "$R/timing.json" "$T/timing.json" $((WARMUP + 2))
  python3 -I "$P/gen_sql.py" "$N" $((WARMUP + 2)) pin --sleep 0.3 --omit-pin "$big" > "$T/sql/q${N}_nsys.sql"
  gpu_idle
  run_logged "$T/sql/q${N}_nsys.sql" "$T/traces/sirius_log_nsys" "$NSYS" "${NSYS_ARGS[@]}" -o "$T/traces/q${N}_nsys" \
    > "$T/traces/nsys_run.txt" 2> "$T/traces/nsys_run.err" || die "selftest nsys run failed"
  python3 -I "$P/pcie_verify.py" "$N" "$T" "$T/traces/sirius_log_nsys" "$T/traces/sirius_log_nsys" \
    "$T/traces/q${N}_nsys.sqlite" "$WARMUP" $TABLES > "$T/pcie_verify_stdout.txt" 2>&1 || rc=$?
  { echo "negative control: '$big' left unpinned; pcie_verify.py exit code $rc (1 expected)";
    grep "^\[FAIL\]" "$T/pcie_verification.txt" || true
    [ $rc = 1 ] && echo "SELFTEST: PASS (verification detected the unpinned table)" || echo "SELFTEST: FAIL (verification did not fail)"; } \
    | tee "$R/selftest_negative_control.txt"
  [ $rc = 1 ] || die "negative control did not fail the PCIe verification"
}

T0=$SECONDS
for s in $STAGES; do run_stage "$s"; done
log "pipeline finished in $((SECONDS - T0)) s"
