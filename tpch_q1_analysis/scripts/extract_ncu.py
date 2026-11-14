"""Extract per-kernel metrics from the Q1 warm ncu report into JSON + a summary table.

Usage: python3 -I extract_ncu.py <report.ncu-rep> <out.json>
Dumps `ncu --import --page raw --csv` once, keeps the metrics needed for the
bottleneck survey, roofline, and stall analysis.
"""
import csv, io, json, re, subprocess, sys, collections

REP, OUT = sys.argv[1], sys.argv[2]
raw = subprocess.run(["/usr/local/cuda/bin/ncu", "--import", REP, "--page", "raw", "--csv",
                      "--print-units", "base"], capture_output=True, text=True, check=True).stdout
lines = [l for l in raw.splitlines() if l.startswith('"')]
rd = csv.reader(io.StringIO("\n".join(lines)))
header = next(rd); units = next(rd)
col = {h: i for i, h in enumerate(header)}

WANT = {
    "dur_ns": "gpu__time_duration.sum",
    "sm_pct": "sm__throughput.avg.pct_of_peak_sustained_elapsed",
    "mem_pct": "gpu__compute_memory_throughput.avg.pct_of_peak_sustained_elapsed",
    "dram_pct": "gpu__dram_throughput.avg.pct_of_peak_sustained_elapsed",
    "dram_rd": "dram__bytes_op_read.sum",
    "dram_wr": "dram__bytes_op_write.sum",
    "l2_hit": "lts__t_sector_hit_rate.pct",
    "l1_hit": "l1tex__t_sector_hit_rate.pct",
    "occ_ach": "sm__warps_active.avg.pct_of_peak_sustained_active",
    "occ_theo": "sm__maximum_warps_per_active_cycle_pct",
    "waves": "launch__waves_per_multiprocessor",
    "grid": "launch__grid_size",
    "block": "launch__block_size",
    "regs": "launch__registers_per_thread",
    "smem_dyn": "launch__shared_mem_per_block_dynamic",
    "smem_st": "launch__shared_mem_per_block_static",
    "inst": "smsp__inst_executed.sum",
    "ipc": "sm__inst_executed.avg.per_cycle_active",
    "sm_clk_hz": "sm__cycles_elapsed.avg.per_second",
    "elapsed_cyc": "gpc__cycles_elapsed.max",
    "sm_active_pct": "sm__cycles_active.avg",  # cycles; ratio computed below
    "thread_inst": "smsp__thread_inst_executed.sum",
    "atom_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_atom.sum",
    "red_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_red.sum",
    "ldreq_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_ld.sum",
    "streq_glob": "l1tex__t_requests_pipe_lsu_mem_global_op_st.sum",
    "atom_shared": "smsp__inst_executed_op_shared_atom.sum",
    "ld_shared": "smsp__sass_inst_executed_op_shared_ld.sum",
    "st_shared": "smsp__sass_inst_executed_op_shared_st.sum",
    "l2_atom_sectors": "lts__t_sectors_srcunit_tex_op_atom.sum",
    "l2_red_sectors": "lts__t_sectors_srcunit_tex_op_red.sum",
    "bank_conflicts": "l1tex__data_bank_conflicts_pipe_lsu_mem_shared.sum",
    "pipe_alu": "sm__inst_executed_pipe_alu.avg.pct_of_peak_sustained_active",
    "pipe_fma": "sm__inst_executed_pipe_fma.avg.pct_of_peak_sustained_active",
    "pipe_lsu": "sm__inst_executed_pipe_lsu.avg.pct_of_peak_sustained_active",
    "pipe_adu": "sm__inst_executed_pipe_adu.avg.pct_of_peak_sustained_active",
    "pipe_cbu": "sm__inst_executed_pipe_cbu.avg.pct_of_peak_sustained_active",
    "pipe_xu": "sm__inst_executed_pipe_xu.avg.pct_of_peak_sustained_active",
    "pipe_uniform": "sm__inst_executed_pipe_uniform.avg.pct_of_peak_sustained_active",
    "pipe_fp64": "sm__inst_executed_pipe_fp64.avg.pct_of_peak_sustained_active",
    "ld_glob": "smsp__sass_inst_executed_op_global_ld.sum",
    "st_glob": "smsp__sass_inst_executed_op_global_st.sum",
    "branch_eff": "smsp__sass_average_branch_targets_threads_uniform.pct",
    "thread_eff": "smsp__thread_inst_executed_per_inst_executed.ratio",
}
STALL_PREFIX = "smsp__pcsamp_warps_issue_stalled_"


