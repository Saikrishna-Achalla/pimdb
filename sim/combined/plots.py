"""Four plots for the combined report, from the CSVs written by combine.py and coverage.py.

Run (after combine.py and coverage.py):
  /home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I sim/combined/plots.py
Writes sim/combined/plots/{operator_speedups,chain_time_breakdown,pim_time_composition,coverage_by_query}.png
Colours: dataviz reference palette slots 1..4 in fixed order; white background; 200 dpi.
"""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = "/home/sai/cs254_project"
D = os.path.join(ROOT, "sim/combined")
OUTD = os.path.join(D, "plots")
os.makedirs(OUTD, exist_ok=True)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 10.5, "axes.titlecolor": INK,
                     "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})


def style(ax, grid_axis="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def rd(name):
    return list(csv.DictReader(open(os.path.join(D, name))))


# ------------------------------------------------------------------ 1. operator speedups (SF 0.1, S1 scale)
ops = rd("operators_speedup.csv")
pick = [("predicate int32 < const -> mask", "pred_ship32 [op/host]", "pred int32\nbit mask"),
        ("predicate int32 < const -> mask", "pred_ship32_bool8out [op/host]", "pred int32\nbool8 mask"),
        ("predicate int32 < const -> mask", "pred_ship32+maskreadout [op/host]", "pred int32\n+ GPU reads"),
        ("cast int32 -> int64", "ew_widen32to64 [op/host]", "cast\n4->8 B"),
        ("multiply int64 x int64 -> int64", "ew_mul64x64 [op/host]", "multiply\n64x64"),
        ("sum int32", "sum_int32 [op/host]", "sum\nint32"),
        ("sum int64", "sum_int64 [op/host]", "sum\nint64"),
        ("compaction mask -> row ids", "compact_ids [op/seq]", "compaction*\nin mem (seq)"),
        ("compaction mask -> row ids", "compact_ids+readout [op/seq]", "compaction*\n+ GPU reads"),
        ("membership in 8-key set -> mask", "member_in8 [tile/seq]", "8-key IN*\n(one op)"),
        ("conjunctive range filter -> mask", "pred_and [tile/seq]", "range filter*\n(one op)")]
vals = []
for op, var, lab in pick:
    r = [x for x in ops if x["operator"] == op and x["pim_variant"] == var and x["sf"] == "0.1"][0]
    vals.append((lab, float(r["speedup_vs_sim_baseline"]), float(r["speedup_vs_bw_floor"])))
fig, ax = plt.subplots(figsize=(10, 4.5))
xs = range(len(vals)); w = 0.38
b1 = ax.bar([x - w / 2 for x in xs], [v[1] for v in vals], w, color=C[0], label="vs simulated Vortex S1 baseline")
b2 = ax.bar([x + w / 2 for x in xs], [v[2] for v in vals], w, color=C[1], label="vs baseline bandwidth floor (bytes / 14 GB/s)")
for bars in (b1, b2):
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, h + 0.15, f"{h:.1f}", ha="center", va="bottom", fontsize=7, color=INK2)
ax.axhline(1, color=INK2, linewidth=0.8)
ax.text(-0.55, 1.12, "1x = no gain", ha="left", va="bottom", fontsize=7, color=INK2)
ax.set_xticks(list(xs)); ax.set_xticklabels([v[0] for v in vals], fontsize=7.5)
ax.set_ylabel("speedup of the PIM operator (x)")
ax.set_ylim(0, max(max(v[1], v[2]) for v in vals) * 1.15)
ax.set_title("Operator speedup, SF 0.1, same memory as S1 (14 GB/s = 0.4375 AiM channel)", loc="left")
style(ax)
ax.legend(frameon=False, loc="upper right", fontsize=8)
fig.text(0.01, 0.01, "Modeled ratio of simulated times: Vortex simx (S1) / AiM Ramulator2 1-channel x 1/0.4375. Linear axis. Results stay in memory unless 'GPU reads'.\n"
         "* compaction: Vortex interpolated to the PIM selectivity, different output order; IN / filter: PIM time width-normalized.",
         fontsize=6.8, color=INK2)
fig.tight_layout(rect=(0, 0.07, 1, 1))
fig.savefig(os.path.join(OUTD, "operator_speedups.png"), dpi=200)
plt.close(fig)

# ------------------------------------------------------------------ 2. chain times at full-5070 scale
ch = rd("chains_speedup.csv")


def t(q, sf, rid):
    return float([r for r in ch if r["query"] == q and r["sf"] == sf and r["config"] == "5070 (projected)" and r["row_id"] == rid][0]["time_us"])


series = [("a", "baseline, simulated (S1 x 1/48)"), ("b_samebytes", "baseline floor (input bytes once at 672 GB/s)"),
          ("c", "PIM operator-at-a-time"), ("d", "PIM tile-at-a-time (sequencer)")]
fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
for ax, (q, sf, title) in zip(axes, (("Q6", "1.0", "Q6, SF 1"), ("Q1", "0.1", "Q1, SF 0.1"))):
    v = [t(q, sf, k) for k, _ in series]
    bars = ax.bar(range(4), v, 0.62, color=C[:4])
    for b, x in zip(bars, v):
        ax.text(b.get_x() + b.get_width() / 2, x + max(v) * 0.015, f"{x:.1f} us", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(4)); ax.set_xticklabels(["baseline\nsimulated", "baseline\nfloor", "PIM\nop-at-a-time", "PIM\ntile-at-a-time"], fontsize=8)
    ax.set_ylabel("chain time on the full RTX 5070 (us)")
    ax.set_ylim(0, max(v) * 1.15)
    ax.set_title(title, loc="left")
    style(ax)
