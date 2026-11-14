#!/usr/bin/env bash
# Run a prebuilt OpenCL test from a read-only Vortex build dir using the dry-run command line captured in
# <cmdline file> (from `make -n run-simx OPTS=@@OPTS@@`). Output dir is under sim_scout/vortex_q6/.
# Usage (inside vx_ro.sh): run_app_ro.sh <cmdline file> <app dir> <app name> <run tag> <class> "<opts>" [kernel.cl]
set -euo pipefail
CMDF=$1; APPDIR=$2; APP=$3; TAG=$4; CLS=$5; OPTS=$6; KSRC=${7:-$APPDIR/kernel.cl}  # optional replacement kernel.cl
R=/home/sai/cs254_project/pim_exploration/sim_scout/vortex_q6/$TAG
mkdir -p "$R" "$HOME" "$POCL_CACHE_DIR"; cd "$R"; cp "$KSRC" kernel.cl
cmd=$(sed -e "s|@@OPTS@@|$OPTS|" -e "s|\./$APP|$APPDIR/$APP|" "$CMDF")
echo "$cmd" > cmd.txt
t0=$(date +%s.%N); VORTEX_PROFILING=$CLS bash -c "$cmd" > run.log 2>&1 || true; t1=$(date +%s.%N)
echo "[$TAG] process wall: $(echo "$t1 - $t0" | bc) s"
grep -E "PASSED|FAILED|Elapsed|PERF: instrs|PERF: memory: reqs|rror" run.log
