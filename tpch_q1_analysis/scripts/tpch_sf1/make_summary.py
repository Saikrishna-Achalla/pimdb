"""Cross-query summary of the TPC-H SF1 profiling campaign (Q2-Q22).

Usage: <venv>/bin/python -I make_summary.py [results_dir]
Reads every results/q<N>/ data file, writes results/summary/summary_data.json, three PNG charts in results/summary/,
and results/SUMMARY_tpch_sf1.md. Every number in the page is computed here from the per-query files; nothing is typed in.
"""
import collections, json, os, re, statistics, sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = sys.argv[1] if len(sys.argv) > 1 else "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
OUT = f"{R}/summary"
os.makedirs(OUT, exist_ok=True)
QS = list(range(2, 23))
PEAK_BW = 672e9  # bytes/s, RTX 5070 GDDR7

# ---------------------------------------------------------------- collect
PHASE_GROUPS = collections.OrderedDict([  # fixed order = fixed colour slot
    ("sort / top-N", ["sort/top-N"]),
    ("expression eval", ["expression eval"]),
    ("dynamic-filter scan/filter", ["scan/filter"]),
    ("gather / copy / concat", ["gather/copy/concat"]),
    ("hash join + group-by", ["hash join build", "hash join probe", "hash group-by/agg"]),
    ("cub scan/select/reduce + other", ["cub scan/select/reduce", "other"]),
    ("string ops", ["string ops"]),
])
FAMILY_LABEL = {
    "DeviceMergeSortBlockSortKernel": "merge-sort block sort", "compute_column_kernel": "expression interpreter",
    "fused_membership_mask_kernel": "dynamic-filter probe (fused)", "static_kernel": "`static_kernel` family",
    "transform_kernel": "`transform_kernel` family", "gather_chars_fn_char_parallel": "string character gather",
    "DeviceRadixSortOnesweepKernel": "radix sort (onesweep)", "like_multiliteral_kernel": "`LIKE` matcher",
}


def load(q, name):
    return json.load(open(f"{R}/q{q}/{name}"))


def facts(k):  # one kernel launch: launch shape, throughput and stall shares from the full ncu pass
    st = k.get("stalls") or {}
    tot = sum(st.values()) or 1
    sh = lambda name: 100 * sum(v for n_, v in st.items() if name in n_) / tot
    return dict(func=k["func"], pos=k["pos"], dur_us=k["dur_ns"] / 1e3, grid=int(k.get("grid") or 0), waves=k.get("waves") or 0,
                dram_pct=k.get("dram_pct") or 0, pipe_lsu=k.get("pipe_lsu") or 0, lanes=k.get("thread_eff") or 0,
                barrier=sh("barrier"), long_sb=sh("long_scoreboard"), stall_samples=sum(st.values()))


