#!/usr/bin/env bash
# Re-run every calibration attempt (stream and latency probes) in parallel; then: python3 calibration.py
set -euo pipefail
T=/home/sai/cs254_project/sim/vortex_baseline; R=$T/runs; RV=/home/sai/cs254_project/sim/scripts/run_vortex.sh
MB=$T/tests/vx_membw/kernel.cl; LT=$T/tests/vx_latency/kernel.cl
stream() { $RV $1 $R/membw/$2 $MB $T/bin/vx_membw -n $3 -i 1 -g $4 -l 256; }
lat()    { $RV $1 $R/lat/$1_n$2 $LT $T/bin/vx_latency -b 33554432 -s 4096 -n $2; }
stream S1 S1_g1024 524288 1024 & stream S1 S1_g4096 524288 4096 & stream S1 S1_16M_g1024 2097152 1024 &
stream S1_1ch7000 S1_1ch7000_16M 2097152 1024 & stream S1_w16 S1_w16_16M 2097152 512 & stream S1_w64 S1_w64_16M 2097152 2048 &
stream S4 S4_4M_g4096 524288 4096 & stream S4 S4_16M_g4096 2097152 4096 &
lat S1 256 & lat S1 1280 & lat S4 256 & lat S4 1280 &
wait
