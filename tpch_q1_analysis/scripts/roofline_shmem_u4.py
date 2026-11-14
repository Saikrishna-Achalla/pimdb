"""Instruction roofline for single_pass_shmem_aggs_kernel only, U=4 profile.
Usage: venv/bin/python -I scripts/roofline_shmem_u4.py"""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
ROOT = "/home/sai/cs254_project/tpch_q1_analysis"
K = [k for k in json.load(open(f"{ROOT}/traces/ncu_u4_warm_full.json"))["kernels"] if "single_pass_shmem_aggs" in k["name"]]
K.sort(key=lambda k: -k["dram_bytes"])
clk = K[0]["sm_clk_hz"]
peak_gips = 48 * 4 * clk / 1e9          # 48 SMs x 4 SMSPs x 1 warp-inst/clk
bw = 672.0                              # GB/s
x = np.logspace(-3, 2, 400)
plt.figure(figsize=(7, 4.6))
plt.loglog(x, np.minimum(peak_gips, x * bw), "k-", lw=1.5)
plt.axvline(peak_gips / bw, color="gray", ls=":", lw=1)
plt.text(peak_gips / bw * 1.1, 0.5, f"ridge {peak_gips/bw:.2f} inst/B", color="gray", fontsize=8)
plt.text(1.5e-3, 1.6, "672 GB/s DRAM", rotation=33, fontsize=8)
plt.text(5, peak_gips * 1.1, f"peak {peak_gips:.0f} G warp-inst/s", fontsize=8)
labels = ["large batch (118 MB)", "small batch (23 MB)", "merge (1 CTA)"]
for k, lab, c in zip(K, labels, ["#00798c", "#edae49", "#8d96a3"]):
    ai = k["inst"] / max(k["dram_bytes"], 1)
    gips = k["inst"] / k["dur_ns"]
    plt.loglog(ai, gips, "o", ms=9, color=c, label=f"{lab}: {k['dur_ns']/1e3:.0f} us, {k['dram_bytes']/k['dur_ns']:.0f} GB/s")
plt.xlabel("warp instructions per DRAM byte")
plt.ylabel("G warp-instructions / s")
plt.title(f"single_pass_shmem_aggs_kernel, U=4 (ncu, SM clock {clk/1e6:.0f} MHz)", fontsize=10)
plt.xlim(1e-3, 1e2); plt.ylim(1e-1, peak_gips * 3)
plt.legend(fontsize=8, loc="lower right"); plt.grid(True, which="both", alpha=0.2)
plt.tight_layout(); plt.savefig(f"{ROOT}/analysis/results/q1_u4/roofline_shmem_aggs_u4.png", dpi=150)
for k, lab in zip(K, labels):
    print(f"{lab}: AI={k['inst']/max(k['dram_bytes'],1):.3f} inst/B, {k['inst']/k['dur_ns']:.1f} G inst/s, ridge={peak_gips/bw:.2f}")
