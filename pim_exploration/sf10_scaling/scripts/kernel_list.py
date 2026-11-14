"""Warm-iteration kernel list + profiling plan from three ncu "list" passes (pin + 3/4/5 iterations).

Usage: python3 -I kernel_list.py <list_x3.csv> <list_x4.csv> <list_x5.csv> <results_dir> <threshold> <coverage>
Writes warm_kernel_list.json, warm_kernel_summary.txt, ncu_plan.json in <results_dir>; exits 1 if
launch counts are not stable across iterations (the -s/-c slicing would then be wrong).

Plan: skip = N4 (all launches before iteration 5), count = N5 - N4.
  count <= threshold -> policy "full_all": --set full on every warm kernel.
  otherwise          -> policy "light_plus_families": light metrics on all warm kernels + --set full on the
                        kernel families (function base names) that together cover >= coverage of warm GPU time.
"""
import collections, csv, json, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from kclass import func_base, phase, operator

X3, X4, X5, R, THR, COV = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), float(sys.argv[6])


def read(path):
    k = collections.OrderedDict()
    for r in csv.DictReader(l for l in open(path, errors="replace") if l.startswith('"')):
        d = k.setdefault(int(r["ID"]), {"id": int(r["ID"]), "name": r["Kernel Name"]})
        v = r["Metric Value"].replace(",", "")
        try:
            d[r["Metric Name"]] = float(v)
        except ValueError:
            pass
    return list(k.values())


L3, L4, L5 = read(X3), read(X4), read(X5)
N3, N4, N5 = len(L3), len(L4), len(L5)
per = [N4 - N3, N5 - N4]
C = lambda ks: collections.Counter(k["name"] for k in ks)
# Stability without assuming anything about the pin or the cold iteration:
#  - cross-run reproducibility: x4's first N3 launches have x3's multiset, x5's first N4 have x4's multiset
#  - the extra iteration added by each run has the same count and multiset: L4[N3:] == L5[N4:] (and L5[N3:N4] == L5[N4:])
cross_run = C(L4[:N3]) == C(L3) and C(L5[:N4]) == C(L4)
tail_equal = C(L4[N3:]) == C(L5[N4:]) and C(L5[N3:N4]) == C(L5[N4:])
order_diff_4_5 = sum(x["name"] != y["name"] for x, y in zip(L5[N3:N4], L5[N4:]))
prefix_diff = sum(x["name"] != y["name"] for x, y in zip(L4, L5))
try:
    nsys_per = json.load(open(f"{R}/pcie.json"))["per_iteration"][-1]["kernels"]
except Exception:
    nsys_per = None
reasons = []
if not (N3 > 0 and per[0] == per[1] > 0):
    reasons.append(f"launches per added iteration differ: x4-x3={per[0]}, x5-x4={per[1]}")
if not cross_run:
    reasons.append("prefix of a longer run does not reproduce the shorter run's kernel multiset")
if not tail_equal:
    reasons.append("the added iteration's kernel multiset differs between runs / between iterations 4 and 5")
if nsys_per is not None and nsys_per != per[1]:
    reasons.append(f"nsys run has {nsys_per} kernels per measured iteration, ncu list pass {per[1]}")
stable = not reasons
warm = L5[N4:]
for k in warm:
    k["dur_ns"] = k.pop("gpu__time_duration.sum", 0.0)
    k["grid"] = k.pop("launch__grid_size", None); k["block"] = k.pop("launch__block_size", None)
    k["regs"] = k.pop("launch__registers_per_thread", None)
    k["func"] = func_base(k["name"]); k["phase"] = phase(k["name"]); k["operator"] = operator(k["name"])
json.dump(warm, open(f"{R}/warm_kernel_list.json", "w"), indent=1)

tot = sum(k["dur_ns"] for k in warm) or 1.0
fam = collections.defaultdict(lambda: [0, 0.0])
for k in warm:
    fam[k["func"]][0] += 1; fam[k["func"]][1] += k["dur_ns"]
fams = sorted(fam.items(), key=lambda kv: -kv[1][1])
chosen, acc = [], 0.0
for f, (c, t) in fams:
    if acc >= min(1.0, COV + 0.03) * tot:  # 3-point margin: the detail run's durations differ slightly from the list pass
        break
    chosen.append(f); acc += t
