#!/usr/bin/env bash
# Writes q1_groups.csv: the real TPC-H Q1 SF1 group id (0=AF 1=NF 2=NO 3=RF) of every row that passes
# Q1's filter, in table order -- i.e. what groupby::mapping_indices_kernel hands the aggregation kernel.
set -euo pipefail
cd "$(dirname "$0")"
D=/home/sai/cs254_project/sirius/sirius-duckdb/build/release/duckdb
PQ=/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1
files=$( (ls "$PQ"/lineitem*.parquet "$PQ"/lineitem/*.parquet 2>/dev/null || true) | sed "s/.*/'&'/" | paste -sd,)
"$D" -no-agent -c "COPY (SELECT CASE l_returnflag||l_linestatus WHEN 'AF' THEN 0 WHEN 'NF' THEN 1 WHEN 'NO' THEN 2 ELSE 3 END
  FROM read_parquet([$files]) WHERE l_shipdate <= date '1995-08-19') TO 'q1_groups.csv' (HEADER false);"
wc -l q1_groups.csv
