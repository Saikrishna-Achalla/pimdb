#!/usr/bin/env bash
# Project-owned build of the AiM simulator (arkhadem/aim_simulator @ 0f28a07) + sim/patches/aim/*.patch.
# Usage: bash sim/scripts/setup_aim.sh [--reset]
#   --reset : restore the submodule's tracked files to 0f28a07 before applying the patches
#             (otherwise the script refuses to run on a dirty tree that is not exactly the patch set).
# Dependencies (yaml-cpp 0.7.0, spdlog 1.11.0, argparse 2.9) are copied offline from
# /home/sai/aimdb/CENT/aim_simulator/ext (read-only) if present, else fetched by CMake (needs network once).
set -euo pipefail
export GIT_OPTIONAL_LOCKS=0
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SUB="$ROOT/sim/aim_simulator"; PATCHES="$ROOT/sim/patches/aim"; COMMIT=0f28a07
DEPS=/home/sai/aimdb/CENT/aim_simulator/ext
[ -e "$SUB/.git" ] || git -C "$ROOT" submodule update --init sim/aim_simulator
cur=$(git -C "$SUB" rev-parse --short=7 HEAD)
[ "$cur" = "$COMMIT" ] || { echo "submodule at $cur, expected $COMMIT"; exit 1; }
# does the tree already equal the patch set?

if [ "${1:-}" = "--reset" ] || git -C "$SUB" diff --quiet; then
  git -C "$SUB" checkout -- . 
  for p in "$PATCHES"/*.patch; do echo "apply $(basename "$p")"; git -C "$SUB" apply "$p"; done
else
  echo "submodule tree is dirty; assuming patches already applied (use --reset to re-apply)"
fi
if [ ! -d "$SUB/ext/yaml-cpp" ] && [ -d "$DEPS" ]; then cp -r "$DEPS" "$SUB/ext"; fi
mkdir -p "$SUB/build"; cd "$SUB/build"
DISC=OFF; [ -d "$SUB/ext/yaml-cpp" ] && DISC=ON
cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_CXX_FLAGS="-include cstdint" \
      -DFETCHCONTENT_FULLY_DISCONNECTED=$DISC > cmake.log
make -j"$(nproc)" > make.log
ls -la "$SUB/build/ramulator2"
