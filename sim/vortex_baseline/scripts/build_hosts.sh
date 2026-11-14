#!/usr/bin/env bash
# Build the OpenCL host programs (configuration-independent) into sim/vortex_baseline/bin/, inside the container.
set -euo pipefail
T=/home/sai/cs254_project/sim/vortex_baseline
CXX="g++ -O2 -std=c++17 -Wall -Wextra -Werror -I/home/sai/tools/pocl/include -DCL_TARGET_OPENCL_VERSION=120"
LIBS="-L/usr/lib/x86_64-linux-gnu -lOpenCL"
VX_WORKDIR=$T /home/sai/cs254_project/sim/scripts/vx.sh "
  $CXX tests/vx_membw/main.cc -o bin/vx_membw $LIBS &&
  $CXX tests/vx_latency/main.cc -o bin/vx_latency $LIBS &&
  { [ ! -f tests/dbops/host.cc ] || $CXX tests/dbops/host.cc -o bin/dbops $LIBS; }"
ls -l $T/bin
