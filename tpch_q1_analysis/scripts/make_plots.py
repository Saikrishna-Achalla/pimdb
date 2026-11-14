"""Plots for the TPC-H Q1 Sirius report.
Usage: venv/bin/python -I scripts/make_plots.py [out_dir pinned.json unpinned.json wall_pinned_ms wall_unpinned_ms wall_cpu_ms SF]
Defaults reproduce the original SF1 run."""
import json, collections, re, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "/home/sai/cs254_project/tpch_q1_analysis"
_a = sys.argv[1:] or [f"{ROOT}/analysis/results/q1", f"{ROOT}/analysis/results/q1/ncu_q1_warm_full.json",
                      f"{ROOT}/traces/ncu_unpinned_warm_full.json", "12", "20", "31", "1"]
OUT, PJ, UJ = _a[0], _a[1], _a[2]
WALL_PINNED_MS, WALL_UNPINNED_MS, WALL_CPU_MS = map(float, _a[3:6]); SF = _a[6]
K = json.load(open(PJ))["kernels"]
K.sort(key=lambda k: k["id"])
SMS, PEAK_WIPC_PER_SM = 48, 4  # sm_120: 4 SMSPs, 1 warp-inst/clk each
CLK = sorted(k["sm_clk_hz"] for k in K)[len(K) // 2]
PEAK_GIPS = SMS * PEAK_WIPC_PER_SM * CLK / 1e9
PEAK_BW = 672.0  # GB/s


def phase(n):
    if any(s in n for s in ("parquet::", "unsnap", "nvcomp", "decompress", "codec", "PageInfo")): return "Parquet decode"
    if any(s in n for s in ("groupby", "cuco", "insert_and_find")): return "Hash group-by"
    if "compute_column_kernel" in n or "ast::" in n: return "Expression (AST)"
    if "merge_sort" in n or "Sort" in n or "sort" in n: return "Sort / ORDER BY"
    if "Memcpy" in n or "concatenate" in n or "gather" in n: return "Copy / concat / gather"
    if "Scan" in n or "Reduce" in n or "Select" in n or "Compact" in n: return "CUB scan/select/reduce"
    return "Other (transform/fill)"


COL = {"Parquet decode": "#d1495b", "Hash group-by": "#00798c", "Expression (AST)": "#edae49",
       "Sort / ORDER BY": "#66a182", "Copy / concat / gather": "#8d96a3",
       "CUB scan/select/reduce": "#2e4057", "Other (transform/fill)": "#b8b8d1"}


def short(n):
    n = n.replace("<unnamed>::", "").replace("(anonymous namespace)::", "")
    n = re.sub(r"\(.*$", "", n); n = re.sub(r"^void ", "", n); n = re.sub(r"<.*", "", n)
    return n.split("::")[-1]


tot = sum(k["dur_ns"] for k in K)

# 1. phase breakdown
agg = collections.defaultdict(float); cnt = collections.Counter()
for k in K:
    agg[phase(k["name"])] += k["dur_ns"]; cnt[phase(k["name"])] += 1
items = sorted(agg.items(), key=lambda kv: kv[1])
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh([f"{p} ({cnt[p]} kernels)" for p, _ in items], [t / 1e3 for _, t in items], color=[COL[p] for p, _ in items])
for i, (p, t) in enumerate(items):
    ax.text(t / 1e3 + max(agg.values()) / 1e3 * 0.02, i, f"{t/1e3:.0f} us  ({100*t/tot:.0f}%)", va="center", fontsize=9)
ax.set_xlabel("GPU kernel time (us, ncu, serialized, SM clock %.0f MHz)" % (CLK / 1e6))
ax.set_title(f"Q1 SF{SF}, lineitem pinned on GPU: GPU time by phase ({len(K)} kernels)", fontsize=10)
ax.set_xlim(0, max(agg.values()) / 1e3 * 1.35)
plt.tight_layout(); plt.savefig(f"{OUT}/q1_phase_breakdown.png", dpi=150); plt.close()

# 2. serialized kernel sequence
fig, ax = plt.subplots(figsize=(11, 3.2))
t0 = 0.0
for k in K:
    d = k["dur_ns"] / 1e3
    ax.barh(0, d, left=t0, color=COL[phase(k["name"])], edgecolor="none", height=0.6)
    if d > tot / 1e3 * 0.06:
        ax.text(t0 + d / 2, 0.42, short(k["name"]).replace("_kernel", ""), rotation=30, fontsize=7, ha="left", va="bottom")
    t0 += d
ax.set_yticks([]); ax.set_ylim(-0.5, 1.6)
ax.set_xlabel("cumulative GPU time (us) in launch order — kernels serialized by ncu")
ax.set_title(f"Q1 SF{SF} warm query (lineitem pinned on GPU): {len(K)} kernels in launch order")
_present = [p for p in COL if any(phase(k["name"]) == p for k in K)]
ax.legend([plt.Rectangle((0, 0), 1, 1, color=COL[p]) for p in _present], _present, ncol=3, fontsize=7, loc="upper right", frameon=False)
plt.tight_layout(); plt.savefig(f"{OUT}/q1_kernel_sequence.png", dpi=150); plt.close()

# 3. instruction roofline (warp instructions vs DRAM bytes)
fig, ax = plt.subplots(figsize=(7.5, 5.2))
xs = [10 ** (i / 20) for i in range(-80, 41)]
ax.plot(xs, [min(PEAK_GIPS, PEAK_BW * x) for x in xs], "k-", lw=1.5)
ax.text(1e-3 * 1.3, PEAK_BW * 1e-3 * 1.6, f"DRAM {PEAK_BW:.0f} GB/s", rotation=33, fontsize=8)
ax.text(5, PEAK_GIPS * 1.1, f"issue peak {PEAK_GIPS:.0f} G warp-inst/s", fontsize=8)
big = [k for k in K if k["dur_ns"] > tot * 0.002 and k["dram_bytes"] > 0]
TOP_IDS, _seen = set(), set()
for k in sorted(big, key=lambda k: -k["dur_ns"]):
    if short(k["name"]) not in _seen and len(TOP_IDS) < 5:
        TOP_IDS.add(k["id"]); _seen.add(short(k["name"]))
for k in big:
    x = k["inst"] / k["dram_bytes"]; y = k["inst"] / k["dur_ns"]
    ax.scatter(x, y, s=k["dur_ns"] / tot * 1500, color=COL[phase(k["name"])], alpha=0.8, edgecolor="k", lw=0.4)
    if k["id"] in TOP_IDS:
        ax.annotate(f"{short(k['name']).replace('_kernel','')} ({k['dur_ns']/1e3:.0f}us)", (x, y), fontsize=7,
                    xytext=(6, -12 if "aggs" in k["name"] else (6 if "mapping" in k["name"] else -14)), textcoords="offset points")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("instruction intensity (warp instructions / DRAM byte)")
ax.set_ylabel("achieved G warp-instructions / s")
ax.set_title(f"Instruction roofline — Q1 SF{SF} kernels > 0.2% of GPU time (bubble area ~ time)")
ax.set_xlim(1e-3, 1e3); ax.set_ylim(0.1, PEAK_GIPS * 3)
PRESENT = [p for p in COL if any(phase(k["name"]) == p for k in K)]
ax.legend([plt.Line2D([], [], marker="o", ls="", color=COL[p]) for p in PRESENT], PRESENT, fontsize=7, loc="lower left", bbox_to_anchor=(0.18, 0.02))
plt.tight_layout(); plt.savefig(f"{OUT}/q1_roofline.png", dpi=150); plt.close()

# 4. stall mix
def mix(ks):
    c = collections.Counter()
    for k in ks:
        s = sum(k["stalls"].values())
        for r, v in k["stalls"].items():
            c[r] += k["dur_ns"] * v / s if s else 0
    t = sum(c.values()); return {r: 100 * v / t for r, v in c.items()}
top3 = sorted(K, key=lambda k: -k["dur_ns"])[:3]
groups = {f"All {len(K)} kernels": K}
for k in top3:
    groups[f"{short(k['name'])} (id {k['id']}, {k['dur_ns']/1e3:.0f} us)"] = [k]
reasons = ["long_scoreboard", "barrier", "wait", "short_scoreboard", "not_selected", "selected", "math_pipe_throttle", "branch_resolving", "no_instructions"]
rc = plt.cm.tab10.colors
fig, ax = plt.subplots(figsize=(9, 3.6))
for gi, (g, ks) in enumerate(groups.items()):
    m = mix(ks); left = 0
    for ri, r in enumerate(reasons):
        v = m.get(r, 0); ax.barh(gi, v, left=left, color=rc[ri], label=r if gi == 0 else None)
        if v > 6: ax.text(left + v / 2, gi, f"{v:.0f}", ha="center", va="center", fontsize=7, color="white")
        left += v
    ax.barh(gi, 100 - left, left=left, color="#dddddd", label="other" if gi == 0 else None)
ax.set_yticks(range(len(groups))); ax.set_yticklabels(groups.keys(), fontsize=8); ax.invert_yaxis()
ax.set_xlabel("% of warp stall samples (time-weighted)"); ax.set_xlim(0, 100)
ax.legend(fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.45, -0.25), frameon=False)
ax.set_title("Warp stall reasons")
plt.tight_layout(); plt.savefig(f"{OUT}/q1_stalls.png", dpi=150); plt.close()

