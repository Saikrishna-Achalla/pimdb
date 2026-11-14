"""Plots for a targeted Q1 profile (lineitem pinned on GPU): kernel list of ALL warm-query kernels
(duration + launch shape, from kernel_list.py) plus a --set full pass over the group-by/aggregation
kernels only (scripts/ncu_profile_q1_groupby.sh).
Usage: venv/bin/python -I scripts/make_plots_targeted.py <out_dir> <kernel_list.json> <groupby_full.json> <SF>"""
import json, collections, re, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT, LJ, GJ, SF = sys.argv[1:5]
K = sorted(({"id": k["id"], "name": k["name"], "dur_ns": k["gpu__time_duration.sum"]} for k in json.load(open(LJ))),
           key=lambda k: k["id"])
G = sorted(json.load(open(GJ))["kernels"], key=lambda k: k["id"])
SMS, PEAK_WIPC_PER_SM = 48, 4  # sm_120: 4 SMSPs, 1 warp-inst/clk each
CLK = sorted(k["sm_clk_hz"] for k in G)[len(G) // 2]
PEAK_GIPS = SMS * PEAK_WIPC_PER_SM * CLK / 1e9
PEAK_BW = 672.0
GB_RE = re.compile(r"single_pass_shmem_aggs|mapping_indices|cuco::|open_addressing|groupby::")


def phase(n):
    if GB_RE.search(n): return "Hash group-by"
    if "compute_column_kernel" in n or "ast::" in n: return "Expression (AST)"
    if "merge_sort" in n or "Sort" in n: return "Sort / ORDER BY"
    if "Memcpy" in n or "concatenate" in n or "gather" in n: return "Copy / concat / gather"
    if "Scan" in n or "Reduce" in n or "Select" in n or "Compact" in n: return "CUB scan/select/reduce"
    return "Other (transform/fill)"


def gb_part(n):
    if "single_pass_shmem_aggs" in n: return "shmem aggregate (single_pass_shmem_aggs)"
    if "mapping_indices" in n: return "key -> slot mapping (mapping_indices, cuco insert_and_find)"
    if "initialize_functor" in n: return "hash-set init (cuco initialize)"
    if "open_addressing" in n: return "retrieve unique keys (DeviceSelectSweep over cuco slots)"
    return "other group-by"


COL = {"Hash group-by": "#00798c", "Expression (AST)": "#edae49", "Sort / ORDER BY": "#66a182",
       "Copy / concat / gather": "#8d96a3", "CUB scan/select/reduce": "#2e4057", "Other (transform/fill)": "#b8b8d1"}


def short(n):
    n = n.replace("<unnamed>::", "").replace("(anonymous namespace)::", "")
    n = re.sub(r"\(.*$", "", n); n = re.sub(r"^void ", "", n); n = re.sub(r"<.*", "", n)
    return n.split("::")[-1]


tot = sum(k["dur_ns"] for k in K)

# 1. phase breakdown (all kernels, light pass)
agg = collections.defaultdict(float); cnt = collections.Counter()
for k in K:
    agg[phase(k["name"])] += k["dur_ns"]; cnt[phase(k["name"])] += 1
items = sorted(agg.items(), key=lambda kv: kv[1])
fig, ax = plt.subplots(figsize=(8, 4))
ax.barh([f"{p} ({cnt[p]} kernels)" for p, _ in items], [t / 1e3 for _, t in items], color=[COL[p] for p, _ in items])
for i, (p, t) in enumerate(items):
    ax.text(t / 1e3 + max(agg.values()) / 1e3 * 0.02, i, f"{t/1e3:,.0f} us  ({100*t/tot:.0f}%)", va="center", fontsize=9)
ax.set_xlabel("GPU kernel time (us, ncu, serialized)")
ax.set_title(f"Q1 SF{SF} (lineitem pinned on GPU): GPU time by phase, {len(K)} kernels, {tot/1e6:.1f} ms", fontsize=9)
ax.set_xlim(0, max(agg.values()) / 1e3 * 1.4)
plt.tight_layout(); plt.savefig(f"{OUT}/q1_phase_breakdown.png", dpi=150); plt.close()

# 2. group-by breakdown (full pass)
ga = collections.defaultdict(lambda: [0, 0.0])
for k in G:
    a = ga[gb_part(k["name"])]; a[0] += 1; a[1] += k["dur_ns"]
gi = sorted(ga.items(), key=lambda kv: kv[1][1])
gt = sum(v[1] for _, v in gi)
fig, ax = plt.subplots(figsize=(8.5, 3.2))
ax.barh([f"{p}\n({n} launches)" for p, (n, _) in gi], [t / 1e3 for _, (_, t) in gi], color="#00798c")
for i, (p, (n, t)) in enumerate(gi):
    ax.text(t / 1e3 + gt / 1e3 * 0.01, i, f"{t/1e3:,.0f} us ({100*t/gt:.0f}%)", va="center", fontsize=8)
ax.set_xlim(0, max(v[1] for _, v in gi) / 1e3 * 1.3); ax.tick_params(axis="y", labelsize=7)
ax.set_xlabel("GPU time (us, ncu --set full, serialized)")
ax.set_title(f"Q1 SF{SF} hash group-by: {len(G)} kernels, {gt/1e3:,.0f} us = {100*gt/tot:.0f}% of GPU time", fontsize=10)
plt.tight_layout(); plt.savefig(f"{OUT}/q1_groupby_breakdown.png", dpi=150); plt.close()

# 3. serialized kernel sequence
fig, ax = plt.subplots(figsize=(11, 3.2))
t0 = 0.0
for k in K:
    d = k["dur_ns"] / 1e3
    ax.barh(0, d, left=t0, color=COL[phase(k["name"])], edgecolor="none", height=0.6)
    t0 += d
ax.set_yticks([]); ax.set_ylim(-0.5, 1.2)
ax.set_xlabel("cumulative GPU time (us) in launch order — kernels serialized by ncu")
ax.set_title(f"Q1 SF{SF} warm query (lineitem pinned on GPU): {len(K)} kernels in launch order")
_present = [p for p in COL if cnt[p]]
ax.legend([plt.Rectangle((0, 0), 1, 1, color=COL[p]) for p in _present], _present, ncol=3, fontsize=7, loc="upper right", frameon=False)
plt.tight_layout(); plt.savefig(f"{OUT}/q1_kernel_sequence.png", dpi=150); plt.close()

# 4. instruction roofline (group-by kernels, full pass)
fig, ax = plt.subplots(figsize=(7.5, 5.2))
xs = [10 ** (i / 20) for i in range(-80, 41)]
ax.plot(xs, [min(PEAK_GIPS, PEAK_BW * x) for x in xs], "k-", lw=1.5)
ax.text(1e-3 * 1.3, PEAK_BW * 1e-3 * 1.6, f"DRAM {PEAK_BW:.0f} GB/s", rotation=33, fontsize=8)
ax.text(5, PEAK_GIPS * 1.1, f"issue peak {PEAK_GIPS:.0f} G warp-inst/s", fontsize=8)
big = [k for k in G if k["dur_ns"] > 5e3 and k["dram_bytes"] > 0 and k["inst"]]
lab = {max((k for k in big if gb_part(k["name"]) == p), key=lambda k: k["dur_ns"])["id"]
       for p in {gb_part(k["name"]) for k in big}}
GCOL = {"shme": "#00798c", "key ": "#d1495b", "hash": "#edae49", "retr": "#2e4057", "othe": "#8d96a3"}
for k in big:
    x = k["inst"] / k["dram_bytes"]; y = k["inst"] / k["dur_ns"]
    ax.scatter(x, y, s=k["dur_ns"] / max(b["dur_ns"] for b in big) * 400, color=GCOL[gb_part(k["name"])[:4]], alpha=0.75, edgecolor="k", lw=0.4)
    if k["id"] in lab:
        ax.annotate(f"{short(k['name']).replace('_kernel','')} ({k['dur_ns']/1e3:.0f}us)", (x, y), fontsize=7,
                    xytext=(6, -12), textcoords="offset points")
ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("instruction intensity (warp instructions / DRAM byte)")
ax.set_ylabel("achieved G warp-instructions / s")
ax.set_title(f"Instruction roofline — Q1 SF{SF} group-by kernels > 5 us (bubble ~ time)", fontsize=10)
ax.set_xlim(1e-3, 1e3); ax.set_ylim(0.1, PEAK_GIPS * 3)
_gp = sorted({gb_part(k["name"]) for k in big})
ax.legend([plt.Line2D([], [], marker="o", ls="", color=GCOL[p[:4]]) for p in _gp], _gp, fontsize=6.5, loc="lower right")
plt.tight_layout(); plt.savefig(f"{OUT}/q1_roofline.png", dpi=150); plt.close()


# 5. stall mix (group-by kernels, full pass)
def mix(ks):
    c = collections.Counter()
    for k in ks:
        s = sum(k["stalls"].values())
        for r, v in k["stalls"].items():
            c[r] += k["dur_ns"] * v / s if s else 0
    t = sum(c.values()); return {r: 100 * v / t for r, v in c.items()}


groups = {f"All {len(G)} group-by kernels": G}
for p in sorted(ga, key=lambda p: -ga[p][1])[:3]:
    groups[p.split(" (")[0] + f" ({ga[p][1]/1e3:,.0f} us)"] = [k for k in G if gb_part(k["name"]) == p]
reasons = ["long_scoreboard", "barrier", "wait", "short_scoreboard", "not_selected", "selected", "math_pipe_throttle", "branch_resolving", "no_instructions", "lg_throttle"]
rc = plt.cm.tab10.colors
fig, ax = plt.subplots(figsize=(9, 3.6))
for gi_, (g, ks) in enumerate(groups.items()):
    m = mix(ks); left = 0
    for ri, r in enumerate(reasons):
        v = m.get(r, 0); ax.barh(gi_, v, left=left, color=rc[ri], label=r if gi_ == 0 else None)
        if v > 6: ax.text(left + v / 2, gi_, f"{v:.0f}", ha="center", va="center", fontsize=7, color="white")
        left += v
    ax.barh(gi_, 100 - left, left=left, color="#dddddd", label="other" if gi_ == 0 else None)
ax.set_yticks(range(len(groups))); ax.set_yticklabels(groups.keys(), fontsize=8); ax.invert_yaxis()
ax.set_xlabel("% of warp stall samples (time-weighted)"); ax.set_xlim(0, 100)
ax.legend(fontsize=7, ncol=6, loc="upper center", bbox_to_anchor=(0.45, -0.25), frameon=False)
ax.set_title(f"Warp stall reasons — Q1 SF{SF} group-by kernels")
plt.tight_layout(); plt.savefig(f"{OUT}/q1_stalls.png", dpi=150); plt.close()

print("peak GIPS", PEAK_GIPS, "clock", CLK, "total GPU us", tot / 1e3)
