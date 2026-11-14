#!/usr/bin/env bash
# Driver: SF10 main (sql timing pcie selftest), SF1 control with the same yaml, SF10 with SF1-pipeline batch sizes (b77),
# and Q1 at SF1 with the original SF1 pipeline yaml (no SF1 pipeline result exists for Q1). Sequential; each GPU
# process takes the shared GPU lock inside profile_query.sh.
P="$(cd "$(dirname "$0")" && pwd)"; E=$(dirname "$P")
QS=${QS:-"1 3 6 9 10 13 16 18"}
for n in $QS; do
  mkdir -p $E/q$n
  SF=10 CFG=main "$P/profile_query.sh" $n sql timing pcie selftest > $E/q$n/pipeline_run.log 2>&1; echo "q$n sf10 main exit $?"
done
for n in $QS; do
  mkdir -p $E/q$n/sf1_main
  SF=1 CFG=main "$P/profile_query.sh" $n sql timing pcie > $E/q$n/sf1_main/pipeline_run.log 2>&1; echo "q$n sf1 main exit $?"
  mkdir -p $E/q$n/sf10_b77
  SF=10 CFG=b77 "$P/profile_query.sh" $n sql timing pcie > $E/q$n/sf10_b77/pipeline_run.log 2>&1; echo "q$n sf10 b77 exit $?"
done
mkdir -p $E/q1/sf1_sf1pipe
SF=1 CFG=sf1pipe "$P/profile_query.sh" 1 sql timing pcie > $E/q1/sf1_sf1pipe/pipeline_run.log 2>&1; echo "q1 sf1 sf1pipe exit $?"
