#!/usr/bin/env bash
# ncu passes for TPC-H Q1 (SF from env, default 1) (GPU counters are admin-only; uses NOPASSWD sudo for ncu only).
# Usage: [SF=10] [RUN_TAG=_u4] [CUDF_PRELOAD=...] ncu_profile_q1.sh [pin]     (pin = lineitem pinned on GPU via pin_table tier='gpu')
#   Pass 1: kernel list for a 4-iteration run  -> count kernels before the profiled query
#   Pass 2: kernel list for a 5-iteration run  -> iteration 5 is the warm profiled query
#   Pass 3: --set full on ONLY iteration-5 kernels (launch-skip = pass-1 count)
# Pinning kernels run before iteration 1 in both passes, so they are skipped too.
set -euo pipefail
cd "$(dirname "$0")/.."
SF="${SF:-1}"; SFX=$([ "$SF" = 1 ] || echo _sf$SF)
MODE="${1:-}"; TAG=$([ "$MODE" = pin ] && echo pinned || echo unpinned)${RUN_TAG:-}${SFX}
NCU="sudo -n /usr/local/cuda/bin/ncu"
PQ=/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf$SF
./scripts/make_q1_sql.sh "$PQ" 4 $MODE > scripts/q1_${TAG}_x4.sql
export CUDF_PRELOAD="${CUDF_PRELOAD:-}"
./scripts/make_q1_sql.sh "$PQ" 5 $MODE > scripts/q1_${TAG}_x5.sql
METRICS=gpu__time_duration.sum,launch__grid_size,launch__block_size,launch__registers_per_thread

echo "== Pass 1"; ./scripts/run_q1.sh scripts/q1_${TAG}_x4.sql $NCU --metrics $METRICS --csv --print-units base > traces/ncu_list_${TAG}_x4.csv 2> traces/ncu_list_${TAG}_x4.err || true
echo "== Pass 2"; ./scripts/run_q1.sh scripts/q1_${TAG}_x5.sql $NCU --metrics $METRICS --csv --print-units base > traces/ncu_list_${TAG}_x5.csv 2> traces/ncu_list_${TAG}_x5.err || true
N4=$(grep -c '"gpu__time_duration.sum"' traces/ncu_list_${TAG}_x4.csv || true)
N5=$(grep -c '"gpu__time_duration.sum"' traces/ncu_list_${TAG}_x5.csv || true)
CNT=$((N5 - N4)); echo "kernels: 4 iters=$N4, 5 iters=$N5 -> profiling $CNT (skip $N4)"
[ "$N4" -gt 0 ] && [ "$CNT" -gt 0 ] || { echo "ERROR: kernel counting failed"; exit 1; }
echo "== Pass 3"; ./scripts/run_q1.sh scripts/q1_${TAG}_x5.sql $NCU --set full --import-source yes -s "$N4" -c "$CNT" -o profiles/q1_sf${SF}_${TAG%$SFX}_warm_full -f > traces/ncu_full_${TAG}_stdout.txt 2>&1 || true
echo "== DONE"; ls -la profiles/
