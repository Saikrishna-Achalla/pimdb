"""Where does a warm iteration's wall time go? (nsys CUDA trace, unserialized, real clocks)

Usage: python3 -I nsys_breakdown.py <results_dir>   (needs pcie.json + traces/q<N>_nsys.sqlite + traces/sirius_log_nsys)
For each measured iteration (Sirius log windows, as in pcie_verify.py):
  - engine window (Sirius `QueryBegin: transparent_execution` -> `QueryEnd`)
  - GPU busy = union of kernel/memcpy/memset intervals; GPU idle inside the engine window
  - first->last GPU activity span, number of kernels / copies
  - CUDA runtime API calls: count and total CPU time by function (launches, syncs, allocs, copies)
Writes nsys_iteration_breakdown.txt/.json.
"""
import collections, glob, json, os, re, sqlite3, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog

R = sys.argv[1]
c = sqlite3.connect(glob.glob(f"{R}/traces/q*_nsys.sqlite")[0])
t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
ts = lambda l: siriuslog.ts_ms(l) * 1e6 - t0
P = json.load(open(f"{R}/pcie.json")); nwarm = sum(not p["measured"] for p in P["per_iteration"])
L, _ = siriuslog.read_run(f"{R}/traces/sirius_log_nsys")
qb, tb, qe = [], [], []
for l in L:
    sql = siriuslog.sql_of(l)
    if sql is not None:
        if not sql.lower().startswith(siriuslog.DDL):
            qb.append(ts(l))
    elif "QueryBegin: transparent_execution" in l:
        tb.append(ts(l))
    elif l.endswith("QueryEnd") and "sirius_context" in l and len(qe) < len(tb):
        qe.append(ts(l))
names = dict(c.execute("select id, value from StringIds"))
gpu = sorted([(s, e) for s, e in c.execute("select start, end from CUPTI_ACTIVITY_KIND_KERNEL")] +
             [(s, e) for s, e in c.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMCPY")] +
             [(s, e) for s, e in c.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMSET")])
kern = [s for (s,) in c.execute("select start from CUPTI_ACTIVITY_KIND_KERNEL")]
kfull = c.execute("select k.start, k.end, s.value from CUPTI_ACTIVITY_KIND_KERNEL k join StringIds s on k.shortName = s.id").fetchall()
api = [(s, e, names.get(n, "?")) for s, e, n in c.execute("select start, end, nameId from CUPTI_ACTIVITY_KIND_RUNTIME")]


def by_name(lo, hi):
    d = collections.Counter()
    for s, e, n in kfull:
        if lo <= s < hi:
            d[n] += e - s
    return dict(d)


def union(iv, lo, hi):
    tot, cur_s, cur_e = 0, None, None
    for s, e in iv:
        s, e = max(s, lo), min(e, hi)
        if e <= s:
            continue
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                tot += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    return tot + ((cur_e - cur_s) if cur_e is not None else 0)


rows = []
for i in range(len(qb)):
    if i < nwarm or i >= len(tb) or i >= len(qe):
        continue
    lo, hi = tb[i] - 1e6, qe[i] + 1e6  # engine window, +-1 ms for log resolution
    act = [(s, e) for s, e in gpu if lo <= s < hi]
    busy = union(act, lo, hi)
    a = collections.defaultdict(lambda: [0, 0.0])
    for s, e, n in api:
        if lo <= s < hi:
            x = a[re.sub(r"_v\d+$", "", n)]; x[0] += 1; x[1] += e - s
    rows.append({"iter": i + 1, "planning_ms": (tb[i] - qb[i]) / 1e6, "engine_ms": (qe[i] - tb[i]) / 1e6,
                 "gpu_busy_ms": busy / 1e6, "gpu_span_ms": ((max(e for _, e in act) - min(s for s, _ in act)) / 1e6) if act else 0,
                 "kernels": sum(lo <= s < hi for s in kern), "gpu_ops": len(act),
                 "kernel_ns_by_name": by_name(lo, hi),
                 "api": {k: {"calls": v[0], "cpu_ms": v[1] / 1e6} for k, v in a.items()}})
json.dump(rows, open(f"{R}/nsys_iteration_breakdown.json", "w"), indent=1)
med = lambda k: statistics.median(r[k] for r in rows)
with open(f"{R}/nsys_iteration_breakdown.txt", "w") as f:
    f.write(f"nsys (CUDA trace, unserialized, boost clocks), measured iterations {[r['iter'] for r in rows]} of the nsys run\n")
    f.write("iter planning_ms engine_ms gpu_busy_ms gpu_span_ms kernels gpu_ops\n")
    for r in rows:
        f.write(f"{r['iter']:4d} {r['planning_ms']:11.1f} {r['engine_ms']:9.1f} {r['gpu_busy_ms']:11.3f} {r['gpu_span_ms']:11.2f} {r['kernels']:7d} {r['gpu_ops']:7d}\n")
    f.write(f"median: planning {med('planning_ms'):.1f} ms, engine {med('engine_ms'):.1f} ms, GPU busy {med('gpu_busy_ms'):.3f} ms "
            f"({100*med('gpu_busy_ms')/med('engine_ms'):.0f}% of the engine window), first->last GPU op {med('gpu_span_ms'):.2f} ms\n")
    f.write("(planning/engine from 1 ms Sirius log stamps; GPU busy = union of kernel+memcpy+memset intervals)\n\n")
    tot = collections.defaultdict(lambda: [0, 0.0])
    for r in rows:
        for k, v in r["api"].items():
            tot[k][0] += v["calls"]; tot[k][1] += v["cpu_ms"]
    f.write(f"CUDA runtime API per measured iteration (mean over {len(rows)}): calls, CPU ms (all threads, summed)\n")
    for k, (n, t) in sorted(tot.items(), key=lambda kv: -kv[1][1])[:15]:
        f.write(f"  {k:40s} {n/len(rows):7.1f} {t/len(rows):8.3f}\n")
    fam = collections.Counter()
    for r in rows:
        fam.update(r["kernel_ns_by_name"])
    ktot = sum(fam.values()) or 1
    f.write(f"\nkernel time by name at real clocks (nsys, mean per measured iteration; total {ktot/len(rows)/1e3:.1f} us of kernels):\n")
    for k, v in fam.most_common(12):
        f.write(f"  {k[:45]:45s} {v/len(rows)/1e3:8.1f} us {100*v/ktot:5.1f}%\n")
print(open(f"{R}/nsys_iteration_breakdown.txt").read())
