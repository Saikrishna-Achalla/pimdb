#!/usr/bin/env bash
# show.sh <rundir>: per-launch table (label | cycles flush instrs dram_reads dram_writes)
d=$1
grep -E "RESULT|GROUP|DONE|FAIL|rror|wall" $d/run.log
paste <(grep "^LAUNCH" $d/run.log | awk '{print $3, $4, $5}') <(python3 -c "
import sys; sys.path.insert(0,'/home/sai/cs254_project/sim/vortex_baseline/scripts'); import vxlog
for L in vxlog.launches('$d'): print(L['run_cycles'], L['flush_cycles'], L['run_instrs'], L['run_mem_reads'], L['run_mem_writes']+L['flush_mem_writes'])
") | column -t
