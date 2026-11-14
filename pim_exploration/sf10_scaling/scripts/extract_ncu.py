"""Per-kernel metrics for the warm iteration -> <results_dir>/ncu_warm_metrics.json + a printed summary.

Usage: python3 -I extract_ncu.py <results_dir>
Policy full_all          : profiles/q<N>_warm_full.ncu-rep holds every warm kernel with --set full.
Policy light_plus_families: profiles/q<N>_warm_light.ncu-rep (all warm kernels, light metrics) is merged with
                           profiles/q<N>_warm_families_full.ncu-rep (--set full, family regex). The two reports come
                           from different runs whose launch ORDER differs, so kernels are matched on the exact mangled
                           name + grid + block (ncu --print-kernel-base mangled), ties broken by closest duration.
Every kernel gets has_full, src_report, src_index (row index inside its source report; sass_top.py uses it).
All ncu numbers: kernels serialized, clocks locked to base, L2 flushed before every kernel (--cache-control all), so
DRAM bytes are cold-L2 traffic and tiny kernels look slower than at real clocks.
"""
import collections, csv, glob, io, json, os, re, subprocess, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from kclass import func_base, phase, operator

R = sys.argv[1]
plan = json.load(open(f"{R}/ncu_plan.json"))
WANT = {
    "dur_ns": "gpu__time_duration.sum", "sm_pct": "sm__throughput.avg.pct_of_peak_sustained_elapsed",
    "mem_pct": "gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed",
    "dram_pct": "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed",
    "dram_rd": "dram__bytes_op_read.sum", "dram_wr": "dram__bytes_op_write.sum",
    "l2_hit": "lts__t_sector_hit_rate.pct", "l1_hit": "l1tex__t_sector_hit_rate.pct",
    "occ_ach": "sm__warps_active.avg.pct_of_peak_sustained_active", "occ_theo": "sm__maximum_warps_per_active_cycle_pct",
    "waves": "launch__waves_per_multiprocessor", "grid": "launch__grid_size", "block": "launch__block_size",
    "regs": "launch__registers_per_thread", "smem_dyn": "launch__shared_mem_per_block_dynamic",
    "smem_st": "launch__shared_mem_per_block_static", "inst": "smsp__inst_executed.sum",
    "ipc": "sm__inst_executed.avg.per_cycle_active", "sm_clk_hz": "sm__cycles_elapsed.avg.per_second",
    "elapsed_cyc": "gpc__cycles_elapsed.max", "sm_active_cyc": "sm__cycles_active.avg",
    "atom_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_atom.sum", "red_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_red.sum",
    "ldreq_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum", "streq_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_st.sum",
    "atom_shared": "smsp__inst_executed_op_shared_atom.sum", "ld_shared": "smsp__sass_inst_executed_op_shared_ld.sum",
    "st_shared": "smsp__sass_inst_executed_op_shared_st.sum", "bank_conflicts": "l1tex__data_bank_conflicts_pipe_lsu_mem_shared.sum",
    "pipe_alu": "sm__inst_executed_pipe_alu.avg.pct_of_peak_sustained_active", "pipe_fma": "sm__inst_executed_pipe_fma.avg.pct_of_peak_sustained_active",
    "pipe_lsu": "sm__inst_executed_pipe_lsu.avg.pct_of_peak_sustained_active", "pipe_adu": "sm__inst_executed_pipe_adu.avg.pct_of_peak_sustained_active",
    "pipe_cbu": "sm__inst_executed_pipe_cbu.avg.pct_of_peak_sustained_active", "pipe_xu": "sm__inst_executed_pipe_xu.avg.pct_of_peak_sustained_active",
    "pipe_uniform": "sm__inst_executed_pipe_uniform.avg.pct_of_peak_sustained_active", "pipe_fp64": "sm__inst_executed_pipe_fp64.avg.pct_of_peak_sustained_active",
    "ld_glob": "smsp__sass_inst_executed_op_global_ld.sum", "st_glob": "smsp__sass_inst_executed_op_global_st.sum",
    "branch_eff": "smsp__sass_average_branch_targets_threads_uniform.pct", "thread_eff": "smsp__thread_inst_executed_per_inst_executed.ratio",
    "sm_active_max": "sm__cycles_active.max", "sm_active_min": "sm__cycles_active.min",
}
STALL = "smsp__pcsamp_warps_issue_stalled_"


