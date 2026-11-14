#!/usr/bin/env python
"""Regenerate the six round-1 findings charts from the data files.

Run:  /home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I make_round1_plots.py
Only the standard library, numpy and matplotlib are used.
Outputs (PNG, 200 dpi) and a small CSV "table view" per chart are written next to this script.
"""
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

HERE = os.path.dirname(os.path.abspath(__file__))
PIM = os.path.dirname(HERE)                      # .../pim_exploration
LAUNCH_CSV = f"{PIM}/launch_anatomy/launch_causes.csv"
IDLE_JSON = f"{PIM}/idle_attribution/idle_buckets.json"
PARTB_JSON = f"{PIM}/idle_attribution/partB_summary.json"
SCALING_CSV = f"{PIM}/sf10_scaling/scaling_table.csv"
NCU_JSON = PIM + "/sf10_scaling/q{q}/ncu_families_metrics.json"
TIER_CSV = f"{PIM}/kernel_fit/tier_shares.csv"

# ---- reference palette (dataviz/references/palette.md), light mode, fixed order ----
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]   # slots 1-6
ORDINAL = ["#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"]          # blue steps 250,400,500,600,700
SURFACE = "#ffffff"
INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
LABEL_ON = {"#eda100": INK, "#86b6ef": INK}   # label inside fill: white except on yellow / lightest step

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.family": "DejaVu Sans", "font.size": 9, "text.color": INK,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.linewidth": 0.8, "grid.color": GRID, "grid.linewidth": 0.7, "grid.linestyle": "-",
    "legend.frameon": False,
})
GAP = 1.2          # white edge between touching marks (surface gap)
FIGSIZE = (10, 4.5)
DPI = 200
REPORT = []        # numbers recomputed from data, printed at the end


def title(fig, main, sub, sub_y=0.915):
    fig.text(0.015, 0.968, main, fontsize=13, fontweight="bold", color=INK, ha="left", va="top")
    fig.text(0.015, sub_y, sub, fontsize=8.8, color=INK2, ha="left", va="top", linespacing=1.35)


def footnote(fig, text):
    fig.text(0.015, 0.012, text, fontsize=7.8, color=INK2, ha="left", va="bottom", linespacing=1.3)


def style_axes(ax, grid_axis):
    ax.grid(True, axis=grid_axis)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(AXIS)


def save(fig, name, header, rows):
    fig.savefig(f"{HERE}/{name}.png", dpi=DPI)
    plt.close(fig)
    with open(f"{HERE}/{name}_table.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


# =====================================================================================
# 1. launch causes
# =====================================================================================
def chart_launch_causes():
    causes = ["distinct", "multi-pass", "per-column", "per-batch", "bookkeeping"]
    labels = ["Distinct work", "Multi-pass", "Per-column", "Per-batch", "Bookkeeping"]
    data = {}
    for r in csv.DictReader(open(LAUNCH_CSV)):
        data.setdefault(int(r["q"]), {})[r["cause"]] = int(r["launches"])
    qs = sorted(data)
    vals = {c: [data[q].get(c, 0) for q in qs] for c in causes}
    totals = [sum(data[q].values()) for q in qs]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(left=0.065, right=0.99, top=0.78, bottom=0.13)
    x = list(range(len(qs)))
    bottom = [0] * len(qs)
    for i, c in enumerate(causes):
        ax.bar(x, vals[c], 0.62, bottom=bottom, color=CAT[i], edgecolor=SURFACE, linewidth=GAP,
               label=labels[i])
        bottom = [b + v for b, v in zip(bottom, vals[c])]
    for xi, t in zip(x, totals):
        ax.text(xi, t + 3, str(t), ha="center", va="bottom", fontsize=7.5, color=INK2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"Q{q}" for q in qs])
    ax.set_ylabel("Kernel launches in one warm iteration")
    ax.set_ylim(0, max(totals) * 1.1)
    ax.set_xlim(-0.6, len(qs) - 0.4)
    style_axes(ax, "y")
    ax.spines["left"].set_visible(False)
    ax.legend(ncol=5, loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=8.5, handlelength=1.2,
              handleheight=1.0, columnspacing=1.6, borderaxespad=0.3)
    sums = {c: sum(vals[c]) for c in causes}
    tot = sum(totals)
    title(fig, "Only about one launch in ten is the operator's distinct work",
          "Kernel launches per warm iteration, TPC-H SF1, Q2-Q22 (RTX 5070, Sirius), split by cause of the launch.\n"
          "Causes are inferred from kernel names and plan position; number above each bar is the total.")
    footnote(fig, "Source: launch_anatomy/launch_causes.csv (columns q, cause, launches); queries in numeric order.")
    save(fig, "launch_causes", ["query"] + causes + ["total"],
         [[f"Q{q}"] + [vals[c][i] for c in causes] + [totals[i]] for i, q in enumerate(qs)])
    REPORT.append(("launch_causes", f"total {tot} launches over 21 queries; " +
                   ", ".join(f"{labels[i]} {sums[c]} ({100*sums[c]/tot:.1f}%)" for i, c in enumerate(causes)) +
                   f"; max total Q{qs[totals.index(max(totals))]}={max(totals)}, min Q{qs[totals.index(min(totals))]}={min(totals)}"))


