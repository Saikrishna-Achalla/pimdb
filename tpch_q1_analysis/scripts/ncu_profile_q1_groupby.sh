#!/usr/bin/env bash
# Targeted ncu passes for TPC-H Q1, lineitem pinned on GPU, warm (5th) query only.
# Usage: [SF=10] ncu_profile_q1_groupby.sh
# Needs the pass-1/pass-2 kernel lists from ncu_profile_q1.sh (traces/ncu_list_pinned_sf$SF_x{4,5}.csv).
#   Pass L (only with LIGHT=1; ~7 s/kernel at SF10 because every replay saves/restores GBs of device memory): lightweight metrics (time, DRAM bytes, launch shape) on ALL kernels of the warm query.
#   Pass G: --set full + SASS source on ONLY the group-by / aggregation kernels of the warm query
#           (kernel-name regex GB_RE; -s/-c count only regex-matching launches).
set -euo pipefail
cd "$(dirname "$0")/.."
SF="${SF:-10}"; TAG=pinned_sf$SF
NCU="sudo -n /usr/local/cuda/bin/ncu"
GB_RE='single_pass_shmem_aggs|mapping_indices|cuco::|open_addressing|groupby::'
X4=traces/ncu_list_${TAG}_x4.csv; X5=traces/ncu_list_${TAG}_x5.csv
[ -f scripts/q1_${TAG}_x5.sql ] && [ -f "$X4" ] && [ -f "$X5" ] || { echo "run ncu_profile_q1.sh passes 1-2 first"; exit 1; }
cnt() { venv/bin/python -I -c "
import csv,re,sys
ids={}
for r in csv.DictReader(l for l in open(sys.argv[1]) if l.startswith('\"')): ids[r['ID']]=r['Kernel Name']
print(len(ids) if sys.argv[2]=='' else sum(bool(re.search(sys.argv[2],n)) for n in ids.values()))" "$1" "$2"; }
N4=$(cnt $X4 ''); N5=$(cnt $X5 ''); G4=$(cnt $X4 "$GB_RE"); G5=$(cnt $X5 "$GB_RE")
echo "all kernels: skip $N4, profile $((N5-N4)); group-by kernels: skip $G4, profile $((G5-G4))"
LM=gpu__time_duration.sum,dram__bytes_op_read.sum,dram__bytes_op_write.sum,gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed,sm__throughput.avg.pct_of_peak_sustained_elapsed,launch__grid_size,launch__block_size,launch__registers_per_thread,launch__waves_per_multiprocessor,smsp__inst_executed.sum,sm__cycles_elapsed.avg.per_second
[ "${LIGHT:-0}" = 1 ] && { echo "== Pass L"; ./scripts/run_q1.sh scripts/q1_${TAG}_x5.sql $NCU --metrics $LM -s "$N4" -c "$((N5-N4))" \
  -o profiles/q1_sf${SF}_pinned_warm_light -f > traces/ncu_light_${TAG}_stdout.txt 2>&1 || true; }
echo "== Pass G"; ./scripts/run_q1.sh scripts/q1_${TAG}_x5.sql $NCU --set full --import-source yes \
  --kernel-name-base demangled -k "regex:$GB_RE" -s "$G4" -c "$((G5-G4))" \
  -o profiles/q1_sf${SF}_pinned_warm_groupby_full -f > traces/ncu_groupby_${TAG}_stdout.txt 2>&1 || true
echo "== DONE"; ls -la profiles/ | grep sf$SF
