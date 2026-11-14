"""Q1 at SF10 (results/q1/, older single-file layout, no nsys sqlite): the final merge group-by -> ORDER BY chain.

Source: q1_warm_kernel_list.json (ncu list pass: gpu__time_duration = ncu serialized time, NOT real clock) and
ncu_q1_groupby_full.json (full metrics for the group-by family only; joined on kernel id where present).
The last group-by is the merge of the per-batch partials: everything after the last `concat` run that precedes the
last single_pass_shmem_aggs_kernel. The sort side starts at the first sort kernel after it.
Writes q1_sf10_groupby_sort.json.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify  # noqa: E402

R = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q1"
K = json.load(open(f"{R}/q1_warm_kernel_list.json"))
F = {k["id"]: k for k in json.load(open(f"{R}/ncu_q1_groupby_full.json"))["kernels"]}
for k in K:
    k["sub"] = classify.sub_op(k["name"])
    k["ncu_ns"] = k["gpu__time_duration.sum"]
last_agg = max(i for i, k in enumerate(K) if "shmem_aggs" in k["name"])
j = last_agg
while j > 0 and K[j - 1]["sub"] != "concat":
    j -= 1
while j > 0 and K[j - 1]["sub"] == "concat":
    j -= 1
first_sort = min(i for i, k in enumerate(K) if i > last_agg and k["sub"] == "sort")
sort_start = first_sort - 1 if K[first_sort - 1]["sub"] == "fill" else first_sort
merge_gb = K[j:sort_start]
gb_core = [k for k in merge_gb if k["sub"] not in ("expr_cast", "expr_binop", "expr_ast", "fill")]
proj = [k for k in K[last_agg + 1:first_sort] if k["sub"] in ("expr_cast", "expr_binop", "expr_ast")]
sort_side = K[sort_start:]
full = lambda ks, f: sum((F.get(k["id"]) or {}).get(f, 0) or 0 for k in ks)
out = {
    "total_warm_kernels": len(K), "total_ncu_us": sum(k["ncu_ns"] for k in K) / 1e3,
    "groups_into_sort": 4, "rows_scanned": 59986052,
    "merge_groupby_kernels_incl_concat_and_finalize": len(merge_gb), "merge_groupby_ncu_us": sum(k["ncu_ns"] for k in merge_gb) / 1e3,
    "merge_groupby_subs": [k["sub"] for k in merge_gb],
    "finalize_projection_kernels": len(proj), "finalize_projection_ncu_us": sum(k["ncu_ns"] for k in proj) / 1e3,
    "sort_side_kernels": len(sort_side), "sort_side_ncu_us": sum(k["ncu_ns"] for k in sort_side) / 1e3,
    "sort_kernel_ncu_us": sum(k["ncu_ns"] for k in sort_side if k["sub"] == "sort") / 1e3,
    "sort_side_subs": [k["sub"] for k in sort_side],
    "merge_groupby_grids": sorted({k["launch__grid_size"] for k in merge_gb}),
    "sort_side_grids": sorted({k["launch__grid_size"] for k in sort_side}),
    "full_metrics_available_for": [k["id"] for k in merge_gb + sort_side if k["id"] in F],
    "merge_gb_dram_rd_B_where_available": full(merge_gb, "dram_rd"),
    "note": "durations are ncu (serialized, clock-locked, L2 flushed); intermediate = 4 groups x ~10 columns (< 1 KB, inferred)",
}
json.dump(out, open(f"{HERE}/q1_sf10_groupby_sort.json", "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if not k.endswith("subs")}, indent=1))
print("merge gb:", " ".join(out["merge_groupby_subs"]))
print("sort side:", " ".join(out["sort_side_subs"]))
