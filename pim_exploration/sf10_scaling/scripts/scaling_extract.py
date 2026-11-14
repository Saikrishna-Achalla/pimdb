"""Per-run scaling metrics from one pipeline results directory (nsys trace + timing + pcie + Sirius logs).

Usage: venv/bin/python -I scaling_extract.py <results_dir> <out.json> [label]
Reads (read-only): <results_dir>/traces/q<N>_nsys.sqlite, traces/sirius_log_nsys, traces/sirius_log_timing,
                   timing.json, pcie.json, nsys_iteration_breakdown.json.
Iteration windows are built exactly as nsys_breakdown.py does (Sirius log `QueryBegin: transparent_execution` ->
`QueryEnd`, +-1 ms). For every measured iteration it records kernels / GPU ops / GPU-busy and, per kernel family
(function base name, kclass.func_base) and per phase (kclass.phase): launches and kernel ns at real clocks.
"Representative warm iteration" = the measured iteration with the median GPU-busy time.
Also: launches by grid size (< 48 CTAs = fewer CTAs than SMs), nsys duration classes (< 5 us, >= 100 us),
gpu_pool high-water before the first query (end of pin phase) and at the end of the run.
"""
import collections, glob, json, os, re, sqlite3, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog
from kclass import func_base, phase

R, OUT = sys.argv[1], sys.argv[2]
LABEL = sys.argv[3] if len(sys.argv) > 3 else R
db = glob.glob(f"{R}/traces/q*_nsys.sqlite")[0]
c = sqlite3.connect(db)
t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
ts = lambda l: siriuslog.ts_ms(l) * 1e6 - t0
P = json.load(open(f"{R}/pcie.json")); nwarm = sum(not p["measured"] for p in P["per_iteration"])
T = json.load(open(f"{R}/timing.json"))
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
S = dict(c.execute("select id, value from StringIds"))
K = [(s, e, S[d], gx * gy * gz, bx * by * bz) for s, e, d, gx, gy, gz, bx, by, bz in c.execute(
    "select start, end, demangledName, gridX, gridY, gridZ, blockX, blockY, blockZ from CUPTI_ACTIVITY_KIND_KERNEL")]
GPU = sorted([(s, e) for s, e, *_ in K] + list(c.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMCPY")) +
             list(c.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMSET")))
CL = {}  # cache classification per name


def cls(n):
    if n not in CL:
        CL[n] = (func_base(n), phase(n))
    return CL[n]


def union(iv, lo, hi):
    tot, cs, ce = 0, None, None
    for s, e in iv:
        s, e = max(s, lo), min(e, hi)
        if e <= s:
            continue
        if ce is None or s > ce:
            if ce is not None:
                tot += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return tot + ((ce - cs) if ce is not None else 0)


its = []
for i in range(len(qb)):
    if i < nwarm or i >= len(tb) or i >= len(qe):
        continue
    lo, hi = tb[i] - 1e6, qe[i] + 1e6
    ks = [k for k in K if lo <= k[0] < hi]
    act = [(s, e) for s, e in GPU if lo <= s < hi]
    fam = collections.defaultdict(lambda: {"launches": 0, "ns": 0, "phase": "", "grid_max": 0, "grid_min": 1 << 40})
    ph = collections.defaultdict(lambda: {"launches": 0, "ns": 0})
    for s, e, n, g, b in ks:
        f, p = cls(n)
        x = fam[f]; x["launches"] += 1; x["ns"] += e - s; x["phase"] = p
        x["grid_max"] = max(x["grid_max"], g); x["grid_min"] = min(x["grid_min"], g)
        y = ph[p]; y["launches"] += 1; y["ns"] += e - s
    durs = [e - s for s, e, *_ in ks]
    its.append({"iter": i + 1, "planning_ms": (tb[i] - qb[i]) / 1e6, "engine_ms": (qe[i] - tb[i]) / 1e6,
                "gpu_busy_ms": union(act, lo, hi) / 1e6, "kernels": len(ks), "gpu_ops": len(act),
                "kernel_ms": sum(durs) / 1e6,
                "lt5us": sum(d < 5000 for d in durs), "ge100us": sum(d >= 100000 for d in durs),
                "ge100us_ms": sum(d for d in durs if d >= 100000) / 1e6,
                "grid_lt48": sum(g < 48 for *_, g, b in ks), "grid_1": sum(g == 1 for *_, g, b in ks),
                "families": dict(fam), "phases": dict(ph)})
assert its, f"no measured iterations in {R}"
rep = sorted(its, key=lambda r: r["gpu_busy_ms"])[len(its) // 2]
# gpu_pool high-water: end of pin phase (last pin_table QueryEnd) vs end of run, timing-run log
tl, _ = siriuslog.read_run(f"{R}/traces/sirius_log_timing")
peaks, pin_end_peak, pinned = [], None, None
in_pin = False
for l in tl:
    s = siriuslog.sql_of(l)
    if s is not None:
        in_pin = "pin_table" in s.lower()
    m = re.search(r"\[gpu_pool\].*QueryEnd.*allocated=(\d+) bytes peak=(\d+)", l)
    if m:
        peaks.append(int(m.group(2)))
        if in_pin:
            pin_end_peak, pinned = int(m.group(2)), int(m.group(1))
med = lambda k: statistics.median(r[k] for r in its)
out = {"label": LABEL, "results_dir": R, "nsys_sqlite": db,
       "warm_ms": T["median_ms"], "warm_min_ms": T["min_ms"], "warm_max_ms": T["max_ms"], "timed": len(T["timed_ms"]),
       "warmup": T["warmup"], "cpu_ms": T["cpu"]["median_ms"], "result_rows": T["result_rows"],
       "gpu_equals_cpu": T["gpu_equals_cpu"], "compare_mode": T["gpu_vs_cpu"]["mode"],
       "timing_log_planning_ms": T["log_split_median_ms"]["planning"], "timing_log_engine_ms": T["log_split_median_ms"]["engine"],
       "pcie_overall": P["overall"], "table_rows": P.get("table_rows"),
       "pinned_bytes": pinned, "pool_peak_after_pin_bytes": pin_end_peak, "pool_peak_end_bytes": max(peaks) if peaks else None,
       "pool_peak_note": "process-lifetime high-water; if end == after_pin, the query never exceeded the pin-phase peak",
       "measured_iters": [r["iter"] for r in its], "kernels_per_iter": [r["kernels"] for r in its],
       "nsys_median": {k: med(k) for k in ["planning_ms", "engine_ms", "gpu_busy_ms", "kernels", "gpu_ops", "kernel_ms",
                                            "lt5us", "ge100us", "ge100us_ms", "grid_lt48", "grid_1"]},
       "rep_iter": rep}
json.dump(out, open(OUT, "w"), indent=1)
m = out["nsys_median"]
print(f"{LABEL}: warm {out['warm_ms']} ms, kernels {m['kernels']}, ops {m['gpu_ops']}, busy {m['gpu_busy_ms']:.3f} ms "
      f"({100*m['gpu_busy_ms']/out['warm_ms']:.1f}% of wall), pinned {pinned/1e6 if pinned else 0:.0f} MB, "
      f"pool peak after pin {pin_end_peak/1e6 if pin_end_peak else 0:.0f} MB / end {out['pool_peak_end_bytes']/1e6 if peaks else 0:.0f} MB")
