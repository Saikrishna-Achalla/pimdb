#!/usr/bin/env bash
# Project-owned Vortex (simx + OpenCL/PoCL) build for the scaled-down RTX 5070 baseline.
#
#   sim/scripts/setup_vortex.sh                 # init submodules, apply patches, build third_party, build S1 and S4
#   sim/scripts/setup_vortex.sh S1 S1_w64 ...   # (re)build only the named configurations
#
# A configuration is sim/vortex_baseline/configs/<name>.json (calibration variants: configs/calib/<name>.json).
# It is symlinked into sim/vortex/profiles/ (untracked) and built in sim/vortex/build64-<name>/ (untracked).
# All VX_CFG_* knobs are compile-time in simx, so each configuration has its own build directory.
# Each build directory also gets vx_run_env.txt: the environment `make run-simx` would use (PoCL compile
# flags carrying that configuration's -DVX_CFG_*, library paths), read by sim/scripts/run_vortex.sh.
# Everything runs inside localhost/vortex-dev:22.04 through sim/scripts/vx.sh (toolchain in ~/tools, read-only).
set -euo pipefail
S=/home/sai/cs254_project/sim
V=$S/vortex
PATCHES=$S/patches/vortex
VX=$S/scripts/vx.sh
LOG=$S/vortex_baseline/logs
mkdir -p "$LOG"
export GIT_OPTIONAL_LOCKS=0

init_and_patch() {
  git -C "$V" submodule update --init --recursive
  # Vortex tree patches (owner's DRAM knobs + project patches), idempotent.
  for p in vortex_dram_knobs.patch vortex_cs254_model.patch; do
    if git -C "$V" apply --reverse --check "$PATCHES/$p" 2>/dev/null; then
      echo "already applied: $p"
    else
      git -C "$V" apply "$PATCHES/$p" && echo "applied: $p"
    fi
  done
  # Ramulator2 submodule patch (owner's controller queue-size knob).
  p=ramulator_queue_size.patch
  if git -C "$V/third_party/ramulator" apply --reverse --check "$PATCHES/$p" 2>/dev/null; then
    echo "already applied: $p"
  else
    git -C "$V/third_party/ramulator" apply "$PATCHES/$p" && echo "applied: $p"
  fi
}

build_third_party() {
  mkdir -p "$V/build64-S1"
  link_profile S1
  (cd "$V/build64-S1" && VX_WORKDIR=$PWD $VX '../configure --xlen=64 --tooldir=/home/sai/tools --profile=S1')
  # Serial: the ramulator_ext object needs the headers Ramulator's cmake fetches first.
  VX_WORKDIR=$V/build64-S1 $VX 'make third_party' > "$LOG/build_third_party.log" 2>&1
}

link_profile() {   # profiles/<name>.json -> the project's config file
  local n=$1 f
  if [ -f "$S/vortex_baseline/configs/$n.json" ]; then f=../../vortex_baseline/configs/$n.json
  elif [ -f "$S/vortex_baseline/configs/calib/$n.json" ]; then f=../../vortex_baseline/configs/calib/$n.json
  else echo "no config $n" >&2; exit 1; fi
  ln -sfn "$f" "$V/profiles/$n.json"
}

build_config() {
  local n=$1 B=$V/build64-$1
  link_profile "$n"
  mkdir -p "$B"
  VX_WORKDIR=$B $VX "../configure --xlen=64 --tooldir=/home/sai/tools --profile=$n && \
     make -C sw/kernel -j8 && make -C sw/runtime/stub -j8 && make -C sw/runtime/simx -j8" > "$LOG/build_$n.log" 2>&1
  # Capture the run environment (everything make run-simx puts before the binary).
  VX_WORKDIR=$B/tests/opencl/vecadd $VX 'make -n run-simx OPTS=@@OPTS@@ 2>/dev/null | grep "VORTEX_DRIVER=simx"' \
    | sed -e 's| VORTEX_DRIVER=simx ./vecadd @@OPTS@@||' > "$B/vx_run_env.txt"
  test -s "$B/vx_run_env.txt"
  echo "built $n -> $B"
}

if [ $# -eq 0 ]; then
  init_and_patch
  build_third_party
  set -- S1 S4
fi
for n in "$@"; do build_config "$n"; done
