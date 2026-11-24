#!/bin/bash
# Gate-level check (PLAN F21): the synthesized Nangate45 netlists, with each cell expanded from its Liberty function,
# run the same vectors as the RTL. CHECK_STATE = 0: PRD words and the read path only (the random vectors force a
# PMC M <- M1 / V; PRD pair on 5 % of commands, so M1 and V are observed too). Exits non-zero unless all pass.
export PATH=~/tools/oss-cad-suite/bin:$PATH
cd "$(dirname "$0")"
LIB=~/tools/pdk/nangate45/NangateOpenCellLibrary_typical.lib
rm -rf gls; mkdir -p gls
for tag in filter_x1 filter_x0 join_x1 join_x0 all_x1 all_x0; do
  yosys -q -p "read_liberty -ignore_miss_func $LIB; read_verilog out/$tag.flat.v; hierarchy -top pu; flatten;
               opt_clean; rename pu pu_gl; write_verilog -noattr gls/$tag.v" 2>&1 | grep -v Warning | head -3
done
cd ../tb
B=build_gl; rm -rf $B; mkdir -p $B; : > $B/results.txt
sed 's/^  pu #(.HAS_JOIN(HAS_JOIN), .HAS_SETSEL(HAS_SETSEL), .HAS_XREG(HAS_XREG)) dut (/  pu_gl dut (/' tb_pu.sv > $B/tb_gl.sv
grep -q "pu_gl dut" $B/tb_gl.sv || { echo "testbench substitution failed"; exit 1; }
N=0
run() {  # netlist vec join setsel xreg
  local D=""; [ "$3" = 0 ] && D="-DNO_JOIN_STATE"; N=$((N + 1))
  iverilog -g2012 $D -o $B/$1_$2.vvp -s tb_pu -P tb_pu.HAS_JOIN=$3 -P tb_pu.HAS_SETSEL=$4 -P tb_pu.HAS_XREG=$5 \
    -P tb_pu.CHECK_STATE=0 ../src/pu_pkg.sv ../syn/gls/$1.v $B/tb_gl.sv 2>&1 | grep -iE "error" | head -3
  vvp -n $B/$1_$2.vvp +VEC=vec/$2 | grep -E "RESULT|mismatch" | sed "s/^/[gate $1] /" | head -4 | tee -a $B/results.txt
}
run filter_x1 rand_filter 0 0 1
run filter_x0 rand_filter 0 0 0
run filter_x1 replay_q6 0 0 1
run filter_x1 replay_q19la 0 0 1
run join_x1 rand_nosel 1 0 1
run join_x0 rand_nosel 1 0 0
run join_x1 replay_q12join 1 0 1
run all_x1 rand_all 1 1 1
run all_x0 rand_all 1 1 0
run all_x1 replay_q12la 1 1 1
run all_x1 replay_q19la 1 1 1
P=$(grep -c "RESULT.* 0 errors" $B/results.txt); echo "== $P of $N gate-level runs passed"; [ "$P" = "$N" ]