D = []
for q in QS:
    d = f"{R}/q{q}"
    t, p, plan = load(q, "timing.json"), load(q, "pcie.json"), load(q, "ncu_plan.json")
    nb, m, ph = load(q, "nsys_iteration_breakdown.json"), load(q, "ncu_warm_metrics.json"), load(q, "phase_breakdown.json")
    pv = open(f"{d}/pcie_verification.txt").read()
    st = open(f"{d}/selftest_negative_control.txt").read()
    sm = open(f"{d}/ncu_sysmem_check.txt").read()
    meas = [it for it in p["per_iteration"] if it["measured"]]
    cp = lambda k, f: max(it["copies"].get(k, {}).get(f, 0) for it in meas)
    fam = collections.Counter()
    for it in nb:
        for k, v in it["kernel_ns_by_name"].items():
            fam[k] += v / len(nb)
    ktot = sum(fam.values())
    top = fam.most_common(3)
    K = m["kernels"]
    phases = {x["phase"]: x["time_us"] for x in ph["phases"]}
    grp = {g: sum(phases.get(n, 0.0) for n in ns) for g, ns in PHASE_GROUPS.items()}
    assert abs(sum(grp.values()) - sum(phases.values())) < 1e-6, (q, set(phases) - {n for ns in PHASE_GROUPS.values() for n in ns})
    scans = re.search(r"#GPU_SCAN operators \((\d+)\)", pv)
    smm = re.search(r"(\d+) kernels, (\d+) with SM", sm)
    neg = re.search(r"negative control: '(\w+)' left unpinned", st)
    pinned = p["memory"]["pinned_allocated_bytes"]
    busy = statistics.median(it["gpu_busy_ms"] for it in nb)
    D.append(dict(
        q=q, warm_ms=t["median_ms"], warm_min=t["min_ms"], warm_max=t["max_ms"], cpu_ms=t["cpu"]["median_ms"],
        planning_ms=t["log_split_median_ms"]["planning"], engine_ms=t["log_split_median_ms"]["engine"],
        result_rows=t["result_rows"], result_bytes=t["result_bytes"], compare_mode=t["gpu_vs_cpu"]["mode"],
        max_rel_diff=t["gpu_vs_cpu"]["max_rel_diff"],
        pcie=p["overall"], scans=int(scans.group(1)), tables=len(p["table_rows"]),
        h2d_copies=cp("H2D", "count"), h2d_bytes=cp("H2D", "bytes"), h2d_max=cp("H2D", "max"),
        d2h_copies=cp("D2H", "count"), d2h_bytes=cp("D2H", "bytes"), d2h_max=cp("D2H", "max"),
        um_faults=sum(it["um_faults"] for it in meas), decode_kernels=sum(len(it["decode_kernels"]) for it in meas),
        limits_default=p["limits"] == p["default_limits"],
        pinned_mb=pinned / 1e6, pool_peak_mb=p["memory"]["peak_bytes_high_water"] / 1e6,
        sysmem_kernels=int(smm.group(1)), sysmem_nonzero=int(smm.group(2)), sysmem_pass="-> PASS" in sm,
        selftest_pass="SELFTEST: PASS" in st, selftest_table=neg.group(1) if neg else "?",
        kernels=plan["count"], policy=plan["policy"], ncu_us=ph["total_us"],
        nsys_kernel_us=ktot / 1e3, gpu_busy_ms=busy,
        lt5=sum(k["dur_ns"] < 5000 for k in K), lt1wave=sum((k.get("waves") or 0) < 1 for k in K),
        grid1=sum((k.get("grid") or 0) == 1 for k in K),
        max_dram_pct=max((k.get("dram_pct") or 0) for k in K),
        floor_us=pinned / PEAK_BW * 1e6,
        top=[(n, v / 1e3, 100 * v / ktot) for n, v in top], phase_us=grp,
        longest=facts(max(K, key=lambda k: k["dur_ns"])),
        longest_by_func={f: facts(max((k for k in K if k["func"] == f), key=lambda k: k["dur_ns"]))
                         for f in ("DeviceMergeSortBlockSortKernel", "compute_column_kernel") if any(k["func"] == f for k in K)},
    ))
for r in D:
    r["speedup"] = r["cpu_ms"] / r["warm_ms"]
    r["busy_pct_wall"] = 100 * r["gpu_busy_ms"] / r["warm_ms"]
    r["busy_x_floor"] = r["gpu_busy_ms"] * 1e3 / r["floor_us"]
    r["wall_x_floor"] = r["warm_ms"] * 1e3 / r["floor_us"]
json.dump(D, open(f"{OUT}/summary_data.json", "w"), indent=1)

# ---------------------------------------------------------------- charts
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
S = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]  # validated categorical order
NEUTRAL = "#c9c8c1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK, "text.color": INK, "figure.facecolor": SURF,
                     "axes.facecolor": SURF, "savefig.facecolor": SURF, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.spines.left": False})
labels = [f"Q{r['q']}" for r in D]
y = list(range(len(D)))


def base(title, sub, xlabel, h=7.2):
    fig, ax = plt.subplots(figsize=(8.6, h), dpi=160)
    fig.text(0.02, 0.975, title, fontsize=11.5, fontweight="bold", va="top")
    fig.text(0.02, 0.945, sub, fontsize=8.5, color=INK2, va="top")
    ax.set_yticks(y); ax.set_yticklabels(labels); ax.invert_yaxis()
    ax.xaxis.grid(True, color=GRID, linewidth=0.8); ax.set_axisbelow(True)
    ax.tick_params(length=0); ax.set_xlabel(xlabel)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.86, bottom=0.07)
    return fig, ax


def legend(ax, n):
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=n, frameon=False, fontsize=8.5, handlelength=1.2,
              columnspacing=1.4, borderaxespad=0.2)


