#!/bin/bash
# RTL tests: every vector set on the matching configuration(s), with Icarus (4-state) and Verilator (2-state), plus
# the channel test (decoder + 16 PUs). Rebuilds from scratch, shows compiler errors, and exits non-zero unless every
# run prints a RESULT line with 0 errors.
export PATH=~/tools/oss-cad-suite/bin:$PATH
cd "$(dirname "$0")"
S="../src/pu_pkg.sv ../src/pu_cmp_seg.sv ../src/pu_cfg.sv ../src/pu_filter.sv ../src/pu_slot.sv ../src/pu_join.sv ../src/pu.sv"
B=build; rm -rf $B; mkdir -p $B
LOG=$B/results.txt; : > $LOG
EXPECT=0
sim() {  # top tag join setsel xreg vec
  local top=$1 tag=$2_j$3s$4x$5 D="" src="$S"
  [ "$3" = 0 ] && D="-DNO_JOIN_STATE"
  [ "$top" = tb_chan ] && src="$S ../src/pu_decoder.sv"
  EXPECT=$((EXPECT + 2))
  if iverilog -g2012 $D -o $B/$tag.vvp -s $top -P $top.HAS_JOIN=$3 -P $top.HAS_SETSEL=$4 -P $top.HAS_XREG=$5 \
       $src $top.sv 2> $B/$tag.icarus.err; then
    vvp -n $B/$tag.vvp +VEC=vec/$6 | grep -E "RESULT|mismatch|transparent" | sed "s/^/[icarus $tag] /" | tee -a $LOG
  else grep -v "sorry: constant selects" $B/$tag.icarus.err | head -5; fi
  if verilator --binary $D -Wno-fatal -Wno-lint -Wno-style --top-module $top -GHAS_JOIN=$3 -GHAS_SETSEL=$4 \
       -GHAS_XREG=$5 --Mdir $B/v_$tag -o vtb $src $top.sv > $B/$tag.verilator.log 2>&1; then
    $B/v_$tag/vtb +VEC=vec/$6 | grep -E "RESULT|mismatch|transparent" | sed "s/^/[verilator $tag] /" | tee -a $LOG
  else grep -E "%Error" $B/$tag.verilator.log | head -5; fi
  rm -rf $B/v_$tag/*.o $B/v_$tag/*.cpp
}
sim tb_pu all 1 1 1 rand_all
sim tb_pu all 1 1 0 rand_all
sim tb_pu nosel 1 0 1 rand_nosel
sim tb_pu nosel 1 0 0 rand_nosel
sim tb_pu filter 0 0 1 rand_filter
sim tb_pu filter 0 0 0 rand_filter
sim tb_pu q6f 0 0 1 replay_q6
sim tb_pu q6 1 1 1 replay_q6
sim tb_pu q12la 1 1 1 replay_q12la
sim tb_pu q19la 1 1 1 replay_q19la
sim tb_pu q19laf 0 0 1 replay_q19la
sim tb_pu q12join 1 0 1 replay_q12join
sim tb_chan chan_all 1 1 1 rand_all
sim tb_chan chan_all 1 1 0 rand_all
sim tb_chan chan_join 1 0 1 replay_q12join
sim tb_chan chan_filter 0 0 1 rand_filter
PASS=$(grep -c "RESULT.* 0 errors" $LOG)
echo "== $PASS of $EXPECT runs passed"
[ "$PASS" = "$EXPECT" ]