# 5. pinned vs unpinned comparison (unpinned data kept in traces/ for reference)
U = json.load(open(UJ))["kernels"]
def by_phase(ks):
    a = collections.defaultdict(float)
    for k in ks: a[phase(k["name"])] += k["dur_ns"] / 1e3
    return a
pu, pp = by_phase(U), by_phase(K)
wall = {"unpinned": WALL_UNPINNED_MS, "pinned": WALL_PINNED_MS}
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.3, 1]})
for xi, (lab, d, n) in enumerate([("Parquet in pinned\nCPU cache (before)", pu, len(U)), ("lineitem pinned\non GPU (now)", pp, len(K))]):
    bottom = 0
    for ph in COL:
        v = d.get(ph, 0)
        a1.bar(xi, v, bottom=bottom, color=COL[ph], width=0.55, label=ph if xi == 0 else None)
        if v > max(sum(pu.values()), sum(pp.values())) * 0.04: a1.text(xi, bottom + v / 2, f"{v/1e3:.1f} ms", ha="center", va="center", fontsize=7, color="white")
        bottom += v
    a1.text(xi, bottom + max(sum(pu.values()), sum(pp.values())) * 0.02, f"{bottom/1e3:.1f} ms\n{n} kernels", ha="center", fontsize=8)
a1.set_xticks([0, 1]); a1.set_xticklabels(["Parquet in pinned\nCPU cache (before)", "lineitem pinned\non GPU (now)"], fontsize=8)
a1.set_ylabel("GPU kernel time (us, ncu)"); a1.set_title("GPU kernel time by phase", fontsize=10)
a1.set_ylim(0, max(sum(pu.values()), sum(pp.values())) * 1.2)
a1.legend(fontsize=6.5, loc="upper right")
a2.bar([0, 1], [wall["unpinned"], wall["pinned"]], color=["#8d96a3", "#00798c"], width=0.55)
a2.bar([2], [WALL_CPU_MS], color="#edae49", width=0.55)
for x, v in zip([0, 1, 2], [wall["unpinned"], wall["pinned"], WALL_CPU_MS]): a2.text(x, v + 0.5, f"{v:.0f} ms", ha="center", fontsize=9)
a2.set_xticks([0, 1, 2]); a2.set_xticklabels(["Sirius\n(before)", "Sirius\npinned (now)", "DuckDB\nCPU"], fontsize=8)
a2.set_ylabel("warm end-to-end (ms, median)"); a2.set_title("End-to-end Q1 time", fontsize=10); a2.set_ylim(0, max(wall["unpinned"], WALL_CPU_MS) * 1.18)
plt.tight_layout(); plt.savefig(f"{OUT}/q1_pinned_vs_unpinned.png", dpi=150); plt.close()
print("peak GIPS", PEAK_GIPS, "clock", CLK)