def num(v):
    try:
        return float(v.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def load(rep):
    ncu = ["/usr/local/cuda/bin/ncu", "--import", rep, "--page", "raw", "--csv", "--print-units", "base"]
    raw = subprocess.run(ncu, capture_output=True, text=True, check=True).stdout
    mang = subprocess.run(ncu + ["--print-kernel-base", "mangled", "--metrics", "gpu__time_duration.sum"],
                          capture_output=True, text=True, check=True).stdout
    mrows = list(csv.DictReader(io.StringIO("\n".join(l for l in mang.splitlines() if l.startswith('"')))))[1:]
    rd = csv.reader(io.StringIO("\n".join(l for l in raw.splitlines() if l.startswith('"'))))
    hdr = next(rd); next(rd); col = {h: i for i, h in enumerate(hdr)}
    out = []
    for idx, r in enumerate(rd):
        k = {"id": int(r[col["ID"]]), "name": r[col["Kernel Name"]], "mangled": mrows[idx]["Kernel Name"],
             "src_report": os.path.basename(rep), "src_index": idx}
        assert mrows[idx]["ID"] == r[col["ID"]], "mangled/demangled exports disagree on row order"
        for key, m in WANT.items():
            k[key] = num(r[col[m]]) if m in col else None
        k["stalls"] = {h[len(STALL):]: num(r[i]) for h, i in col.items()
                       if h.startswith(STALL) and not h.endswith("_not_issued") and num(r[i])}
        k["has_full"] = k["occ_ach"] is not None  # achieved occupancy is only collected by --set full
        out.append(k)
    return out, [m for m in WANT.values() if m not in col]


rep = lambda kind: (glob.glob(f"{R}/profiles/q*_warm_{kind}.ncu-rep") or [None])[0]
match_info = None
if plan["policy"] == "full_all":
    K, missing_full = load(rep("full")); missing_light = None
else:
    K, missing_light = load(rep("light"))
    F, missing_full = load(rep("families_full"))
    key = lambda k: (k["mangled"], int(k["grid"] or 0), int(k["block"] or 0))
    free = collections.defaultdict(list)
    for i, k in enumerate(K):
        free[key(k)].append(i)
    worst = 0.0
    for f in F:
        cand = free[key(f)]
        if not cand:
            sys.exit(f"ERROR: family-report kernel {f['func'] if 'func' in f else f['name'][:80]} (grid {f['grid']}, block "
                     f"{f['block']}) has no unmatched light-report kernel with the same mangled name and launch shape")
        i = min(cand, key=lambda j: abs((K[j]["dur_ns"] or 0) - (f["dur_ns"] or 0)))
        cand.remove(i)
        worst = max(worst, abs((K[i]["dur_ns"] or 0) - (f["dur_ns"] or 0)) / max(1.0, K[i]["dur_ns"] or 0))
        K[i] = dict(f, id=K[i]["id"], name=K[i]["name"], light_dur_ns=K[i]["dur_ns"])
    match_info = {"matched": len(F), "max_rel_duration_diff_light_vs_full": worst}
clamped = []
for i, k in enumerate(K):
    for f in ("l1_hit", "l2_hit"):  # ncu sector hit rates can read slightly > 100% on tiny kernels (counter artifact)
        if k[f] is not None and k[f] > 100:
            k[f + "_raw"] = k[f]; k[f] = 100.0; clamped.append(f"pos{i}:{f}={k[f + '_raw']:.1f}")
    k["pos"] = i; k["func"] = func_base(k["name"]); k["phase"] = phase(k["name"]); k["operator"] = operator(k["name"])
    if k["elapsed_cyc"] and k["sm_active_cyc"]:
        k["sm_active_frac"] = k["sm_active_cyc"] / k["elapsed_cyc"]
    b = (k["dram_rd"] or 0) + (k["dram_wr"] or 0)
    k["dram_bytes"] = b
    k["achieved_bw_gbs"] = b / k["dur_ns"] if k["dur_ns"] else None
    if k["dram_pct"] is None and k["achieved_bw_gbs"] is not None:  # light-only kernels: derive from bytes / time
        k["dram_pct"] = 100 * k["achieved_bw_gbs"] / 672.0
    k["inst_per_byte"] = (k["inst"] / b) if (b and k["inst"]) else None
json.dump({"policy": plan["policy"], "missing_metrics": missing_full, "missing_metrics_light": missing_light,
           "family_match": match_info, "ncu_conditions": "serialized, clocks locked to base, L2 flushed before each kernel", "clamped_hit_rates": clamped, "kernels": K}, open(f"{R}/ncu_warm_metrics.json", "w"), indent=1)

tot = sum(k["dur_ns"] for k in K)
print("ncu conditions: kernels serialized, SM clocks locked to base, L2 flushed before each kernel (--cache-control all):"
      " DRAM bytes are cold-L2 traffic; durations of tiny kernels are inflated vs real clocks (use nsys for those)")
print(f"policy={plan['policy']} kernels={len(K)} (full metrics: {sum(k['has_full'] for k in K)}) gpu_time_us={tot/1e3:.1f} "
      f"dram_MB={sum(k['dram_bytes'] for k in K)/1e6:.2f} missing_metrics full={missing_full} light={missing_light} "
      f"family_match={match_info}")
print(f"hit rates > 100% clamped to 100 (raw kept as *_raw): {clamped or 'none'}")
print(f"{'pos':>3} {'kernel':34s} {'us':>7} {'%':>5} {'grid':>6} {'blk':>4} {'SM%':>5} {'DRAM%':>5} {'GB/s':>6} {'occ%':>5} {'waves':>5} {'MB':>6}")
for k in sorted(K, key=lambda k: -k["dur_ns"])[:25]:
    f = lambda x: x or 0
    print(f"{k['pos']:3d} {k['func'][:34]:34s} {k['dur_ns']/1e3:7.1f} {100*k['dur_ns']/tot:5.1f} {int(f(k['grid'])):6d} {int(f(k['block'])):4d} "
          f"{f(k['sm_pct']):5.1f} {f(k['dram_pct']):5.1f} {f(k['achieved_bw_gbs']):6.1f} {f(k['occ_ach']):5.1f} {f(k['waves']):5.2f} {k['dram_bytes']/1e6:6.2f}")
agg = collections.Counter()
for k in K:
    s = sum(k["stalls"].values())
    for r, v in k["stalls"].items():
        agg[r] += k["dur_ns"] * v / s if s else 0
st = sum(agg.values()) or 1
print("time-weighted stall mix (kernels with full metrics):", ", ".join(f"{r}={100*v/st:.1f}%" for r, v in agg.most_common(8)))
clk = sorted(k["sm_clk_hz"] or 0 for k in K)[len(K) // 2]
print(f"sm clock (MHz) median: {clk/1e6:.0f}")
