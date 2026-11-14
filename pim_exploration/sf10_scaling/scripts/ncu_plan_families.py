"""Plan a restricted Nsight Compute run on the warm iteration: the top-K kernel families by real-clock (nsys) time.

Usage: venv/bin/python -I ncu_plan_families.py <results_dir> <K> <cap> [func ...]
Uses the nsys trace of the same results dir (pin + 3 warmup + 5 measured iterations, same pin and same cold iteration
as the ncu x5 SQL script: pin + 5 iterations, profiled = iteration 5). With `-k regex:` ncu counts --launch-skip and
--launch-count over MATCHING launches only, so:
  skip  = matching launches in the nsys trace that start before the window of iteration 5 (pin phase included)
  count = matching launches inside iteration 5's window (up to the next iteration's window), capped at <cap>.
  (one ncu run per family)
Families: the K function-base names with most kernel ns in the representative warm iteration (scaling_metrics.json),
unless given explicitly. Writes <results_dir>/ncu_families_plan.json and prints `regex skip count`.
"""
import glob, json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog
from kclass import func_base

R, KTOP, CAP = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
M = json.load(open(f"{R}/scaling_metrics.json"))
fams = sys.argv[4:] or [f for f, _ in sorted(M["rep_iter"]["families"].items(), key=lambda kv: -kv[1]["ns"])[:KTOP]]
c = sqlite3.connect(glob.glob(f"{R}/traces/q*_nsys.sqlite")[0])
t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
L, _ = siriuslog.read_run(f"{R}/traces/sirius_log_nsys")
tb = [siriuslog.ts_ms(l) * 1e6 - t0 for l in L if "QueryBegin: transparent_execution" in l]
lo5, lo6 = tb[4] - 1e6, tb[5] - 1e6
S = dict(c.execute("select id, value from StringIds"))
ks = sorted((s, e, func_base(S[d]), gx * gy * gz) for s, e, d, gx, gy, gz in
            c.execute("select start, end, demangledName, gridX, gridY, gridZ from CUPTI_ACTIVITY_KIND_KERNEL"))
runs = []
for f in fams:  # one ncu run per family: its own skip/count, so a capped family still gets its own window
    match = [k for k in ks if k[2] == f]
    it5 = [k for k in match if lo5 <= k[0] < lo6]
    n = min(len(it5), CAP); tot = sum(e - s for s, e, _, _ in it5) or 1
    runs.append({"func": f, "regex": f"^({f})$", "skip": sum(k[0] < lo5 for k in match), "count": n,
                 "matching_in_iteration5": len(it5), "capped": len(it5) > CAP,
                 "it5_launches": [{"func": f, "grid": g, "nsys_dur_ns": e - s} for s, e, _, g in it5],
                 "profiled_launches_nsys": [{"func": f, "grid": g, "nsys_dur_ns": e - s} for s, e, _, g in it5[:n]],
                 "profiled_share_of_family_ns": sum(e - s for s, e, _, _ in it5[:n]) / tot})
plan = {"families": fams, "cap_per_family": CAP, "runs": runs,
        "note": "skip/count count matching launches only (ncu -k regex); profiled = the first <count> launches of the family in "
                "warm iteration 5; launch order can differ by a few positions between runs (4 pipeline threads), so "
                "ncu_extract_families.py compares the profiled (func, grid) multiset with the nsys iteration"}
json.dump(plan, open(f"{R}/ncu_families_plan.json", "w"), indent=1)
for r in runs:
    print(r["func"], r["skip"], r["count"], r["matching_in_iteration5"], f"{r['profiled_share_of_family_ns']:.2f}")
