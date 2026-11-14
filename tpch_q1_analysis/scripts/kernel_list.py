"""Parse ncu --csv kernel list; report the kernels of the last N launches (the warm profiled query)."""
import csv, sys, json, collections, re
path, skip = sys.argv[1], int(sys.argv[2])
rows = [l for l in open(path) if l.startswith('"')]
rd = csv.DictReader(rows)
k = collections.OrderedDict()
for r in rd:
    i = int(r["ID"]); d = k.setdefault(i, {"name": r["Kernel Name"], "id": i})
    d[r["Metric Name"]] = float(r["Metric Value"].replace(",", "")) if r["Metric Value"] else 0
ks = [v for i, v in k.items() if i >= skip]
def short(n):
    n = re.sub(r"\(.*", "", n); return n.split("::")[-1].split("<")[0] if "<" not in n.split("::")[-1] else n.split("<")[0].split("::")[-1]
tot = sum(x["gpu__time_duration.sum"] for x in ks)
agg = collections.defaultdict(lambda: [0, 0.0])
for x in ks:
    a = agg[short(x["name"])]; a[0] += 1; a[1] += x["gpu__time_duration.sum"]
print(f"kernels={len(ks)} total_gpu_time_us={tot/1e3:.1f}")
print(f"{'kernel':45s} {'count':>5s} {'total_us':>9s} {'pct':>6s} {'avg_us':>8s}")
for n, (c, t) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
    print(f"{n[:45]:45s} {c:5d} {t/1e3:9.1f} {100*t/tot:6.1f} {t/c/1e3:8.2f}")
durs = sorted(x["gpu__time_duration.sum"] for x in ks)
print("median_us", durs[len(durs)//2]/1e3, "kernels<5us", sum(d < 5000 for d in durs), "kernels<10us", sum(d < 10000 for d in durs))
json.dump(ks, open(sys.argv[3], "w"), indent=1)
