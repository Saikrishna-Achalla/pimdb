"""Sensitivity of the task segmentation (TASK_GAP_US) and placement statistics. Writes sensitivity.json."""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import chains  # noqa: E402

out = {}
for gap in (100, 300, 1000, 1e9):
    chains.TASK_GAP_US = gap
    tot = collections.Counter()
    for q in range(2, 23):
        A = chains.analyse(q)
        same = [e for e in A["E"] if e["kind"] == "same-thread"]
        tot["same_thread_step_edges"] += len(same)
        tot["roundtrip_B_same_thread"] += sum(e["roundtrip"] for e in same)
        tot["tasks"] += len({g["task"] for g in A["segs"]})
        tot["seg_edges_same_thread"] += sum(e["kind"] == "same-thread" for e in A["SE"])
        if gap == 300:
            K = A["D"]["kernels"]
            tot["kernels"] += len(K)
            tot["placed_by_name"] += sum(k["placed"] == "name" for k in K)
            tot["placed_by_context"] += sum(k["placed"] == "context" for k in K)
            tot["unplaced"] += sum(k["placed"] == "unplaced" for k in K)
            tot["placed_weak"] += sum(k["placed"] == "context_weak" for k in K)
            tot["kernel_ns"] += sum(k["dur"] for k in K)
            tot["kernel_ns_by_name"] += sum(k["dur"] for k in K if k["placed"] == "name")
            seg_of = {s["id"]: A["segs"][s["seg"]] for s in A["steps"]}
            for s in A["steps"]:
                g = seg_of[s["id"]]
                tot["launches_unique_plan_instance"] += s["launches"] * (g["plan_id"] is not None)
                tot["launches_no_plan_candidate"] += s["launches"] * (not g["plan_candidates"])
            tot["segments"] += len(A["segs"])
            tot["segments_isolated"] += sum(1 for g in A["segs"] if not any(e["src"] == g["id"] or e["dst"] == g["id"] for e in A["SE"]))
    out[str(gap)] = dict(tot)
    print(gap, dict(tot))
chains.TASK_GAP_US = 300
json.dump(out, open(f"{HERE}/sensitivity.json", "w"), indent=1)
