#!/usr/bin/env bash
# Regenerate sim/patches/vortex/*.patch from the working tree of sim/vortex (maintainer tool).
# vortex_dram_knobs.patch and ramulator_queue_size.patch are the owner's (copied from ~/aimdb/vortex/patches,
# never regenerated). The project changes are diffed against "upstream + owner patch":
#   vortex_cs254_model.patch : launch log + DRAM drain (processor.cpp, memory.*, dram_sim.*),
#                              L2 write-validate + hashed cache sets (cache.cpp), their knobs (VX_config.toml)
set -euo pipefail
S=/home/sai/cs254_project/sim; V=$S/vortex; P=$S/patches/vortex
export GIT_OPTIONAL_LOCKS=0
tmp=$(mktemp -d)
files=$(git -C $V diff --name-only --ignore-submodules)
for f in $files; do mkdir -p $tmp/a/$(dirname $f); git -C $V show HEAD:$f > $tmp/a/$f; done
(cd $tmp/a && git apply --include='*' $P/vortex_dram_knobs.patch 2>/dev/null || patch -s -p1 < $P/vortex_dram_knobs.patch)
out=$P/vortex_cs254_model.patch; : > $out
for f in $files; do
  (cd $tmp && diff -u --label a/$f --label b/$f a/$f $V/$f >> $out) || true
done
rm -rf $tmp
echo "wrote $out ($(grep -c '^+++' $out) files)"
