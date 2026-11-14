#!/usr/bin/env bash
# Rerun every AiM-PIM result (CPU only, ~1 min): regression, spec, mapping, all workloads -> sim/aim_pim/results/
set -euo pipefail
cd "$(dirname "$0")/../aim_pim"
PY=/home/sai/aimdb/.venv/bin/python     # has duckdb + numpy (read-only use)
[ -x ../aim_simulator/build/ramulator2 ] || bash ../scripts/setup_aim.sh
$PY -B regress_owner_q6.py
$PY -B tools/write_isr_spec.py
$PY -B tools/write_mapping.py
$PY -B run_all.py --jobs "${JOBS:-16}"
