#!/bin/bash
# Runs all DC jobs (6 PU variants x flat/hier + decoder) in parallel.  Usage: run_dc.sh [PERIOD_NS] [tag]
W=${W:-/edata1/yanggon/dc_work/pimdb_pu}   # work dir: src/ tb/ ref/ cells/ scripts/ (see ../README.md)
source /etc/profile.d/modules.sh; module load synopsys/syn/Y-2026.03-SP2 >/dev/null 2>&1
export TMPDIR=$W/tmp; mkdir -p $TMPDIR; ulimit -s unlimited
export PERIOD_NS=${1:-2.284}; TAG=${2:-p2284}
L=/mnt/nas0/eda.libs/saed14/EDK_08_2025/SAED14nm_EDK_STD_RVT/liberty/nldm
export DB="$L/base/saed14rvt_base_tt0p8v25c.db $L/cg/saed14rvt_cg_tt0p8v25c.db"
S=$W/src; PUSRC="$S/pu_pkg.sv $S/pu_cmp_seg.sv $S/pu_cfg.sv $S/pu_filter.sv $S/pu_slot.sv $S/pu_join.sv $S/pu.sv"
job() {  # name top params mode src
  local d=$W/dc/$TAG/$1; rm -rf $d; mkdir -p $d; cd $d
  TOP=$2 PARAMS=$3 MODE=$4 SRC="$5" dc_shell -no_home_init -f $W/scripts/dc_pu.tcl > dc.log 2>&1
  echo "$1: $(grep -E '^DC_(WNS|AREA|NREG|DONE|ERROR)' dc.log | tr '\n' ' ')"
}
for cfg in "filter 0 0" "join 1 0" "all 1 1"; do set -- $cfg
  for xr in 1 0; do for m in flat hier; do
    job ${1}_x${xr}.$m pu "HAS_JOIN=$2,HAS_SETSEL=$3,HAS_XREG=$xr" $m "$PUSRC" &
  done; done
done
job decoder.flat pu_decoder "" flat "$S/pu_pkg.sv $S/pu_decoder.sv" &
wait
