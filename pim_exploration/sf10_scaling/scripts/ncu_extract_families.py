"""Per-family Nsight Compute metrics of a restricted warm-iteration run, next to the same families at SF1.

Usage: venv/bin/python -I ncu_extract_families.py <results_dir> <N> [sf1_metrics_json]
Reads <results_dir>/profiles/q<N>_warm_fam_<func>.ncu-rep (one per family) (+ ncu_families_plan.json) and, for SF1, the existing
pipeline file tpch_q1_analysis/analysis/results/q<N>/ncu_warm_metrics.json (every warm SF1 launch, --set full).
Writes <results_dir>/ncu_families_metrics.json. Per family (both scales, same aggregation):
  launches, ncu_us (sum), dram_GBps = sum DRAM bytes / sum ncu time, pct_of_672, inst_per_byte = sum warp inst /
  sum DRAM bytes, l2_hit (time-weighted), waves (min/median/max), grid (min/max), stall mix (share of all pc samples
  of the family), thread_eff (time-weighted lanes of 32), occ_ach (time-weighted), launches_lt1wave.
ncu conditions: serialized, clocks locked (~2.3 GHz), L2 flushed before each kernel -> cold-L2 DRAM bytes; never mix
these durations with nsys durations.
"""
import collections, csv, io, json, os, statistics, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kclass import func_base

R, N = sys.argv[1], int(sys.argv[2])
SF1 = sys.argv[3] if len(sys.argv) > 3 else f"/home/sai/cs254_project/tpch_q1_analysis/analysis/results/q{N}/ncu_warm_metrics.json"
plan = json.load(open(f"{R}/ncu_families_plan.json"))
W = {"dur_ns": "gpu__time_duration.sum", "dram_pct": "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed",
     "dram_rd": "dram__bytes_op_read.sum", "dram_wr": "dram__bytes_op_write.sum", "l2_hit": "lts__t_sector_hit_rate.pct",
     "waves": "launch__waves_per_multiprocessor", "grid": "launch__grid_size", "inst": "smsp__inst_executed.sum",
     "occ_ach": "sm__warps_active.avg.pct_of_peak_sustained_active", "thread_eff": "smsp__thread_inst_executed_per_inst_executed.ratio",
     "ipc": "sm__inst_executed.avg.per_cycle_active", "sm_clk_hz": "sm__cycles_elapsed.avg.per_second",
     "mem_pct": "gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed", "sm_pct": "sm__throughput.avg.pct_of_peak_sustained_elapsed"}
STALL = "smsp__pcsamp_warps_issue_stalled_"
num = lambda v: (lambda s: float(s) if s not in ("", "n/a") else None)(v.replace(",", "")) if v is not None else None


def load(rep):
    raw = subprocess.run(["/usr/local/cuda/bin/ncu", "--import", rep, "--page", "raw", "--csv", "--print-units", "base"],
                         capture_output=True, text=True, check=True).stdout
    rd = csv.reader(io.StringIO("\n".join(l for l in raw.splitlines() if l.startswith('"'))))
    hdr = next(rd); next(rd); col = {h: i for i, h in enumerate(hdr)}
    out = []
    for r in rd:
        k = {"name": r[col["Kernel Name"]], "func": func_base(r[col["Kernel Name"]])}
        for key, m in W.items():
            try:
                k[key] = num(r[col[m]]) if m in col else None
            except ValueError:
                k[key] = None
        k["stalls"] = {}
        for h, i in col.items():
            if h.startswith(STALL) and not h.endswith("_not_issued"):
                try:
                    v = num(r[i])
                except ValueError:
                    v = None
                if v:
                    k["stalls"][h[len(STALL):]] = v
        out.append(k)
    return out


