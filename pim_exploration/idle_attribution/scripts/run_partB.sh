#!/usr/bin/env bash
# Part B: CPU-sampled (and unsampled reference) Sirius runs of TPC-H query N at SF1, same pin setup as the SF1 pipeline.
# Usage: run_partB.sh <N> <mode> [iters]
#   mode plain    : no profiler (reference wall times; .timer + Sirius log)
#   mode cudatrace: nsys CUDA trace only (same flags as the SF1 pipeline's pcie stage, no UM faults)
#   mode cpu      : nsys CUDA + OS-runtime trace + CPU IP sampling with LBR backtraces + context switches,
#                   collection delayed past pin_table (CPU sampling cancels Sirius's io_uring reads during the pin)
# Every GPU process runs under flock on the shared lock. Outputs: runs/q<N>_<mode>/
set -euo pipefail
N=$1; MODE=$2; IT=${3:-43}
H="$(cd "$(dirname "$0")" && pwd)"; D="$(dirname "$H")"
O="$D/runs/q${N}_${MODE}"; rm -rf "$O"; mkdir -p "$O"
NSYS=/home/sai/nsight-systems-2025.5/opt/nvidia/nsight-systems/2025.5.2/target-linux-x64/nsys
LOCK=/home/sai/cs254_project/pim_exploration/.gpu.lock
PRE_SLEEP=${PRE_SLEEP:-6}; DELAY=${DELAY:-4}
python3 -I "$H/gen_sql.py" "$N" "$IT" pin --sleep 0.05 | sed "s/^\.print __PIN_END__$/.print __PIN_END__\n.shell sleep $PRE_SLEEP/" > "$O/q$N.sql"
case $MODE in
  plain)     PFX=() ;;
  cudatrace) PFX=("$NSYS" profile -t cuda -s none --cpuctxsw=none --backtrace=none -f true --export sqlite -o "$O/q$N") ;;
  cpu)       PFX=("$NSYS" profile -t cuda,osrt -s process-tree --cpuctxsw=process-tree --backtrace=lbr --sampling-period=${SP:-343750}
                  --osrt-threshold=1000 -y "$DELAY" -f true --export sqlite -o "$O/q$N") ;;
  *) echo "bad mode"; exit 2 ;;
esac
t0=$(date +%s.%N)
flock "$LOCK" "$H/run_sirius.sh" "$O/q$N.sql" "$O/sirius_log" "${PFX[@]}" > "$O/run.txt" 2> "$O/run.err" || { echo "run failed rc=$?"; tail "$O/run.err"; exit 1; }
echo "wall incl. lock wait: $(echo "$(date +%s.%N) - $t0" | bc) s"
grep -c "Run Time" "$O/run.txt"
