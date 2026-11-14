#!/usr/bin/env bash
# Run a command inside the Ubuntu 22.04 Vortex container (localhost/vortex-dev:22.04) as the calling user.
#   sim/scripts/vx.sh '<command>'            (working dir = $VX_WORKDIR or $PWD)
# Mounts: the project tree read-write; the owner's ~/pim, ~/aimdb and the prebuilt toolchain ~/tools READ-ONLY.
# HOME, XDG_CACHE_HOME and POCL_CACHE_DIR default into sim/vortex_baseline/.cache so PoCL's kernel cache stays in
# the project. Parallel runs should each pass their own POCL_CACHE_DIR (env VX_POCL_CACHE) to avoid races.
P=/home/sai/cs254_project
C=${VX_CACHE:-$P/sim/vortex_baseline/.cache}
mkdir -p "$C/home" "$C/pocl" "$C/ccache"
exec podman run --rm --security-opt label=disable --userns=keep-id --user "$(id -u):$(id -g)" \
  -v $P:$P -v /home/sai/tools:/home/sai/tools:ro -v /home/sai/pim:/home/sai/pim:ro -v /home/sai/aimdb:/home/sai/aimdb:ro \
  -e HOME=$C/home -e XDG_CACHE_HOME=$C -e CCACHE_DIR=$C/ccache -e GIT_OPTIONAL_LOCKS=0 \
  -e POCL_CACHE_DIR="${VX_POCL_CACHE:-$C/pocl}" \
  -w "${VX_WORKDIR:-$PWD}" localhost/vortex-dev:22.04 bash -lc "$*"
