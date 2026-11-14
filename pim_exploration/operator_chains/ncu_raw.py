"""Extra per-kernel counters from the existing ncu reports (CPU-only `ncu --import`, no GPU, no new profiling).

ncu_warm_metrics.json has dram_rd/dram_wr only. With the L2 flushed before each kernel, reads come from DRAM, but
writes land in the 48 MB L2 and are mostly NOT written back during the kernel, so dram_wr ~ 0 for most kernels and
is useless as the size of an intermediate. This script adds, per warm kernel (same row order as the report, i.e.
ncu_warm_metrics.json src_index):
  st_bytes  = l1tex__t_sectors_pipe_lsu_mem_global_op_st.sum * 32   (bytes the SMs store to global memory)
  ld_bytes  = l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum * 32   (bytes the SMs load from global memory)
  atom_bytes= (global atom + red sectors) * 32
  l2_wr_bytes = lts__t_sectors_srcunit_tex_op_write.sum * 32        (writes arriving at L2 from the SMs)
  l2_rd_bytes = lts__t_sectors_srcunit_tex_op_read.sum * 32
  dram_rd, dram_wr (re-read, for cross-check)
Usage: python -I ncu_raw.py [q ...]   -> ncu_raw/q<N>.json
"""
import csv, io, json, os, subprocess, sys

RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ncu_raw")
os.makedirs(OUT, exist_ok=True)
M = {"st_sec": "l1tex__t_sectors_pipe_lsu_mem_global_op_st.sum", "ld_sec": "l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum",
     "atom_sec": "l1tex__t_sectors_pipe_lsu_mem_global_op_atom.sum", "red_sec": "l1tex__t_sectors_pipe_lsu_mem_global_op_red.sum",
     "l2_wr_sec": "lts__t_sectors_srcunit_tex_op_write.sum", "l2_rd_sec": "lts__t_sectors_srcunit_tex_op_read.sum",
     "dram_rd": "dram__bytes_op_read.sum", "dram_wr": "dram__bytes_op_write.sum"}


def num(v, unit):
    v = v.replace(",", "")
    try:
        x = float(v)
    except ValueError:
        return None
    return x * {"Kbyte": 1e3, "Mbyte": 1e6, "Gbyte": 1e9, "byte": 1}.get(unit, 1) if unit else x


qs = [int(a) for a in sys.argv[1:]] or list(range(2, 23))
for q in qs:
    rep = f"{RES}/q{q}/profiles/q{q}_warm_full.ncu-rep"
    txt = subprocess.run(["/usr/local/cuda/bin/ncu", "--import", rep, "--page", "raw", "--csv", "--metrics", ",".join(M.values())],
                         capture_output=True, text=True).stdout
    rows = list(csv.reader(io.StringIO(txt)))
    hdr, units, data = rows[0], rows[1], rows[2:]
    ix = {h: i for i, h in enumerate(hdr)}
    out = []
    for j, r in enumerate(data):
        d = {"src_index": j, "mangled_or_name": r[ix["Kernel Name"]][:200]}
        for k, m in M.items():
            d[k] = num(r[ix[m]], units[ix[m]])
        d["st_bytes"] = (d["st_sec"] or 0) * 32
        d["ld_bytes"] = (d["ld_sec"] or 0) * 32
        d["atom_bytes"] = ((d["atom_sec"] or 0) + (d["red_sec"] or 0)) * 32
        d["l2_wr_bytes"] = (d["l2_wr_sec"] or 0) * 32
        d["l2_rd_bytes"] = (d["l2_rd_sec"] or 0) * 32
        out.append(d)
    json.dump(out, open(f"{OUT}/q{q}.json", "w"))
    print(q, len(out), "kernels")