# =====================================================================================
# 2. wall decomposition
# =====================================================================================
def chart_wall():
    d = json.load(open(IDLE_JSON))
    qs = sorted(int(k) for k in d)
    pre, act, idle, post_raw = [], [], [], []
    for q in qs:
        m = d[str(q)]["median"]
        p, e, a = m["pre_engine_ms"], m["engine_ms"], m["buckets_ms"]["gpu_active"]
        pre.append(p)
        act.append(a)
        idle.append(e - a)
        post_raw.append(m["timer_ms"] - p - e)   # as in idle_buckets_table.txt ("post = remainder of timer")
    post = [max(0.0, v) for v in post_raw]
    neg = [(q, v) for q, v in zip(qs, post_raw) if v < 0]
    comps = [("Planning (before engine starts)", pre), ("GPU active", act),
             ("GPU idle in engine span", idle), ("After engine (result)", post)]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(left=0.06, right=0.855, top=0.78, bottom=0.15)
    x = list(range(len(qs)))
    bottom = [0.0] * len(qs)
    for i, (name, v) in enumerate(comps):
        ax.bar(x, v, 0.62, bottom=bottom, color=CAT[i], edgecolor=SURFACE, linewidth=GAP, label=name)
        bottom = [b + t for b, t in zip(bottom, v)]
    # direct labels beside the last column
    last = len(qs) - 1
    cum = 0.0
    for i, (name, v) in enumerate(comps):
        mid = cum + v[last] / 2
        cum += v[last]
        ax.annotate(name.split(" (")[0].replace(" span",""), xy=(last + 0.33, mid), xytext=(last + 0.7, mid), fontsize=8,
                    color=INK, va="center", ha="left", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=AXIS, lw=0.8, shrinkA=0, shrinkB=0))
    ax.set_xticks(x)
    ax.set_xticklabels([f"Q{q}" for q in qs])
    ax.set_ylabel("Warm wall time per query (ms, nsys-traced)")
    ax.set_xlim(-0.6, len(qs) - 0.4)
    ax.set_ylim(0, 24)
    style_axes(ax, "y")
    ax.spines["left"].set_visible(False)
    ax.legend(ncol=4, loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=8.5, handlelength=1.2,
              handleheight=1.0, columnspacing=1.6, borderaxespad=0.3)
    tp, ta, ti, tq = sum(pre), sum(act), sum(idle), sum(post)
    timer_sum = sum(d[str(q)]["median"]["timer_ms"] for q in qs)
    title(fig, "The GPU is busy for about a tenth of the wall time; planning and idle gaps take the rest",
          "Median warm iteration per query, TPC-H SF1. These are nsys-traced runs: traced times are inflated relative to untraced\n"
          "runs (engine span about 1.7x; summed DuckDB timer 259 ms traced vs 163.5 ms untraced).")
    return comps, qs, post_raw, (tp, ta, ti, tq, timer_sum), neg, fig, ax


