#!/usr/bin/env bash
# ncu --set full on the top-3 families (per ncu_families_plan.json) of the SF10 main runs of Q3, Q9, Q18, Q16 (Q6 done first).
E=/home/sai/cs254_project/pim_exploration/sf10_scaling
for n in ${QS:-3 9 18 16}; do
  $E/scripts/ncu_families.sh $n $E/q$n $E/scripts/sirius.yaml /home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf10 > $E/q$n/ncu_families_run.log 2>&1
  echo "q$n ncu exit $?"
done
