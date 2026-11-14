#!/usr/bin/env bash
# Run the owner's prebuilt tpch_q6 (host binary) with a snapshot of prebuilt simx runtime libs, without
# writing anything into ~/pim or ~/aimdb.  Usage (host): vx_ro.sh bash run_q6_ro.sh <libtag> <sf> <global> <local> [class]
set -euo pipefail
LIB=/home/sai/aimdb/vortex/sweep/logs/fable/vx/lib_$1; SF=$2; G=$3; L=$4; CLS=${5:-7}
B=/home/sai/pim/vortex/build64-h100x8
R=/home/sai/cs254_project/pim_exploration/sim_scout/vortex_q6/run_${1}_sf${SF}_g${G}
mkdir -p "$R" "$HOME" "$POCL_CACHE_DIR"; cd "$R"
cp /home/sai/pim/vortex/tests/opencl/tpch_q6/kernel.cl kernel.cl
cmd=$(sed -e "s|@@OPTS@@|-g $G -l $L -d /home/sai/pim/q6_vortex/data/sf$SF|" -e "s|LD_LIBRARY_PATH=|LD_LIBRARY_PATH=$LIB:|" \
          -e "s|\./vx_membw|$B/tests/opencl/tpch_q6/tpch_q6|" "$LIB/cmdline")
echo "$cmd" > cmd.txt
t0=$(date +%s.%N); VORTEX_PROFILING=$CLS bash -c "$cmd" > run.log 2>&1 || true; t1=$(date +%s.%N)
echo "process wall: $(echo "$t1 - $t0" | bc) s" | tee time.log
grep -E "PASSED|FAILED|Elapsed|PERF: instrs|PERF: memory: reqs|rror" run.log
