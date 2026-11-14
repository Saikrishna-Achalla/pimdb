#!/usr/bin/env bash
# Usage: run_q1.sh <sql_file> [prefix command...]  -- runs Sirius DuckDB on the script.
# Env vars are passed through /usr/bin/env so they survive a `sudo -n ncu ...` prefix.
# CUDF_PRELOAD=/path/libcudf.so  -> load that libcudf instead of the pixi one (LD_PRELOAD; RPATH beats LD_LIBRARY_PATH).
set -euo pipefail
SQL="$1"; shift
SIRIUS=/home/sai/cs254_project/sirius
A=/home/sai/cs254_project/tpch_q1_analysis
PRE=(); [ -n "${CUDF_PRELOAD:-}" ] && PRE=(LD_PRELOAD="$CUDF_PRELOAD")
exec "$@" /usr/bin/env "${PRE[@]}" \
  SIRIUS_CONFIG_FILE="$A/scripts/sirius.yaml" SIRIUS_DISABLE=0 SIRIUS_LOG_DIR="${SIRIUS_LOG_DIR:-$A/traces/sirius_log}" \
  "$SIRIUS/sirius-duckdb/build/release/duckdb" -unsigned -bail \
  -cmd "LOAD '$SIRIUS/sirius-duckdb/build/release/extension/sirius/sirius.duckdb_extension';" \
  -cmd "SET enable_duckdb_fallback = false;" < "$SQL"
