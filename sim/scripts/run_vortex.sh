#!/usr/bin/env bash
# Run one OpenCL host program on simx for one configuration, in its own working directory.
#   sim/scripts/run_vortex.sh <config> <rundir> <kernel.cl> <host binary> [args...]
# The run directory receives kernel.cl, run.log (stdout+stderr), launch.log (one RUN/FLUSH line per
# kernel launch, from vortex_launch_log.patch), ramulator.stats.log, and its own PoCL cache, so runs
# can go in parallel. VORTEX_PROFILING (default 7: memory class) is passed through.
set -euo pipefail
CFG=$1; R=$2; K=$3; BIN=$4; shift 4
S=/home/sai/cs254_project/sim
B=$S/vortex/build64-$CFG
ENVF=$B/vx_run_env.txt
[ -s "$ENVF" ] || { echo "no build for $CFG ($ENVF); run sim/scripts/setup_vortex.sh $CFG" >&2; exit 2; }
mkdir -p "$R/pocl"
cp "$K" "$R/kernel.cl"
rm -f "$R/launch.log" "$R/ramulator.stats.log"
ARGS=$(printf '%q ' "$@")
echo "$CFG $BIN $ARGS" > "$R/cmd.txt"
t0=$(date +%s.%N)
VX_POCL_CACHE=$R/pocl VX_WORKDIR=$R $S/scripts/vx.sh \
  "$(cat "$ENVF") VX_LAUNCH_LOG=$R/launch.log VORTEX_PROFILING=${VORTEX_PROFILING:-7} VORTEX_DRIVER=simx $BIN $ARGS" \
  > "$R/run.log" 2>&1 || rc=$?
t1=$(date +%s.%N)
echo "wall_s=$(echo "$t1 - $t0" | bc) rc=${rc:-0}" >> "$R/run.log"
exit ${rc:-0}