def num(v):
    v = v.replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


kernels = []
for r in rd:
    k = {"id": int(r[col["ID"]]), "name": r[col["Kernel Name"]]}
    for key, m in WANT.items():
        k[key] = num(r[col[m]]) if m in col else None
    stalls = {}
    for h, i in col.items():
        if h.startswith(STALL_PREFIX) and not h.endswith("_not_issued"):
            v = num(r[i])
            if v:
                stalls[h[len(STALL_PREFIX):]] = v
    k["stalls"] = stalls
    if k["elapsed_cyc"] and k["sm_active_pct"]:
        k["sm_active_frac"] = k["sm_active_pct"] / k["elapsed_cyc"]
    b = (k["dram_rd"] or 0) + (k["dram_wr"] or 0)
    ops = k["thread_inst"] or 0  # thread-level instructions (integer-dominated workload)
    k["dram_bytes"] = b
    k["ops"] = ops
    k["ai"] = ops / b if b else None
    k["achieved_bw_gbs"] = b / k["dur_ns"] if k["dur_ns"] else None
    k["achieved_gops"] = ops / k["dur_ns"] if k["dur_ns"] else None
    kernels.append(k)

missing = [m for m in WANT.values() if m not in col]
json.dump({"missing_metrics": missing, "kernels": kernels}, open(OUT, "w"), indent=1)


def short(n):
    n = n.replace("<unnamed>::", "").replace("(anonymous namespace)::", "")
    n = re.sub(r"\(.*$", "", n)
    n = re.sub(r"^void ", "", n)
    n = re.sub(r"<.*", "", n)
    return n.split("::")[-1]


tot = sum(k["dur_ns"] for k in kernels)
print(f"kernels={len(kernels)} gpu_time_us={tot/1e3:.1f} missing_metrics={missing}")
print(f"{'#':>3} {'kernel':38s} {'us':>7} {'%':>5} {'grid':>6} {'blk':>4} {'SM%':>5} {'Mem%':>5} {'DRAM%':>5} {'GB/s':>6} {'occ%':>5} {'waves':>5} {'MB':>6}")
for k in sorted(kernels, key=lambda k: -k["dur_ns"])[:25]:
    print(f"{k['id']:3d} {short(k['name'])[:38]:38s} {k['dur_ns']/1e3:7.1f} {100*k['dur_ns']/tot:5.1f} "
          f"{int(k['grid'] or 0):6d} {int(k['block'] or 0):4d} {k['sm_pct'] or 0:5.1f} {k['mem_pct'] or 0:5.1f} "
          f"{k['dram_pct'] or 0:5.1f} {k['achieved_bw_gbs'] or 0:6.1f} {k['occ_ach'] or 0:5.1f} {k['waves'] or 0:5.2f} "
          f"{k['dram_bytes']/1e6:6.1f}")
# time-weighted stall breakdown over all kernels
agg = collections.Counter()
for k in kernels:
    s = sum(k["stalls"].values())
    for r, v in k["stalls"].items():
        agg[r] += k["dur_ns"] * v / s if s else 0
st = sum(agg.values())
print("time-weighted stall mix:", ", ".join(f"{r}={100*v/st:.1f}%" for r, v in agg.most_common(8)))
print(f"sm clock (MHz) median: {sorted(k['sm_clk_hz'] or 0 for k in kernels)[len(kernels)//2]/1e6:.0f}")
