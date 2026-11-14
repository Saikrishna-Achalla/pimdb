"""Real-clock gap between consecutive same-thread sub-operator steps, by what the host does in between.
Reads dataflow_q*.json; writes gap_by_host.csv (kind, edges, median/mean/p90 gap us, total ms)."""
import collections, csv, glob, json, os, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))
G = collections.defaultdict(list)
for f in glob.glob(f"{HERE}/dataflow_q*.json"):
    for e in json.load(open(f))["edges_subop_level"]:
        if e["kind"] == "same-thread":
            G[e["host"]["kind"]].append(e["gap_us"])
            G["ALL"].append(e["gap_us"])
rows = []
for k, v in sorted(G.items(), key=lambda kv: -len(kv[1])):
    v.sort()
    rows.append({"host_between": k, "edges": len(v), "median_us": round(st.median(v), 1), "mean_us": round(st.mean(v), 1),
                 "p90_us": round(v[int(0.9 * (len(v) - 1))], 1), "total_ms": round(sum(v) / 1e3, 2)})
    print(rows[-1])
with open(f"{HERE}/gap_by_host.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