handles = [plt.Rectangle((0, 0), 1, 1, color=C[i]) for i in range(4)]
fig.legend(handles, [s[1] for s in series], loc="upper center", ncol=4, frameon=False, fontsize=7.8, bbox_to_anchor=(0.5, 1.0))
fig.text(0.01, 0.01, "Modeled projection: Vortex S1 simulated x 1/48 (incl. Sirius min/max pre-check, excl. host gaps); PIM 1 channel simulated x 1/21; "
         "floor = bytes the PIM chain reads (Q6 14 B/row, Q1 20 B/row) / 672 GB/s.", fontsize=6.8, color=INK2)
fig.tight_layout(rect=(0, 0.04, 1, 0.93))
fig.savefig(os.path.join(OUTD, "chain_time_breakdown.png"), dpi=200)
plt.close(fig)

# ------------------------------------------------------------------ 3. PIM time composition (SF1, 1 channel)
pc = rd(os.path.join(ROOT, "sim/aim_pim/results/chains.csv"))
rows = []
for wl, sch, lab in (("q6_main", "op", "Q6 operator-at-a-time"), ("q6_main", "tile", "Q6 tile-at-a-time"),
                     ("q1_main", "op", "Q1 operator-at-a-time"), ("q1_main", "tile", "Q1 tile-at-a-time")):
    r = [x for x in pc if x["workload"] == wl and x["schedule"] == sch and x["sf"] == "1" and x["config"] == ""][0]
    parts = [float(r[k]) for k in ("compute_cyc", "rowov_turnaround_cyc", "readout_cyc", "refresh_cyc")]
    assert abs(sum(parts) - float(r["cycles"])) < 2
    rows.append((lab, parts, float(r["time_us"]) / 21))
names = ["compute (column commands)", "row activate/precharge + turnarounds", "read-out (RD_MAC)", "refresh"]
fig, ax = plt.subplots(figsize=(10, 4.5))
for i, (lab, parts, t5) in enumerate(rows[::-1]):
    tot = sum(parts); left = 0
    for j, p in enumerate(parts):
        fr = 100 * p / tot
        ax.barh(i, fr, left=left, height=0.58, color=C[j], edgecolor="white", linewidth=1.5)
        if fr >= 4:
            ax.text(left + fr / 2, i, f"{fr:.0f}%", ha="center", va="center", fontsize=8, color="#0b0b0b" if j == 3 else "white")
        left += fr
    ax.text(101, i, f"{t5:.1f} us\n(5070)", ha="left", va="center", fontsize=7.5, color=INK2)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows[::-1]], fontsize=8.5)
ax.set_xlim(0, 112); ax.set_xticks([0, 20, 40, 60, 80, 100])
ax.set_xlabel("share of simulated PIM cycles (%)")
ax.set_title("PIM chain time composition, SF 1, one AiM channel (read-out < 0.1 %: no label)", loc="left")
style(ax, "x")
ax.legend(names, frameon=False, ncol=4, fontsize=7.8, loc="upper center", bbox_to_anchor=(0.5, -0.13))
fig.text(0.01, 0.01, "Simulated (Ramulator2 aim_simulator, sim/aim_pim/results/chains.csv); time at full-5070 scale = 1-channel time / 21 (modeled).",
         fontsize=6.8, color=INK2)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(os.path.join(OUTD, "pim_time_composition.png"), dpi=200)
plt.close(fig)

# ------------------------------------------------------------------ 4. coverage by query
cov = rd("coverage.csv")
fig, ax = plt.subplots(figsize=(10, 4.5))
labs = [r["query"] for r in cov]
segs = [("E: AST compute_column", lambda r: float(r["kernel_ms_E_AST"]) / float(r["kernel_ms"])),
        ("E: other bank-executable", lambda r: (float(r["kernel_ms_E"]) - float(r["kernel_ms_E_AST"])) / float(r["kernel_ms"])),
        ("not executable", lambda r: float(r["kernel_ms_N"]) / float(r["kernel_ms"])),
        ("bookkeeping", lambda r: float(r["kernel_ms_B"]) / float(r["kernel_ms"]))]
bottom = [0.0] * len(cov)
for j, (nm, fn) in enumerate(segs):
    v = [100 * fn(r) for r in cov]
    ax.bar(range(len(cov)), v, 0.7, bottom=bottom, color=C[j], edgecolor="white", linewidth=1.0, label=nm)
    bottom = [b + x for b, x in zip(bottom, v)]
for i, r in enumerate(cov):
    e = 100 * float(r["share_time_E"])
    ax.text(i, 101.5, f"{e:.0f}", ha="center", va="bottom", fontsize=7, color=INK)
ax.text(-0.9, 101.5, "E%", ha="right", va="bottom", fontsize=7, color=INK)
ax.set_xticks(range(len(cov))); ax.set_xticklabels(labs, fontsize=7.5)
ax.set_ylim(0, 108); ax.set_ylabel("share of kernel time (%, ncu serialized)")
ax.set_title("Bank-level executable share of kernel time per query, TPC-H SF 1 (E% on top)", loc="left")
style(ax)
ax.legend(frameon=False, ncol=4, fontsize=7.8, loc="upper center", bbox_to_anchor=(0.5, -0.08))
fig.text(0.01, 0.01, "Measured kernel time (ncu serialized durations, pim_exploration/kernel_fit/launches_all.csv); classification modeled from isr_spec.json "
         "(sim/combined/coverage_families.csv). ALL = sum over Q2-Q22.", fontsize=6.8, color=INK2)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(os.path.join(OUTD, "coverage_by_query.png"), dpi=200)
plt.close(fig)
print("wrote", sorted(os.listdir(OUTD)))
