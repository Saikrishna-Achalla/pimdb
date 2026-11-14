#!/usr/bin/env bash
# System CUDA 12.9 can't parse this host's glibc headers; build with Sirius's pixi CUDA 13.5 + conda gcc.
set -euo pipefail
cd "$(dirname "$0")"
P=/home/sai/cs254_project/sirius/.pixi/envs/default
PATH=$P/bin:$PATH "$P/bin/nvcc" -ccbin "$P/bin/x86_64-conda-linux-gnu-g++" \
  -O3 -std=c++17 -arch=sm_120 -lineinfo groupby_unroll_bench.cu -o groupby_unroll_bench