regex = "^(" + "|".join(re.escape(f) for f in chosen) + ")$"
rx = re.compile(regex)
pre_match = sum(bool(rx.search(func_base(k["name"]))) for k in L5[:N4])
warm_match = [k for k in warm if rx.search(k["func"])]
plan = {"N3": N3, "N4": N4, "N5": N5, "pin_plus_iteration1_if_iterations_2_3_equal": N3 - 2 * per[0],
        "per_iteration_counts": per, "cross_run_prefix_multisets_equal": cross_run, "added_iteration_multisets_equal": tail_equal,
        "order_positions_differing_iter4_vs_iter5": order_diff_4_5, "x4_vs_x5_prefix_positions_differing": prefix_diff,
        "nsys_kernels_per_warm_iter": nsys_per, "stable": stable, "unstable_reasons": reasons,
        "skip": N4, "count": N5 - N4, "threshold": THR, "coverage": COV,
        "policy": "full_all" if N5 - N4 <= THR else "light_plus_families",
        "families": [{"func": f, "count": c, "time_us": t / 1e3, "pct": 100 * t / tot} for f, (c, t) in fams],
        "full_families": chosen, "full_regex": regex, "full_regex_skip": pre_match, "full_regex_count": len(warm_match),
        "full_regex_time_pct": 100 * sum(k["dur_ns"] for k in warm_match) / tot}
json.dump(plan, open(f"{R}/ncu_plan.json", "w"), indent=1)

with open(f"{R}/warm_kernel_summary.txt", "w") as f:
    f.write(f"ncu list passes: pin+3 iters={N3}, pin+4={N4}, pin+5={N5} launches; launches added per iteration {per}; "
            f"nsys kernels per measured iteration {nsys_per}\n")
    f.write(f"cross-run prefix multisets reproduce: {cross_run}; added-iteration multisets equal (x4 tail, x5 tail, x5 iter 4): "
            f"{tail_equal}; STABLE: {stable} {reasons or ''}\n")
    f.write(f"launch-order differences (multi-threaded pipelines interleave): x5 iteration 4 vs 5 differ at {order_diff_4_5} positions; "
            f"x4 vs first N4 of x5 at {prefix_diff} positions (only counts and multisets are used for the -s/-c slice)\n")
    f.write(f"warm iteration (5th): {len(warm)} kernels, serialized GPU time {tot/1e3:.1f} us "
            f"(ncu gpu__time_duration: kernels serialized, clocks locked to base, L2 flushed before each kernel)\n")
    d = sorted(k["dur_ns"] for k in warm)
    f.write(f"median kernel {d[len(d)//2]/1e3:.2f} us; <5 us: {sum(x < 5e3 for x in d)}; <10 us: {sum(x < 1e4 for x in d)}; "
            f"time in <10 us kernels: {sum(x for x in d if x < 1e4)/1e3:.1f} us\n")
    f.write(f"policy: {plan['policy']} (threshold {THR}); full-set families ({COV:.0%} coverage): {chosen} "
            f"-> {len(warm_match)} kernels, {plan['full_regex_time_pct']:.1f}% of time\n\n")
    f.write(f"{'family (function base)':42s} {'count':>5} {'time_us':>9} {'pct':>6} {'avg_us':>8}\n")
    for fn, (c, t) in fams:
        f.write(f"{fn[:42]:42s} {c:5d} {t/1e3:9.1f} {100*t/tot:6.1f} {t/c/1e3:8.2f}\n")
    ph = collections.defaultdict(lambda: [0, 0.0])
    for k in warm:
        ph[k["phase"]][0] += 1; ph[k["phase"]][1] += k["dur_ns"]
    f.write(f"\n{'phase':28s} {'count':>5} {'time_us':>9} {'pct':>6}\n")
    for p, (c, t) in sorted(ph.items(), key=lambda kv: -kv[1][1]):
        f.write(f"{p:28s} {c:5d} {t/1e3:9.1f} {100*t/tot:6.1f}\n")
print(open(f"{R}/warm_kernel_summary.txt").read())
if not stable:
    msg = (f"kernel launches are not deterministic across runs/iterations: {'; '.join(reasons)}. The -s/-c warm-iteration "
           f"slice cannot be trusted; stage detail refuses to run (see ncu_plan.json, warm_kernel_summary.txt).")
    open(f"{R}/ERROR.txt", "w").write(f"q-stage list: {msg}\n")
    sys.exit("ERROR: " + msg)
