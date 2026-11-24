#!/bin/bash
# Yosys + ABC synthesis of the PU to the Nangate45 (FreePDK45) typical library.
# Reports: cell area, gate-equivalents (area / NAND2_X1 = 0.798 um^2), flip-flops, flop-to-flop logic depth.
# ABC maps with buffering and sizing (-constr: BUF_X1 driver, 3 fF load per output, review IMPL F5). No timing
# constraint is applied; -D does not change the gates (review IMPL F10). Timing, routing and power: next phase.
# Flattened run = headline; hierarchical run = per-block breakdown (PLAN F17).
export PATH=~/tools/oss-cad-suite/bin:$PATH
cd "$(dirname "$0")"
set -e
LIB=~/tools/pdk/nangate45/NangateOpenCellLibrary_typical.lib
S="../src/pu_pkg.sv ../src/pu_cmp_seg.sv ../src/pu_cfg.sv ../src/pu_filter.sv ../src/pu_slot.sv ../src/pu_join.sv ../src/pu.sv"
ABC="abc -liberty $LIB -constr abc.constr -D 2284"
rm -rf out; mkdir -p out
for cfg in "filter 0 0" "join 1 0" "all 1 1"; do
  set -- $cfg
  for xr in 1 0; do
    tag=$1_x$xr
    yosys -m slang -q -l out/$tag.flat.log -p "read_liberty -lib $LIB; read_slang $S --top pu -G HAS_JOIN=$2 -G HAS_SETSEL=$3 -G HAS_XREG=$xr;
      synth -top pu -flatten; check -assert; dfflibmap -liberty $LIB; $ABC; opt_clean;
      check -assert; tee -o out/$tag.flat.stat stat -liberty $LIB; write_verilog -noattr out/$tag.flat.v;
      delete t:DFF*; tee -o out/$tag.flat.ltp ltp"
    if grep -q "Detected loop" out/$tag.flat.ltp; then echo "ltp walked through a loop: $tag"; exit 1; fi
    yosys -m slang -q -l out/$tag.hier.log -p "read_liberty -lib $LIB; read_slang $S --keep-hierarchy --top pu -G HAS_JOIN=$2 -G HAS_SETSEL=$3 -G HAS_XREG=$xr;
      synth -top pu; check -assert; dfflibmap -liberty $LIB; $ABC; opt_clean; check -assert;
      tee -o out/$tag.hier.stat stat -liberty $LIB"
  done
done
# per-channel decoder
yosys -m slang -q -l out/decoder.log -p "read_liberty -lib $LIB; read_slang ../src/pu_pkg.sv ../src/pu_decoder.sv --top pu_decoder;
  synth -top pu_decoder -flatten; check -assert; dfflibmap -liberty $LIB; $ABC; opt_clean; check -assert;
  tee -o out/decoder.stat stat -liberty $LIB"
# summary
printf "%-10s %10s %8s %6s %6s %6s\n" config area_um2 gate_eq flops bufs depth
for f in out/*.flat.stat; do
  t=$(basename $f .flat.stat)
  a=$(grep "Chip area" $f | awk '{print $NF}')
  ff=$(awk '/DFF_X1/{print $1}' $f); ff=${ff:-0}
  bf=$(awk '/BUF_X/{s+=$1} END{print s+0}' $f)
  d=$(grep -o "length=[0-9]*" out/$t.flat.ltp | cut -d= -f2)
  printf "%-10s %10.0f %8.0f %6s %6s %6s\n" $t $a $(echo "$a/0.798" | bc -l) $ff $bf $d
done | tee out/summary.txt
a=$(grep "Chip area" out/decoder.stat | awk '{print $NF}'); echo "decoder area $a um2 = $(echo "$a/0.798" | bc -l | cut -c1-6) gate-eq" | tee -a out/summary.txt