# A: Sirius (GPU, pinned) vs DuckDB CPU, warm median
fig, ax = base("Warm query time: Sirius on GPU vs DuckDB on CPU", "TPC-H SF1, median of 12 timed iterations after 3 warmups; 1 ms timer resolution",
               "warm median (ms)")
ax.barh([i - 0.19 for i in y], [r["warm_ms"] for r in D], height=0.34, color=S[0], label="Sirius, data pinned on GPU", edgecolor=SURF, linewidth=1)
ax.barh([i + 0.19 for i in y], [r["cpu_ms"] for r in D], height=0.34, color=S[1], label="DuckDB, CPU", edgecolor=SURF, linewidth=1)
legend(ax, 2)
fig.savefig(f"{OUT}/sf1_wall_gpu_vs_cpu.png"); plt.close(fig)

# B: GPU busy inside the warm wall time
fig, ax = base("How much of the warm query time the GPU is busy",
               "GPU busy = union of kernel + memcpy + memset intervals (nsys run); wall = warm median of the unprofiled timing run", "ms")
ax.barh(y, [r["gpu_busy_ms"] for r in D], height=0.6, color=S[0], label="GPU busy", edgecolor=SURF, linewidth=1.5)
ax.barh(y, [max(r["warm_ms"] - r["gpu_busy_ms"], 0) for r in D], left=[r["gpu_busy_ms"] for r in D], height=0.6, color=NEUTRAL,
        label="rest of wall time (planning, host orchestration, result fetch)", edgecolor=SURF, linewidth=1.5)
legend(ax, 2)
fig.savefig(f"{OUT}/sf1_gpu_busy_share.png"); plt.close(fig)

# C: phase mix of serialized ncu kernel time (100% stacked)
fig, ax = base("Where kernel time goes, by phase",
               "share of serialized ncu kernel time in one warm iteration (clock-locked, L2 flushed before each kernel)", "% of ncu kernel time", h=7.6)
left = [0.0] * len(D)
for i, g in enumerate(PHASE_GROUPS):
    v = [100 * r["phase_us"][g] / sum(r["phase_us"].values()) for r in D]
    ax.barh(y, v, left=left, height=0.62, color=S[i], label=g, edgecolor=SURF, linewidth=1.5)
    left = [a + b for a, b in zip(left, v)]
ax.set_xlim(0, 100)
ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=4, frameon=False, fontsize=8.2, handlelength=1.2, columnspacing=1.2, borderaxespad=0.2)
fig.subplots_adjust(top=0.84)
fig.savefig(f"{OUT}/sf1_phase_mix.png"); plt.close(fig)

# ---------------------------------------------------------------- page
n = len(D)
fmt = lambda v, d=1: f"{v:,.{d}f}"
fl = lambda name: FAMILY_LABEL.get(name, f"`{name}`")
top_fam = collections.Counter(r["top"][0][0] for r in D)
by_top = collections.defaultdict(list)
for r in D:
    by_top[r["top"][0][0]].append(r)
qlist = lambda rs: ", ".join(f"Q{r['q']}" for r in rs)
busy_sorted = sorted(D, key=lambda r: r["busy_pct_wall"])
h2d_max_q = max(D, key=lambda r: r["h2d_bytes"]); d2h_top = sorted(D, key=lambda r: -r["d2h_bytes"])[:2]
sp = sorted(D, key=lambda r: r["speedup"])
all_pass = all(r["pcie"] == "PASS" for r in D); all_sys = all(r["sysmem_nonzero"] == 0 and r["sysmem_pass"] for r in D)
all_neg = all(r["selftest_pass"] for r in D); all_exact = all(r["max_rel_diff"] == 0 for r in D)
modes = collections.Counter(r["compare_mode"] for r in D)
tot_k = sum(r["kernels"] for r in D); tot_lt5 = sum(r["lt5"] for r in D); tot_lt1 = sum(r["lt1wave"] for r in D)