def finish_wall(res):
    comps, qs, post_raw, (tp, ta, ti, tq, timer_sum), neg, fig, ax = res
    n_neg = len(neg)
    rng = (f"{min(v for _, v in neg):.2f} to {max(v for _, v in neg):.2f} ms" if neg else "")
    footnote(fig, "Source: idle_attribution/idle_buckets.json, per query 'median': pre_engine_ms, engine_ms, buckets_ms.gpu_active, timer_ms.\n"
                  "Idle = engine - gpu_active; after = timer_ms - pre - engine (as in idle_buckets_table.txt), a remainder of a 1 ms timer.\n"
                  f"It is negative for {n_neg} of {len(qs)} queries ({rng}) and drawn as 0 there, so those bars sum slightly above the timer.")
    rows = [[f"Q{q}"] + [round(c[1][i], 4) for c in comps] + [round(post_raw[i], 4)] for i, q in enumerate(qs)]
    save(fig, "wall_decomposition", ["query", "planning_ms", "gpu_active_ms", "gpu_idle_in_engine_ms",
                                     "after_engine_ms_clipped_at_0", "after_engine_ms_raw"], rows)
    tot = tp + ta + ti + tq
    REPORT.append(("wall_decomposition",
                   f"summed over Q2-Q22 (post clipped at 0, total {tot:.1f} ms): planning {tp:.1f} ms ({100*tp/tot:.1f}%), "
                   f"GPU active {ta:.1f} ({100*ta/tot:.1f}%), GPU idle in engine {ti:.1f} ({100*ti/tot:.1f}%), after {tq:.1f} ({100*tq/tot:.1f}%); "
                   f"summed timer {timer_sum:.1f} ms; raw-remainder negatives in {len(neg)} queries"))


# =====================================================================================
# 3. idle composition
# =====================================================================================
def chart_idle_composition():
    p = json.load(open(PARTB_JSON))["queries"]
    order = ["6", "3", "9", "18"]
    cats = [
        ("CUDA runtime / driver", ["i_cuda_launch", "i_cuda_sync_copy_event_other"]),
        ("Allocation", ["ii_alloc"]),
        ("cuDF / Sirius host code between launches", ["iii_cudf_host", "iii_sirius_operator_host"]),
        ("Sirius scheduling and hand-off", ["iv_sirius_sched_handoff"]),
        ("Result handling (DuckDB)", ["v_duckdb_plan_result"]),
        ("Unattributed", ["vi_unattributed"]),
    ]
    rows = []        # (label, [ms per category])
    for q in order:
        g = p[q]["groups_ms"]
        rows.append((f"Q{q}", [sum(g[k] for k in keys) for _, keys in cats], p[q]["gpu_idle_ms"]))
    sums = [sum(r[1][i] for r in rows) for i in range(len(cats))]
    rows.append(("Sum of the four", sums, sum(r[2] for r in rows)))

    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(left=0.17, right=0.985, top=0.70, bottom=0.17)
    ypos = [4.0, 3.0, 2.0, 1.0, -0.25]
    for yi, (lab, v, idle_ms) in zip(ypos, rows):
        tot = sum(v)
        left = 0.0
        for i, ms in enumerate(v):
            w = 100 * ms / tot
            ax.barh(yi, w, 0.58, left=left, color=CAT[i], edgecolor=SURFACE, linewidth=GAP)
            if w >= 5.5:
                ax.text(left + w / 2, yi, f"{w:.0f} %", ha="center", va="center", fontsize=8.5,
                        color=LABEL_ON.get(CAT[i], "#ffffff"), fontweight="bold")
            left += w
    ax.set_yticks(ypos)
    ax.set_yticklabels([f"{r[0]}\n{r[2]:.1f} ms idle" if r[0] != "Sum of the four" else f"Sum of the four\n{r[2]:.1f} ms idle"
                        for r in rows], fontsize=8.8, color=INK)
    ax.set_xlim(0, 100)
    ax.set_ylim(-1.2, 4.5)
    ax.set_xlabel("Share of GPU-idle engine time (%)")
    ax.set_xticks(range(0, 101, 20))
    style_axes(ax, "x")
    ax.spines["left"].set_visible(False)
    ax.axhline(0.375, color=AXIS, lw=0.8)
    tot_s = sum(sums)
    thin = [(cats[i][0], 100 * sums[i] / tot_s) for i in (4, 5)]
    ax.text(100, -0.78, "Too thin to label in the sum bar: " + ", ".join(f"{n.split(' (')[0].lower()} {s:.1f} %" for n, s in thin),
            ha="right", va="center", fontsize=7.8, color=INK2)
    handles = [Patch(facecolor=CAT[i], edgecolor="none", label=cats[i][0]) for i in range(len(cats))]
    ax.legend(handles=handles, ncol=3, loc="lower left", bbox_to_anchor=(-0.17, 1.0), fontsize=8.5,
              handlelength=1.2, handleheight=1.0, columnspacing=1.6, borderaxespad=0.3)
    title(fig, "Scheduling hand-offs and CUDA runtime calls make up most of the GPU-idle time",
          "What the host does while the GPU is idle inside the Sirius engine span, for the four CPU-sampled queries (TPC-H SF1, 150 iterations each).\n"
          "Sampled runs add CUDA tracing, OS-runtime tracing and CPU sampling; the profiler's own cost is excluded from the shares.")
    footnote(fig, "Source: idle_attribution/partB_summary.json, queries.<q>.groups_ms ('profiler_artifact' excluded). CUDA runtime/driver = i_cuda_launch +\n"
                  "i_cuda_sync_copy_event_other; cuDF/Sirius host = iii_cudf_host + iii_sirius_operator_host. 'ms idle' = gpu_idle_ms of the sampled run (includes profiler share).")
    save(fig, "idle_composition", ["row"] + [c[0] + " (ms)" for c in cats] + ["gpu_idle_ms_incl_profiler"],
         [[r[0]] + [round(x, 4) for x in r[1]] + [round(r[2], 4)] for r in rows])
    REPORT.append(("idle_composition", "sum bar shares: " + ", ".join(f"{cats[i][0]} {100*sums[i]/tot_s:.1f}%" for i in range(len(cats))) +
                   "; scheduling share per query " + ", ".join(f"Q{r[0][1:]} {100*r[1][3]/sum(r[1]):.0f}%" for r in rows[:4])))


