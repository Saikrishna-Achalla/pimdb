"""Finer, operator-level attribution of kernels by name (pinned Q1). Usage: operator_breakdown.py <ncu.json>"""
import json, sys, collections
K = json.load(open(sys.argv[1]))["kernels"]
def op(n):
    if "groupby" in n or "cuco" in n or "insert_and_find" in n: return "group-by: hash build + aggregate (cuDF)"
    if "strings::" in n or "string_offsets" in n: return "filter gather: string keys (returnflag, linestatus)"
    if "permutation_iterator" in n and "transform_kernel" in n: return "filter gather: fixed-width columns"
    if "binops::LessEqual" in n or "Select" in n or "Compact" in n: return "filter: predicate + select indices"
    if any(f"binops::{o}" in n for o in ("Sub", "Mul", "Add", "Div")): return "projection: price arithmetic (binary ops)"
    if "minmax" in n: return "min/max reductions (stats bounds)"
    if "merge_sort" in n or "Sort" in n: return "ORDER BY / merge sort"
    if "compute_column_kernel" in n: return "expression eval (AST)"
    if "Memcpy" in n or "concatenate" in n or "gather" in n: return "other copies/concat"
    return "other (fill, scan, misc)"
a = collections.defaultdict(lambda: [0, 0.0, 0.0])
for k in K:
    x = a[op(k["name"])]; x[0] += 1; x[1] += k["dur_ns"]; x[2] += k["dram_bytes"]
tot = sum(x[1] for x in a.values())
print(f"{'operator':52s} {'kernels':>7} {'time_us':>8} {'pct':>6} {'DRAM_MB':>8}")
for o, (n, t, b) in sorted(a.items(), key=lambda kv: -kv[1][1]):
    print(f"{o:52s} {n:7d} {t/1e3:8.1f} {100*t/tot:6.1f} {b/1e6:8.1f}")