L = []
A = L.append
A("# TPC-H Q2–Q22 at SF1 on Sirius, data pinned on GPU — cross-query summary\n")
A("**Generated by** `scripts/tpch_sf1/make_summary.py` from the data files in each `q<N>/` directory. Tables, counts and ranges are computed from those files (`summary/summary_data.json` holds the collected values); the few notes that quote a per-query report or its review say so.")
A("**Machine**: RTX 5070 (12 GB, 672 GB/s peak DRAM bandwidth, 48 SMs). **Engine**: Sirius (`sirius-duckdb` release build) with stock libcudf, CPU fallback disabled. **Profilers**: Nsight Compute 2025.2.1 (`--set full` on every kernel of one warm iteration) and Nsight Systems 2025.5.2.")
A("**Per-query detail**: each directory has `REPORT_tpch_q<N>_sf1.md` (links in §7), the ncu report, the nsys trace, and the evidence files named below.\n")
A("How to read the numbers: *warm ms* is the median of 12 timed iterations after 3 warmups (1 ms timer resolution). *GPU busy* is the union of kernel, memcpy and memset intervals in the nsys run, at real clocks. *ncu* times are serialized, clock-locked and taken with the L2 cache flushed before each kernel, so they are longer than real-clock times and their DRAM figures are cold-cache values. GPU busy (nsys run) and wall time (timing run) come from different runs.\n")

A("## 1. Headline\n")
A(f"- All {n} queries ran on the GPU path with CPU fallback disabled, and all {n} results equal DuckDB's on the CPU ({', '.join(f'{c} compared as `{m_}`' for m_, c in modes.items())}; maximum relative difference {max(r['max_rel_diff'] for r in D):g}).")
A(f"- PCIe verification: {'all ' + str(n) + ' queries PASS' if all_pass else 'NOT all queries pass'}; {'in every query, zero profiled kernels read host memory in place' if all_sys else 'some kernels read host memory'}; {'every negative control failed the verification as intended' if all_neg else 'a negative control did not behave as intended'} (§2).")
A(f"- Sirius is faster than DuckDB-CPU on every query: from {fmt(sp[0]['speedup'])}× (Q{sp[0]['q']}) to {fmt(sp[-1]['speedup'])}× (Q{sp[-1]['q']}), median {fmt(statistics.median(r['speedup'] for r in D))}× (§3).")
A(f"- The GPU is busy for a small part of the warm wall time: {fmt(busy_sorted[0]['busy_pct_wall'])}% (Q{busy_sorted[0]['q']}) to {fmt(busy_sorted[-1]['busy_pct_wall'])}% (Q{busy_sorted[-1]['q']}), median {fmt(statistics.median(r['busy_pct_wall'] for r in D))}% (§3).")
A(f"- A warm iteration launches {min(r['kernels'] for r in D)}–{max(r['kernels'] for r in D)} kernels. Across all queries, {tot_lt5:,} of {tot_k:,} profiled launches ({100*tot_lt5/tot_k:.0f}%) run under 5 µs (ncu) and {tot_lt1:,} ({100*tot_lt1/tot_k:.0f}%) launch less than one wave of CTAs (§4).")
A(f"- The largest kernel family by real-clock time is the merge-sort block sort in {len(by_top['DeviceMergeSortBlockSortKernel'])} queries, the libcudf expression interpreter (`compute_column_kernel`) in {len(by_top['compute_column_kernel'])}, and the `static_kernel` family in {len(by_top['static_kernel'])} (§5).\n")

