#!/usr/bin/env bash
# Run scaling_extract.py on every run directory (CPU only), then scaling_compare.py.
E=/home/sai/cs254_project/pim_exploration/sf10_scaling; S=$E/scripts
PY="/home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I"
RES=/home/sai/cs254_project/tpch_q1_analysis/analysis/results
for n in 1 3 6 9 10 13 16 18; do
  $PY $S/scaling_extract.py $E/q$n $E/q$n/scaling_metrics.json "q$n sf10_main"
  for d in sf1_main sf10_b77 sf1_sf1pipe; do
    [ -f $E/q$n/$d/pcie.json ] && $PY $S/scaling_extract.py $E/q$n/$d $E/q$n/$d/scaling_metrics.json "q$n $d"
  done
  [ $n != 1 ] && $PY $S/scaling_extract.py $RES/q$n $E/q$n/sf1_pipeline_metrics.json "q$n sf1_pipeline(existing)"
done
$PY $S/scaling_compare.py