# =====================================================================================
# 4. SF1 vs SF10 busy share
# =====================================================================================
def dumbbell_axes(fig, ax, labels, ypos):
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=8.8, color=INK)
    ax.invert_yaxis()
    style_axes(ax, "x")
    ax.spines["left"].set_visible(False)


def chart_busy_share():
    rows = {}
    for r in csv.DictReader(open(SCALING_CSV)):
        if r["config"] in ("sf1_main", "sf10_main"):
            rows.setdefault(int(r["query"]), {})[r["config"]] = float(r["busy_pct_wall"])
    qs = sorted(q for q in rows if len(rows[q]) == 2)
    assert len(qs) == 8, qs
    s1 = [rows[q]["sf1_main"] for q in qs]
    s10 = [rows[q]["sf10_main"] for q in qs]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.74, bottom=0.15)
    y = list(range(len(qs)))
    for yi, a, b in zip(y, s1, s10):
        ax.plot([a, b], [yi, yi], color=AXIS, lw=2, solid_capstyle="round", zorder=2)
    ax.scatter(s1, y, s=75, color=CAT[0], edgecolor=SURFACE, linewidth=1.6, zorder=3, label="SF1")
    ax.scatter(s10, y, s=75, color=CAT[1], edgecolor=SURFACE, linewidth=1.6, zorder=3, label="SF10")
    for yi, a, b in zip(y, s1, s10):
        lo, hi = (a, b) if a < b else (b, a)
        ax.text(lo - 1.8, yi, f"{a if a<b else b:.0f} %", ha="right", va="center", fontsize=8.5, color=INK)
        ax.text(hi + 1.8, yi, f"{hi:.0f} %", ha="left", va="center", fontsize=8.5, color=INK)
    dumbbell_axes(fig, ax, [f"Q{q}" for q in qs], y)
    ax.set_xlim(0, 100)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("GPU-busy share of warm wall time (%)")
    ax.legend(ncol=2, loc="lower left", bbox_to_anchor=(0.0, 1.0), fontsize=8.8, handletextpad=0.3, columnspacing=1.5,
              borderaxespad=0.3, scatterpoints=1)
    title(fig, f"GPU-busy share rises in all eight queries at SF10, from {min(s1):.0f}-{max(s1):.0f} % to {min(s10):.0f}-{max(s10):.0f} %",
          "GPU-busy share of warm wall time, SF1 vs SF10, the eight queries measured at both scales. Same configuration at both scales\n"
          "(Sirius yaml with 0.85 GPU pool, 262 MB batches); only the data size changes. Wall time has 1 ms resolution.")
    footnote(fig, "Source: sf10_scaling/scaling_table.csv, rows config = sf1_main and sf10_main, column busy_pct_wall (= gpu_busy_ms / warm_ms).")
    save(fig, "sf1_vs_sf10_busy_share", ["query", "sf1_busy_pct_wall", "sf10_busy_pct_wall"],
         [[f"Q{q}", a, b] for q, a, b in zip(qs, s1, s10)])
    REPORT.append(("sf1_vs_sf10_busy_share", "SF1->SF10 busy %: " + ", ".join(f"Q{q} {a:.0f}->{b:.0f}" for q, a, b in zip(qs, s1, s10))))