A("## 2. PCIe verification\n")
A("Per measured (warm) iteration of the nsys run; copies are classified by source and destination memory kind. *Scans* is the number of `GPU_SCAN` operators, each of which must get its own pinned-entry assignment in every iteration. *Host-memory kernels* counts profiled kernels with non-zero SM system-memory-aperture sectors in the ncu report. Sources: `pcie.json`, `pcie_verification.txt`, `ncu_sysmem_check.txt`, `selftest_negative_control.txt`.\n")
A("| Query | Verdict | Tables | Scans | H2D copies | H2D bytes | Largest H2D | D2H bytes | Largest D2H | Result bytes (CSV) | Host-memory kernels | Negative control (table unpinned) |")
A("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
for r in D:
    A(f"| Q{r['q']} | {r['pcie']} | {r['tables']} | {r['scans']} | {r['h2d_copies']} | {r['h2d_bytes']:,} | {r['h2d_max']:,} | {r['d2h_bytes']:,} | {r['d2h_max']:,} | {r['result_bytes']:,} | {r['sysmem_nonzero']} of {r['sysmem_kernels']} | {'fails as intended' if r['selftest_pass'] else 'DID NOT FAIL'} (`{r['selftest_table']}`) |")
A("")
A(f"- No table data cross PCIe in the measured iterations of any query. What does cross is small control traffic plus the result: the largest host-to-device total is Q{h2d_max_q['q']}'s {h2d_max_q['h2d_bytes']:,} B in {h2d_max_q['h2d_copies']} copies (largest single copy {h2d_max_q['h2d_max']:,} B), and the largest device-to-host totals are Q{d2h_top[0]['q']} ({d2h_top[0]['d2h_bytes']:,} B for a {d2h_top[0]['result_rows']:,}-row result) and Q{d2h_top[1]['q']} ({d2h_top[1]['d2h_bytes']:,} B, {d2h_top[1]['result_rows']:,} rows).")
A(f"- In the measured iterations there were {sum(r['um_faults'] for r in D)} unified-memory page faults and {sum(r['decode_kernels'] for r in D)} Parquet-decode kernels over all {n} queries. {'Every query used the default byte limits.' if all(r['limits_default'] for r in D) else 'Some queries overrode a byte limit.'}")
A("- Limits of this proof, stated in each report: nsys never produced a GPU-side unified-memory fault table, so only CPU-side faults and managed-memory API calls are actually checked; for dynamic filters whose publication logs no transport line, the claim rests on the host-to-device byte bound and the zero host-memory reads; tables with fewer than 8,192 rows (`nation`, `region`) are too small for a byte limit and rest on the log and host-memory checks; Q21's negative control ran with a different plan (5 scans instead of 6).\n")

A("## 3. Timing\n")
A("![Warm query time: Sirius on GPU vs DuckDB on CPU](summary/sf1_wall_gpu_vs_cpu.png)\n")
A("![How much of the warm query time the GPU is busy](summary/sf1_gpu_busy_share.png)\n")
A("Sources: `timing.json` (warm and CPU medians, planning/engine split from 1 ms Sirius log stamps), `nsys_iteration_breakdown.json` (GPU busy). The planning and engine medians come from 1 ms stamps and do not always sum to the warm median.\n")
A("| Query | Warm ms (min–max) | DuckDB CPU ms | Speed-up | Planning ms | Engine ms | GPU busy ms | GPU busy / wall | Result rows |")
A("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
for r in D:
    A(f"| Q{r['q']} | {r['warm_ms']:g} ({r['warm_min']:g}–{r['warm_max']:g}) | {r['cpu_ms']:g} | {fmt(r['speedup'])}× | {r['planning_ms']:g} | {r['engine_ms']:g} | {r['gpu_busy_ms']:.3f} | {fmt(r['busy_pct_wall'])}% | {r['result_rows']:,} |")
A("")
A(f"- Planning takes {min(r['planning_ms'] for r in D):g}–{max(r['planning_ms'] for r in D):g} ms per query (median {statistics.median(r['planning_ms'] for r in D):g} ms), which is {fmt(statistics.median(100*r['planning_ms']/r['warm_ms'] for r in D), 0)}% of the warm wall time at the median.")
A(f"- GPU busy exceeds 2 ms only in {qlist([r for r in D if r['gpu_busy_ms'] > 2]) or 'no query'}; it is under 1 ms in {sum(r['gpu_busy_ms'] < 1 for r in D)} of {n} queries.\n")

A("## 4. Kernel profile\n")
A("Sources: `ncu_plan.json` (launch count; all queries took the `--set full`-on-everything branch), `ncu_warm_metrics.json` (per-kernel durations, waves, DRAM%), `phase_breakdown.json` (ncu total), `nsys_iteration_breakdown.json`. *Floor* is the pinned bytes read once at 672 GB/s; it is a lower bound on memory time, not a prediction. *Best DRAM%* is the highest single-kernel DRAM throughput as a share of peak (cold L2).\n")
A("| Query | Kernels / iteration | < 5 µs | < 1 wave | Single-CTA | ncu serialized µs | nsys kernel µs | Pinned MB | Pool high-water MB | Floor µs | GPU busy / floor | Wall / floor | Best DRAM% |")
A("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for r in D:
    A(f"| Q{r['q']} | {r['kernels']} | {r['lt5']} | {r['lt1wave']} | {r['grid1']} | {fmt(r['ncu_us'])} | {fmt(r['nsys_kernel_us'])} | {fmt(r['pinned_mb'])} | {fmt(r['pool_peak_mb'])} | {fmt(r['floor_us'])} | {fmt(r['busy_x_floor'])}× | {fmt(r['wall_x_floor'], 0)}× | {fmt(r['max_dram_pct'])} |")
A("")
A(f"- All {n} warm iterations stayed under the 1,000-launch threshold (policies: {', '.join(f'{c} × `{k}`' for k, c in collections.Counter(r['policy'] for r in D).items())}), so every kernel has full ncu metrics.")
A(f"- The pool high-water mark is a process-lifetime figure that includes the pin phase; the largest is {fmt(max(r['pool_peak_mb'] for r in D))} MB (Q{max(D, key=lambda r: r['pool_peak_mb'])['q']}) against a 3 GB pool.\n")

A("## 5. Where kernel time goes\n")
A("![Where kernel time goes, by phase](summary/sf1_phase_mix.png)\n")
A("Share of serialized ncu kernel time per phase group (the chart's data; `phase_breakdown.json`, grouped as in `make_summary.py`). Phases come from the kernel-name classifier `kclass.py`, which classifies on the full template name; known misfile: in Q21 it puts 249.6 µs of `insert_if_n` set builds under \"other\".\n")
A("| Query | " + " | ".join(PHASE_GROUPS) + " |")
A("|---|" + "---:|" * len(PHASE_GROUPS))
for r in D:
    tot = sum(r["phase_us"].values())
    A(f"| Q{r['q']} | " + " | ".join(f"{100*r['phase_us'][g]/tot:.1f}%" for g in PHASE_GROUPS) + " |")
A("")
A("Largest kernel families by real-clock kernel time (nsys, mean per measured iteration; `nsys_iteration_breakdown.json`). A family is every launch of one kernel function, so generic families such as `static_kernel` and `transform_kernel` mix several operators.\n")
A("| Query | #1 family | Share | #2 family | Share | #3 family | Share |")
A("|---|---|---:|---|---:|---|---:|")
for r in D:
    A(f"| Q{r['q']} | " + " | ".join(f"{fl(nm)} | {pct:.1f}%" for nm, _, pct in r["top"]) + " |")
A("")
A("Queries grouped by their largest family:\n")
for nm, rs in sorted(by_top.items(), key=lambda kv: -len(kv[1])):
    A(f"- **{fl(nm)}** ({len(rs)}): " + ", ".join(f"Q{r['q']} ({r['top'][0][2]:.1f}%)" for r in rs))
A("")

A("## 6. Cross-query observations\n")
A("These restate what the per-query reports establish; mechanisms are from their instruction-level sections and carry the same measured/inferred labels there.\n")
A(f"1. **Wall time is set by the host, not the GPU.** GPU busy is at most {fmt(busy_sorted[-1]['busy_pct_wall'])}% of the warm wall time (Q{busy_sorted[-1]['q']}) and under 20% in {sum(r['busy_pct_wall'] < 20 for r in D)} of {n} queries. The remainder is planning plus the engine window with the GPU idle; the reports attribute the idle part to per-operator stream synchronizations, pool allocations and small copies between kernels of a few µs (an inference from nsys call counts and CPU time).")
A(f"2. **Most launches are tiny.** {100*tot_lt5/tot_k:.0f}% of launches run under 5 µs and {100*tot_lt1/tot_k:.0f}% under one wave (measured). For those kernels launch and latency, not bandwidth, set the time (inferred).")
sortq = [r for r in D if r["top"][0][0] == "DeviceMergeSortBlockSortKernel"]
A(f"3. **Sorting is the largest kernel cost in {len(sortq)} queries**, in each case on few CTAs. Longest block-sort launch per query, from the full ncu pass (`ncu_warm_metrics.json`):")
A("")
A("   | Query | Family share (nsys) | Longest launch µs (ncu) | Grid (CTAs) | Active lanes of 32 | Barrier stall share | Long-scoreboard stall share |")
A("   |---|---:|---:|---:|---:|---:|---:|")
for r in sortq:
    k = r["longest_by_func"]["DeviceMergeSortBlockSortKernel"]
    A(f"   | Q{r['q']} | {r['top'][0][2]:.1f}% | {fmt(k['dur_us'])} | {k['grid']} | {fmt(k['lanes'])} | {fmt(k['barrier'])}% | {fmt(k['long_sb'])}% |")
A("")
gk = [r["longest_by_func"]["DeviceMergeSortBlockSortKernel"]["grid"] for r in sortq]
A(f"   These launches use {min(gk)}–{max(gk)} CTAs, so most of the 48 SMs are idle while they run. Where the launch is a single CTA, barrier waits dominate its stall samples; in the multi-CTA launches (Q3, Q16) long-scoreboard waits dominate. The reports trace the latter to dependent loads in cuDF's generic row comparator, including byte-wise string compares in Q16.")
ccq = [r for r in D if r["top"][0][0] == "compute_column_kernel"]
kk = [r["longest_by_func"]["compute_column_kernel"] for r in ccq]
A(f"4. **The libcudf expression interpreter (`compute_column_kernel`) is the largest family in {len(ccq)} queries** ({qlist(ccq)}). Its longest launch in each of those queries fills the GPU ({fmt(min(k['waves'] for k in kk))}–{fmt(max(k['waves'] for k in kk))} waves) with the load/store pipe {fmt(min(k['pipe_lsu'] for k in kk))}–{fmt(max(k['pipe_lsu'] for k in kk))}% busy while DRAM throughput is {fmt(min(k['dram_pct'] for k in kk))}–{fmt(max(k['dram_pct'] for k in kk))}% of peak (measured, cold L2). The reports read this as a kernel limited by instruction count and dependent descriptor loads, not by bandwidth, and attribute these launches to predicates evaluated over `lineitem` partitions (the launch-to-operator mapping is inferred from grid sizes).")
in3 = lambda f: [r for r in D if any(nm == f for nm, _, _ in r["top"])]
A(f"5. **Dynamic-filter probes and string handling are the next tier.** `fused_membership_mask_kernel` is among the three largest families in {len(in3('fused_membership_mask_kernel'))} queries ({qlist(in3('fused_membership_mask_kernel'))}); the `static_kernel` family, which the reports show to be led by `membership_probe_functor` launches in several queries, is in the top three in {len(in3('static_kernel'))}. The byte-per-lane string character gather `gather_chars_fn_char_parallel` is in the top three in {len(in3('gather_chars_fn_char_parallel'))} ({qlist(in3('gather_chars_fn_char_parallel'))}).")
lk = [r["longest"] for r in D]
A(f"6. **Bandwidth is rarely the limit for the kernels that matter.** The best single-kernel DRAM throughput in any query reaches {fmt(max(r['max_dram_pct'] for r in D))}% of peak (Q{max(D, key=lambda r: r['max_dram_pct'])['q']}), but the longest kernel of each query runs at {fmt(min(k['dram_pct'] for k in lk))}–{fmt(max(k['dram_pct'] for k in lk))}% of peak (median {fmt(statistics.median(k['dram_pct'] for k in lk))}%; measured, cold L2).")
A("7. Project rule kept in every report: no query-specific kernel fusion is recommended; optimization directions are general-purpose library or engine changes.\n")

A("## 7. Per-query reports\n")
A("| Query | Report | Largest family (real-clock share) |")
A("|---|---|---|")
for r in D:
    A(f"| Q{r['q']} | [REPORT_tpch_q{r['q']}_sf1.md](q{r['q']}/REPORT_tpch_q{r['q']}_sf1.md) | {fl(r['top'][0][0])} ({r['top'][0][2]:.1f}%) |")
A("")
A("## 8. Scope and caveats\n")
A("- Scale factor 1 only; Q1 was profiled separately (`q1/`, SF10). At SF1 kernel time scales with rows while per-launch and host costs do not, so these shares will shift at larger scale factors (not measured here).")
A("- Sirius ran with a 25% GPU pool and a 1 GB pinned-host pool (`scripts/tpch_sf1/sirius.yaml`) to keep ncu's per-kernel replay fast; no query downgraded or spilled.")
A("- Every report was reviewed against its data files by an independent agent and corrected; headline numbers and PCIe tables held, while corrections concentrated on instruction-level interpretation, derived arithmetic and inferred-versus-measured labels.")
A("- Timer resolution is 1 ms for wall-time figures; speed-ups and wall-time shares inherit that granularity.")
open(f"{R}/SUMMARY_tpch_sf1.md", "w").write("\n".join(L) + "\n")
print(f"wrote {R}/SUMMARY_tpch_sf1.md ({len(L)} lines), 3 charts and summary_data.json in {OUT}")
