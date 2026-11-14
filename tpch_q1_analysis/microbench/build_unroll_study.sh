#!/usr/bin/env bash
# Same toolchain/flags as build.sh (Sirius pixi CUDA 13.5 + conda gcc), for unroll_study.cu.
set -euo pipefail
cd "$(dirname "$0")"
P=/home/sai/cs254_project/sirius/.pixi/envs/default
PATH=$P/bin:$PATH "$P/bin/nvcc" -ccbin "$P/bin/x86_64-conda-linux-gnu-g++" \
  -O3 -std=c++17 -arch=sm_120 -lineinfo unroll_study.cu -o unroll_study
