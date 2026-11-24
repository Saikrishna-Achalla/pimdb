#!/bin/bash
# Per flat netlist: PT timing; for PU variants also VCS zero-delay gate sim (lib2v cell models) -> VCD -> PrimePower.
# Usage: run_pwr.sh [TAG=p2284] [PERIOD_NS=2.284]
W=${W:-/edata1/yanggon/dc_work/pimdb_pu}; TAG=${1:-p2284}; export PERIOD_NS=${2:-2.284}
source /etc/profile.d/modules.sh
module load synopsys/prime/Y-2026.03-SP3 synopsys/vcs/X-2025.06-SP1 >/dev/null 2>&1
export TMPDIR=$W/tmp; mkdir -p $TMPDIR
L=/mnt/nas0/eda.libs/saed14/EDK_08_2025/SAED14nm_EDK_STD_RVT/liberty/nldm
export DB="$L/base/saed14rvt_base_tt0p8v25c.db $L/cg/saed14rvt_cg_tt0p8v25c.db"
pwr() {  # variant vecset xreg   (vecset empty = timing only)
  local v=$1 vec=$2 xr=$3 d=$W/pwr/$TAG/$1 dc=$W/dc/$TAG/$1.flat
  rm -rf $d; mkdir -p $d; cd $d
  local top=$(awk '/^module/{print $2; exit}' $dc/out/net.v)
  local vcdf=""
  if [ -n "$vec" ]; then
    sed "s/^module $top /module pu /" $dc/out/net.v > net_sim.v
    vcs -full64 -sverilog -timescale=1ns/1ps +nospecify +notimingcheck -l compile.log -o simv \
        -top tb_pu -pvalue+tb_pu.HAS_XREG=$xr -pvalue+tb_pu.PER_NS=$PERIOD_NS \
        $W/cells/saed14_cells.v net_sim.v $W/tb/tb_pu_pwr.sv > /dev/null 2>&1 || { echo "$v: VCS compile FAILED"; return; }
    ./simv +VEC=$W/tb/vec/$vec +VCD=$d/pu.vcd -l sim.log > /dev/null 2>&1
    echo "$v: $(grep -E '^RESULT|WINDOW' sim.log | tr '\n' ' ')"
    grep -q 'RESULT.* 0 errors' sim.log || { echo "$v: GATE SIM FAILED"; return; }
    vcdf=$d/pu.vcd
  fi
  TOP=$top NET=$dc/out/net.v SDC=$dc/out/design.sdc VCD=$vcdf pt_shell -f $W/scripts/pt_pu.tcl > pt.log 2>&1
  echo "$v: $(grep -E '^PT_(WNS|NVIOL|POWER|DONE|ERROR)' pt.log | tr '\n' ' ')"
}
pwr filter_x1 rand_filter 1 & pwr filter_x0 rand_filter 0 &
pwr join_x1 rand_nosel 1 &    pwr join_x0 rand_nosel 0 &
pwr all_x1 rand_all 1 &       pwr all_x0 rand_all 0 &
pwr decoder "" "" &
wait; echo ALL_DONE
