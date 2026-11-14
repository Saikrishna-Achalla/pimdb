#!/usr/bin/env bash
# Print Sirius's resolved batch-size settings for a given sirius.yaml (GPU process, run under the GPU lock).
# Usage: probe_settings.sh <sirius.yaml> > out.txt
set -euo pipefail
SIRIUS=/home/sai/cs254_project/sirius
L=$(mktemp -d)
flock /home/sai/cs254_project/pim_exploration/.gpu.lock /usr/bin/env SIRIUS_CONFIG_FILE="$1" SIRIUS_LOG_DIR="$L" \
  "$SIRIUS/sirius-duckdb/build/release/duckdb" -unsigned -bail -no-agent -csv \
  -cmd "LOAD '$SIRIUS/sirius-duckdb/build/release/extension/sirius/sirius.duckdb_extension';" \
  -c "SELECT name, value FROM duckdb_settings() WHERE name IN ('scan_task_batch_size','hash_partition_bytes','concat_batch_bytes','sort_sample_bytes','max_build_hash_table_bytes','max_build_probe_resident_bytes','max_sort_partition_bytes') ORDER BY name;"
echo "config: $1"
rm -rf "$L"
