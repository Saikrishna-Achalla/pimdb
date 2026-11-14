#!/usr/bin/env bash
# Runs the Part B set: Q6 Q3 Q9 Q18 x {plain, cudatrace, cpu}, 3 warm-up + 150 measured iterations each.
set -uo pipefail
H="$(cd "$(dirname "$0")" && pwd)"
for N in 6 3 9 18; do for M in plain cudatrace cpu; do
  echo "== q$N $M $(date +%T)"; "$H/run_partB.sh" "$N" "$M" 153
done; done
echo "ALL DONE $(date +%T)"
