#!/usr/bin/env bash
# Rebuild and rerun the whole Vortex baseline (CPU only; ~45 min on 32 cores, mostly the SF 0.1/1 chains).
#   sim/scripts/run_vortex_baseline.sh            # everything
#   STEPS="results" sim/scripts/run_vortex_baseline.sh   # only re-aggregate existing runs
set -euo pipefail
S=/home/sai/cs254_project/sim
T=$S/vortex_baseline
PY=/home/sai/aimdb/.venv/bin/python          # numpy + duckdb (read-only use)
STEPS=${STEPS:-"setup data hosts calib suite results"}
for step in $STEPS; do
  case $step in
    setup)  $S/scripts/setup_vortex.sh                                   # submodules, patches, third_party, S1, S4
            for v in "S1_1ch7000 PLATFORM_MEMORY_NUM_BANKS=1 PLATFORM_MEMORY_DATA_RATE=7000" "S1_w16 NUM_WARPS=16" \
                     "S1_w64 NUM_WARPS=64" "S1_c2 NUM_CORES=2 L2_NUM_BANKS=2" "S1_nowv CACHE_WRITE_VALIDATE=0"; do
              python3 $T/scripts/mkvariant.py S1 $v
            done
            $S/scripts/setup_vortex.sh S1_1ch7000 S1_w16 S1_w64 S1_c2 S1_nowv ;;
    data)   $PY -I $T/scripts/gen_data.py 0.01 0.1 1 ;;
    hosts)  $T/scripts/build_hosts.sh ;;
    calib)  rm -rf $T/runs/membw $T/runs/lat; $T/scripts/run_calibration.sh; python3 $T/scripts/calibration.py ;;
    suite)  python3 $T/scripts/run_suite.py --force --jobs 28 ;;
    results) $PY $T/scripts/verify.py
             python3 $T/scripts/chain_mapping.py
             python3 $T/scripts/results.py
             python3 $T/scripts/compare_owner.py ;;
  esac
done
