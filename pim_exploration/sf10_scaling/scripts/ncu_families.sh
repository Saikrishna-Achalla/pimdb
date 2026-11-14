#!/usr/bin/env bash
# Nsight Compute --set full on the warm iteration (iteration 5 of the pin+5 SQL), one run per kernel family listed in
# <results_dir>/ncu_families_plan.json (ncu_plan_families.py). Same ncu invocation style as the tpch_sf1 pipeline
# (sudo -n /usr/local/cuda/bin/ncu, --set full --import-source yes, -k regex: -s -c), under the shared GPU lock.
# Usage: ncu_families.sh <N> <results_dir> <sirius.yaml> <parquet_dir>
set -euo pipefail
N=$1; R=$2; Y=$3; PQDIR=$4
P="$(cd "$(dirname "$0")" && pwd)"
PY="/home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I"
export SIRIUS_YAML=$Y TPCH_PARQUET_DIR=$PQDIR
mkdir -p "$R/profiles"
while read -r F RX SKIP COUNT; do
  rm -f "$R/profiles/q${N}_warm_fam_${F}.ncu-rep"; rm -rf "$R/traces/sirius_log_ncu_fam_${F}"
  echo "[$(date +%T)] q$N ncu --set full -k regex:$RX -s $SKIP -c $COUNT"; T0=$SECONDS
  flock /home/sai/cs254_project/pim_exploration/.gpu.lock "$P/run_sirius.sh" "$R/sql/q${N}_ncu_x5.sql" "$R/traces/sirius_log_ncu_fam_${F}" \
    sudo -n /usr/local/cuda/bin/ncu --set full --import-source yes -k "regex:$RX" -s "$SKIP" -c "$COUNT" \
    -o "$R/profiles/q${N}_warm_fam_${F}" -f > "$R/traces/ncu_fam_${F}.log" 2>&1
  echo "[$(date +%T)] q$N $F done in $((SECONDS - T0)) s"
done < <($PY -c "import json;p=json.load(open('$R/ncu_families_plan.json'));[print(r['func'],r['regex'],r['skip'],r['count']) for r in p['runs']]")
$PY "$P/ncu_extract_families.py" "$R" "$N" | tee "$R/ncu_families_summary.txt"
