#!/usr/bin/env bash
# Usage: make_q1_sql.sh <parquet_dir> <n_iterations> [pin] > out.sql
# Builds a DuckDB script: lineitem view, optional pin_table(tier='gpu') of Q1's 7 columns,
# .timer on, then Q1 N times (iteration 1 = cold).
set -euo pipefail
PQ="$1"; N="$2"; PIN="${3:-}"
Q1=/home/sai/cs254_project/sirius/test/tpch_performance/tpch_queries/orig/q1.sql
PINPY=/home/sai/cs254_project/sirius/test/tpch_performance/tpch_pin_columns.py
files=$( (ls "$PQ"/lineitem*.parquet "$PQ"/lineitem/*.parquet 2>/dev/null || true) | sed "s/.*/'&'/" | paste -sd,)
echo "CREATE VIEW lineitem AS SELECT * FROM read_parquet([$files]);"
if [ "$PIN" = "pin" ]; then
  echo ".print __PIN_BEGIN__"
  python3 -I "$PINPY" pin 1 "$PQ"
  echo ".print __PIN_END__"
fi
echo ".timer on"
for i in $(seq 1 "$N"); do echo ".print __ITER__ $i"; cat "$Q1"; echo; done