# =====================================================================================
# 5. SF1 vs SF10 bandwidth
# =====================================================================================
FAMILIES = [   # (query, family key in ncu_families_metrics.json, short label)
    (18, "transform_kernel", "gather / unique_copy / cast"),
    (18, "_kernel_agent", "reduce_by_key"),
    (18, "static_kernel", "static_kernel"),
    (9, "transform_kernel", "gather / cast"),
    (9, "insert_if_n", "hash-join build insert"),
    (6, "compute_column_kernel", "AST compute_column"),
    (6, "DeviceSelectSweepKernel", "select / compaction sweep"),
    (3, "fused_membership_mask_kernel", "fused membership mask"),
]


def chart_bandwidth():
    pts = []
    for q, fam, short in FAMILIES:
        f = json.load(open(NCU_JSON.format(q=q)))["families"][fam]
        pts.append((q, fam, short, f["sf1"]["pct_of_672"], f["sf10"]["pct_of_672"],
                    f["sf1"]["launches"], f["sf10"]["launches"]))
    pts.sort(key=lambda t: -t[4])
    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(left=0.27, right=0.97, top=0.74, bottom=0.23)
    y = list(range(len(pts)))
    ax.axvline(100, color=INK2, lw=1.0, zorder=1)
    ax.text(99, -0.62, "100 % = 672 GB/s peak", ha="right", va="bottom", fontsize=8, color=INK2)
    for yi, t in zip(y, pts):
        ax.plot([t[3], t[4]], [yi, yi], color=AXIS, lw=2, solid_capstyle="round", zorder=2)
    ax.scatter([t[3] for t in pts], y, s=75, color=CAT[0], edgecolor=SURFACE, linewidth=1.6, zorder=3, label="SF1")
    ax.scatter([t[4] for t in pts], y, s=75, color=CAT[1], edgecolor=SURFACE, linewidth=1.6, zorder=3, label="SF10")
    for yi, t in zip(y, pts):
        lo, hi = min(t[3], t[4]), max(t[3], t[4])
        ax.text(lo - 2.2, yi, f"{lo:.0f} %", ha="right", va="center", fontsize=8.5, color=INK)
        ax.text(hi + 2.2, yi, f"{hi:.0f} %", ha="left", va="center", fontsize=8.5, color=INK)
    dumbbell_axes(fig, ax, [f"Q{t[0]}  {t[2]}" for t in pts], y)
    ax.set_ylim(len(pts) - 0.5, -0.9)
    ax.set_xlim(0, 108)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("Achieved DRAM bandwidth (% of 672 GB/s peak), Nsight Compute")
    ax.legend(ncol=2, loc="lower left", bbox_to_anchor=(-0.27, 1.0), fontsize=8.8, handletextpad=0.3, columnspacing=1.5,
              borderaxespad=0.3, scatterpoints=1)
    title(fig, f"{sum(1 for t in pts if t[4] < 30)} of {len(pts)} kernel families stay under 30 % of peak bandwidth at SF10",
          "Achieved DRAM bandwidth as % of the RTX 5070 peak (672 GB/s) for kernel families profiled with Nsight Compute at both scales.\n"
          "Each value is time-weighted over the family's profiled launches (total DRAM bytes / total ncu duration); cold L2, clock-locked, serialized.")
    footnote(fig, "Source: sf10_scaling/q{3,6,9,18}/ncu_families_metrics.json, families.<name>.{sf1,sf10}.pct_of_672 (SF1 values are stored in the same files).\n"
                  "Rows are the SF1 -> SF10 pairs in finding 5 of note 07. Q9 and Q18 transform_kernel at SF10 cover only the first 40 launches\n"
                  "(35 % and 82 % of the family's nsys time); launch counts differ between SF1 and SF10 (see table CSV).")
    save(fig, "sf1_vs_sf10_bandwidth", ["query", "family", "label", "sf1_pct_of_672", "sf10_pct_of_672", "sf1_launches", "sf10_launches"],
         [[f"Q{t[0]}", t[1], t[2], round(t[3], 3), round(t[4], 3), t[5], t[6]] for t in pts])
    REPORT.append(("sf1_vs_sf10_bandwidth", "SF1->SF10 %: " + ", ".join(f"Q{t[0]} {t[1]} {t[3]:.0f}->{t[4]:.0f}" for t in pts)))