def agg(ks):
    t = sum(k["dur_ns"] or 0 for k in ks) or 1
    b = sum((k["dram_rd"] or 0) + (k["dram_wr"] or 0) for k in ks)
    wt = lambda f: sum((k[f] or 0) * (k["dur_ns"] or 0) for k in ks if k.get(f) is not None) / t
    st = collections.Counter()
    for k in ks:
        st.update(k["stalls"])
    ss = sum(st.values()) or 1
    wv = sorted(k["waves"] or 0 for k in ks)
    return {"launches": len(ks), "ncu_us": t / 1e3, "dram_MB": b / 1e6, "dram_GBps": b / t,
            "pct_of_672": 100 * (b / t) / 672.0, "max_launch_pct_of_672": max(100 * ((k["dram_rd"] or 0) + (k["dram_wr"] or 0)) / (k["dur_ns"] or 1) / 672 for k in ks),
            "inst_per_byte": (sum(k["inst"] or 0 for k in ks) / b) if b else None,
            "l2_hit": wt("l2_hit"), "occ_ach": wt("occ_ach"), "thread_eff": wt("thread_eff"), "ipc": wt("ipc"),
            "sm_pct": wt("sm_pct"), "mem_pct": wt("mem_pct"),
            "waves_min": wv[0], "waves_med": statistics.median(wv), "waves_max": wv[-1],
            "launches_lt1wave": sum(w < 1 for w in wv), "grid_min": min(k["grid"] or 0 for k in ks), "grid_max": max(k["grid"] or 0 for k in ks),
            "longest_launch_ncu_us": max(k["dur_ns"] or 0 for k in ks) / 1e3,
            "stall_share": {r: 100 * v / ss for r, v in st.most_common(6)},
            "clk_mhz_med": statistics.median(k["sm_clk_hz"] or 0 for k in ks) / 1e6}


fams = plan["families"]
K, check = [], {}
for r in plan["runs"]:
    rep = f"{R}/profiles/q{N}_warm_fam_{r['func']}.ncu-rep"
    if os.path.exists(rep):
        k = load(rep)
        for x in k:  # a per-family run matched only -k regex:^(func)$; ncu prints anonymous-namespace kernels as
            x["func"] = r["func"]  # "unnamed>::name(...)", which func_base() cannot parse
    else:  # first Q6 run: one combined report of all planned families (-k regex:^(a|b|c)$, uncapped)
        k = [x for x in load(f"{R}/profiles/q{N}_warm_families_top.ncu-rep") if x["func"] == r["func"]]
    # sanity: profiled multiset (func, grid) vs the planned nsys launches of warm iteration 5
    exp = collections.Counter((d["func"], d["grid"]) for d in r["profiled_launches_nsys"])
    got = collections.Counter((x["func"], int(x["grid"] or 0)) for x in k)
    it5 = collections.Counter((d["func"], d["grid"]) for d in r["it5_launches"])
    check[r["func"]] = {"profiled": len(k), "planned": r["count"], "in_iteration5": r["matching_in_iteration5"],
                        "multiset_equal_planned": exp == got, "subset_of_iteration5_multiset": all(got[x] <= it5[x] for x in got),
                        "profiled_share_of_family_nsys_ns": r["profiled_share_of_family_ns"],
                        "missing_vs_planned": [list(x) + [n] for x, n in (exp - got).items()][:6],
                        "unexpected_vs_planned": [list(x) + [n] for x, n in (got - exp).items()][:6]}
    K += k
sf1 = json.load(open(SF1))["kernels"] if os.path.exists(SF1) else []
res = {"query": N, "results_dir": R, "check": check, "sf1_source": SF1 if sf1 else None,
       "ncu_conditions": "serialized, clock-locked, L2 flushed per kernel (cold-L2); durations not comparable to nsys",
       "families": {}}
for f in fams:
    a = [k for k in K if k["func"] == f]
    b = [k for k in sf1 if k.get("func") == f and k.get("has_full")]
    res["families"][f] = {"sf10": agg(a) if a else None, "sf1": agg(b) if b else None}
json.dump(res, open(f"{R}/ncu_families_metrics.json", "w"), indent=1)
print(f"q{N}: profiled {len(K)} launches"); [print("  check", f, {a: b for a, b in v.items() if a not in ("missing_vs_planned", "unexpected_vs_planned") or b}) for f, v in check.items()]
hdr = f"{'family':32s} {'SF':>4} {'n':>4} {'ncu_us':>9} {'GB/s':>6} {'%672':>5} {'maxL%':>5} {'inst/B':>7} {'L2hit':>5} {'waves med/max':>13} {'lanes':>5} top stalls"
print(hdr)
for f, v in res["families"].items():
    for sf in ("sf1", "sf10"):
        x = v[sf]
        if not x:
            print(f"{f[:32]:32s} {sf:>4} (none)"); continue
        ipb = f"{x['inst_per_byte']:.3f}" if x["inst_per_byte"] is not None else "-"
        print(f"{f[:32]:32s} {sf:>4} {x['launches']:4d} {x['ncu_us']:9.1f} {x['dram_GBps']:6.1f} {x['pct_of_672']:5.1f} {x['max_launch_pct_of_672']:5.1f} "
              f"{ipb:>7} {x['l2_hit']:5.1f} {x['waves_med']:6.2f}/{x['waves_max']:6.2f} {x['thread_eff']:5.1f} "
              + ", ".join(f"{r}={s:.0f}%" for r, s in list(x["stall_share"].items())[:4]))
