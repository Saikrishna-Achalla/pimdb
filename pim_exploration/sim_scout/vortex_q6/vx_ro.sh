#!/usr/bin/env bash
# Like ~/aimdb/vortex/vx.sh, but the owner's trees are mounted READ-ONLY; only sim_scout is writable.
# HOME, XDG_CACHE_HOME and POCL_CACHE_DIR point into sim_scout so PoCL's kernel cache lands here.
S=/home/sai/cs254_project/pim_exploration/sim_scout
exec podman run --rm --security-opt label=disable --userns=keep-id --user "$(id -u):$(id -g)" \
  -v /home/sai/pim:/home/sai/pim:ro -v /home/sai/aimdb:/home/sai/aimdb:ro -v /home/sai/tools:/home/sai/tools:ro \
  -v $S:$S -e HOME=$S/vortex_q6/home -e XDG_CACHE_HOME=$S/vortex_q6/cache -e POCL_CACHE_DIR=$S/vortex_q6/cache/pocl \
  -w "${VX_WORKDIR:-$S/vortex_q6}" localhost/vortex-dev:22.04 bash -lc "$*"
