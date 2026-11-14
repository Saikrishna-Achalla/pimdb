#!/usr/bin/env bash
# Usage: run_sirius.sh <sql_file> <sirius_log_dir> [prefix command...]
# Runs the Sirius DuckDB CLI (in-memory DB) on a script with fallback to CPU disabled.
# Env vars go through /usr/bin/env so they survive a `sudo -n ncu ...` / `nsys profile` prefix.
# Stock libcudf from the pixi env (no LD_PRELOAD).
set -euo pipefail
SQL="$1"; LOGDIR="$2"; shift 2
SIRIUS=/home/sai/cs254_project/sirius
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$LOGDIR"; chmod 777 "$LOGDIR"   # root (sudo ncu) must be able to write here; user must delete later
rm -f "$LOGDIR"/*.log
exec "$@" /usr/bin/env SIRIUS_CONFIG_FILE="${SIRIUS_YAML:-$HERE/sirius.yaml}" SIRIUS_DISABLE=0 SIRIUS_LOG_DIR="$LOGDIR" \
  "$SIRIUS/sirius-duckdb/build/release/duckdb" -unsigned -bail -no-agent \
  -cmd "LOAD '$SIRIUS/sirius-duckdb/build/release/extension/sirius/sirius.duckdb_extension';" \
  -cmd "SET enable_duckdb_fallback = false;" < "$SQL"
