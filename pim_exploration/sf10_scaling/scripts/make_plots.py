"""Plots for one TPC-H query from ncu_warm_metrics.json (generalized from scripts/make_plots.py).

Usage: venv/bin/python -I make_plots.py <results_dir> <N>
Writes plots/q<N>_{phase_breakdown,kernel_sequence,roofline,stalls}.png
"""
import collections, json, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, __import__("os").path.dirname(__file__))
from kclass import PHASES

R, N = sys.argv[1], sys.argv[2]
K = sorted(json.load(open(f"{R}/ncu_warm_metrics.json"))["kernels"], key=lambda k: k["pos"])
tot = sum(k["dur_ns"] for k in K)
COL = dict(zip(PHASES, ["#d1495b", "#edae49", "#00798c", "#30638e", "#66a182", "#e07a5f", "#8d96a3",
                        "#9c6644", "#2e4057", "#b8b8d1", "#cccccc"]))
CLK = sorted(k["sm_clk_hz"] or 0 for k in K)[len(K) // 2]
PEAK_GIPS = 48 * 4 * CLK / 1e9; PEAK_BW = 672.0
OUT = f"{R}/plots/q{N}"

# 1. phase breakdown
agg = collections.defaultdict(float); cnt = collections.Counter()
for k in K:
    agg[k["phase"]] += k["dur_ns"]; cnt[k["phase"]] += 1
items = sorted(agg.items(), key=lambda kv: kv[1])
fig, ax = plt.subplots(figsize=(8, 0.45 * len(items) + 1.5))
ax.barh([f"{p} ({cnt[p]})" for p, _ in items], [t / 1e3 for _, t in items], color=[COL[p] for p, _ in items])
mx = max(agg.values()) / 1e3
for i, (p, t) in enumerate(items):
    ax.text(t / 1e3 + mx * 0.02, i, f"{t/1e3:.0f} us ({100*t/tot:.1f}%)", va="center", fontsize=8)
ax.set_xlim(0, mx * 1.4)
ax.set_xlabel(f"GPU kernel time (us; ncu, serialized, SM clock {CLK/1e6:.0f} MHz)")
ax.set_title(f"TPC-H Q{N} SF1 warm iteration: GPU time by phase ({len(K)} kernels, {tot/1e3:.0f} us)", fontsize=10)
plt.tight_layout(); plt.savefig(f"{OUT}_phase_breakdown.png", dpi=150); plt.close()

# 2. kernel sequence (serialized, launch order)
fig, ax = plt.subplots(figsize=(11, 3.2)); t0 = 0.0
for k in K:
    d = k["dur_ns"] / 1e3
    ax.barh(0, d, left=t0, color=COL[k["phase"]], edgecolor="white", lw=0.2, height=0.6)
    if d > tot / 1e3 * 0.05:
        ax.text(t0 + d / 2, 0.4, k["func"], rotation=25, fontsize=7, ha="left", va="bottom")
    t0 += d
ax.set_yticks([]); ax.set_ylim(-0.5, 1.8)
ax.set_xlabel("cumulative GPU time (us) in launch order, kernels serialized by ncu")
ax.set_title(f"Q{N} SF1 warm iteration: {len(K)} kernels in launch order")
pres = [p for p in PHASES if cnt[p]]
ax.legend([plt.Rectangle((0, 0), 1, 1, color=COL[p]) for p in pres], pres, ncol=4, fontsize=7, loc="upper right", frameon=False)
plt.tight_layout(); plt.savefig(f"{OUT}_kernel_sequence.png", dpi=150); plt.close()

# 3. instruction roofline
fig, ax = plt.subplots(figsize=(7.5, 5.2))
xs = [10 ** (i / 20) for i in range(-80, 61)]
ax.plot(xs, [min(PEAK_GIPS, PEAK_BW * x) for x in xs], "k-", lw=1.4)
ax.text(2e-3, PEAK_BW * 2e-3 * 1.5, f"DRAM {PEAK_BW:.0f} GB/s", rotation=30, fontsize=8)
ax.text(3, PEAK_GIPS * 1.1, f"issue peak {PEAK_GIPS:.0f} G warp-inst/s", fontsize=8)
pts = [k for k in K if k.get("inst") and k["dram_bytes"] > 0]
lab = {k["pos"] for k in sorted(pts, key=lambda k: -k["dur_ns"])[:5]}
for k in pts:
    x, y = k["inst"] / k["dram_bytes"], k["inst"] / k["dur_ns"]
    ax.scatter(x, y, s=max(6, k["dur_ns"] / tot * 1500), color=COL[k["phase"]], alpha=0.75, edgecolor="k", lw=0.3)
    if k["pos"] in lab:
        ax.annotate(f"{k['func']} ({k['dur_ns']/1e3:.0f}us)", (x, y), fontsize=7, xytext=(5, 4), textcoords="offset points")
ax.set_xscale("log"); ax.set_yscale("log"); ax.set_xlim(1e-3, 1e3); ax.set_ylim(1e-3, PEAK_GIPS * 3)
ax.set_xlabel("warp instructions / DRAM byte"); ax.set_ylabel("achieved G warp-instructions / s")
ax.set_title(f"Instruction roofline, Q{N} SF1 warm kernels (bubble area ~ time)", fontsize=10)
pp = [p for p in PHASES if any(k["phase"] == p for k in pts)]
ax.legend([plt.Line2D([], [], marker="o", ls="", color=COL[p]) for p in pp], pp, fontsize=7, loc="lower right")
plt.tight_layout(); plt.savefig(f"{OUT}_roofline.png", dpi=150); plt.close()


# 4. stall mix
def mix(ks):
    c = collections.Counter()
    for k in ks:
        s = sum(k["stalls"].values())
        for r, v in k["stalls"].items():
            c[r] += k["dur_ns"] * v / s if s else 0
    t = sum(c.values()) or 1
    return {r: 100 * v / t for r, v in c.items()}


full = [k for k in K if k["has_full"]]
fam = collections.defaultdict(list)
for k in full:
    fam[k["func"]].append(k)
groups = {f"all {len(full)} kernels w/ full metrics": full}
for f, ks in sorted(fam.items(), key=lambda kv: -sum(k["dur_ns"] for k in kv[1]))[:4]:
    groups[f"{f} ({len(ks)}x, {sum(k['dur_ns'] for k in ks)/1e3:.0f} us)"] = ks
reasons = ["long_scoreboard", "barrier", "wait", "short_scoreboard", "not_selected", "selected", "math_pipe_throttle",
           "lg_throttle", "mio_throttle", "branch_resolving", "no_instructions", "membar", "drain"]
rc = plt.cm.tab20.colors
fig, ax = plt.subplots(figsize=(9.5, 0.55 * len(groups) + 2))
for gi, (g, ks) in enumerate(groups.items()):
    m = mix(ks); left = 0
    for ri, r in enumerate(reasons):
        v = m.get(r, 0); ax.barh(gi, v, left=left, color=rc[ri], label=r if gi == 0 else None)
        if v > 6:
            ax.text(left + v / 2, gi, f"{v:.0f}", ha="center", va="center", fontsize=7, color="white")
        left += v
    ax.barh(gi, max(0, 100 - left), left=left, color="#eeeeee", label="other" if gi == 0 else None)
ax.set_yticks(range(len(groups))); ax.set_yticklabels(groups.keys(), fontsize=8); ax.invert_yaxis()
ax.set_xlim(0, 100); ax.set_xlabel("% of warp stall samples (time-weighted)")
ax.legend(fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.4, -0.3), frameon=False)
ax.set_title(f"Q{N} SF1 warp stall reasons")
plt.tight_layout(); plt.savefig(f"{OUT}_stalls.png", dpi=150); plt.close()
print(f"plots written: {OUT}_*.png (peak {PEAK_GIPS:.0f} G warp-inst/s at {CLK/1e6:.0f} MHz)")