# =====================================================================================
# 6. tier shares
# =====================================================================================
def chart_tiers():
    rows = [r for r in csv.DictReader(open(TIER_CSV)) if r["query"] == "ALL"]
    tiers = ["T1", "T2", "T3", "T4", "T5"]
    by = {r["tier"]: r for r in rows}
    meas = [("Kernel launches", "launch_share", "launches"),
            ("Kernel time (ncu, serialized)", "nsys_time_share", "nsys_us"),
            ("DRAM bytes (ncu)", "ncu_dram_share", "ncu_dram_B")]
    desc = ["T1  sequential map, bitwise / integer add", "T2  sequential with wide math, compaction, scan",
            "T3  gather, hash, atomics (random access)", "T4  tiny bookkeeping kernels",
            "T5  string, AST interpreter, compute-heavy"]
    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(left=0.20, right=0.985, top=0.76, bottom=0.32)
    ypos = [2, 1, 0]
    table = []
    t12l = 100 * (float(by["T1"]["launch_share"]) + float(by["T2"]["launch_share"]))
    t12t = 100 * (float(by["T1"]["nsys_time_share"]) + float(by["T2"]["nsys_time_share"]))
    for yi, (lab, col, _) in zip(ypos, meas):
        left = 0.0
        shares = [100 * float(by[t][col]) for t in tiers]
        assert abs(sum(shares) - 100) < 0.01, sum(shares)   # shares in the file sum to 1
        for i, s in enumerate(shares):
            ax.barh(yi, s, 0.5, left=left, color=ORDINAL[i], edgecolor=SURFACE, linewidth=GAP)
            if s >= 4.5:
                ax.text(left + s / 2, yi, f"{s:.0f} %", ha="center", va="center", fontsize=9.5, fontweight="bold",
                        color=LABEL_ON.get(ORDINAL[i], "#ffffff"))
            else:
                ax.annotate(f"{tiers[i]} {s:.1f} %", xy=(left + s / 2, yi + 0.25), xytext=(min(left + s / 2, 99.5), yi + 0.42),
                            ha=("right" if left + s / 2 > 94 else "center"), va="bottom", fontsize=8.2, color=INK,
                            arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8, shrinkA=0, shrinkB=0))
            left += s
        table.append([lab] + [round(s, 3) for s in shares])
    ax.set_yticks(ypos)
    ax.set_yticklabels([m[0] for m in meas], fontsize=9, color=INK)
    ax.set_xlim(0, 100)
    ax.set_ylim(-0.5, 2.8)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("Share over all 21 queries (%)")
    style_axes(ax, "x")
    ax.spines["left"].set_visible(False)
    handles = [Patch(facecolor=ORDINAL[i], edgecolor="none", label=desc[i]) for i in range(5)]
    ax.legend(handles=handles, ncol=3, loc="upper left", bbox_to_anchor=(-0.20, -0.2), fontsize=8.5,
              handlelength=1.2, handleheight=1.0, columnspacing=1.6, borderaxespad=0.3)
    title(fig, f"Streaming kernels (T1, T2) are {t12l:.0f} % of launches but {t12t:.0f} % of kernel time",
          "Share of kernel launches, kernel time (ncu, serialized) and DRAM bytes in each PIM-fit tier, TPC-H SF1, Q2-Q22 (2,730 launches).\n"
          "Tiers are an inference from access pattern and compute per byte; T1 fits best, T5 worst.")
    footnote(fig, "Source: kernel_fit/tier_shares.csv, row query = ALL, columns launch_share, nsys_time_share, ncu_dram_share.\n"
                  "DRAM bytes are Nsight Compute counters (L2 flushed per kernel, writes undercounted).")
    save(fig, "tier_shares", ["measure"] + tiers, table)
    REPORT.append(("tier_shares", "; ".join(f"{t[0]}: " + " / ".join(f"{tiers[i]} {t[i+1]:.1f}%" for i in range(5)) for t in table)))


def main():
    chart_launch_causes()
    finish_wall(chart_wall())
    chart_idle_composition()
    chart_busy_share()
    chart_bandwidth()
    chart_tiers()
    for name, text in REPORT:
        print(f"{name}: {text}")


if __name__ == "__main__":
    main()
