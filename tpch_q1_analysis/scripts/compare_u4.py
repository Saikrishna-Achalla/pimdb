"""Compare Q1 warm-query ncu results: unpatched libcudf (same toolchain) vs U=4 row-unrolled shmem aggs.
Usage: venv/bin/python -I scripts/compare_u4.py <orig.json> <u4.json> <out_dir>
Writes comparison.txt and q1_u4_vs_orig.png into out_dir."""
import json, sys, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

o_path, u_path, out = sys.argv[1:4]
O = sorted(json.load(open(o_path))["kernels"], key=lambda k: k["id"])
U = sorted(json.load(open(u_path))["kernels"], key=lambda k: k["id"])


def phase(n):
    if "single_pass_shmem_aggs" in n: return "group-by: shmem aggs (patched)"
    if any(s in n for s in ("groupby", "cuco", "insert_and_find")): return "group-by: other"
    if "compute_column_kernel" in n or "ast::" in n: return "expression (AST)"
    if "merge_sort" in n or "Sort" in n or "sort" in n: return "sort"
    if "Memcpy" in n or "concatenate" in n or "gather" in n: return "copy/concat/gather"
    if "Scan" in n or "Reduce" in n or "Select" in n or "Compact" in n: return "cub scan/select/reduce"
    return "other"


def stalls(ks):
    s = collections.Counter()
    for k in ks: s.update(k["stalls"])
    t = sum(s.values()) or 1
    return {r: 100 * v / t for r, v in s.most_common(6)}


lines = []
w = lines.append
w(f"kernels: orig={len(O)} u4={len(U)}")
to, tu = sum(k["dur_ns"] for k in O), sum(k["dur_ns"] for k in U)
w(f"total GPU kernel time (ncu, serialized): orig={to/1e3:.1f} us  u4={tu/1e3:.1f} us  delta={(to-tu)/1e3:+.1f} us ({100*(to-tu)/to:.1f}%)")
w(f"total DRAM: orig={sum(k['dram_bytes'] for k in O)/1e6:.1f} MB  u4={sum(k['dram_bytes'] for k in U)/1e6:.1f} MB")
w("")
po, pu = collections.defaultdict(float), collections.defaultdict(float)
for k in O: po[phase(k["name"])] += k["dur_ns"]
for k in U: pu[phase(k["name"])] += k["dur_ns"]
w(f"{'phase':32s} {'orig_us':>9} {'u4_us':>9} {'speedup':>8}")
for p in sorted(po, key=lambda p: -po[p]):
    w(f"{p:32s} {po[p]/1e3:9.1f} {pu[p]/1e3:9.1f} {po[p]/max(pu[p],1):7.2f}x")
w("")
# Pair launches by batch, not run order (the two runs process the row batches in different orders):
# largest DRAM traffic first = large batch, then small batch, then the final merge launch.
ao = sorted([k for k in O if "single_pass_shmem_aggs" in k["name"]], key=lambda k: -k["dram_bytes"])
au = sorted([k for k in U if "single_pass_shmem_aggs" in k["name"]], key=lambda k: -k["dram_bytes"])
w("single_pass_shmem_aggs_kernel launches (paired by batch: large, small, merge):")
w(f"{'':5s} {'us':>8} {'regs':>5} {'grid':>5} {'occ_ach':>7} {'occ_th':>6} {'DRAM_MB':>8} {'GB/s':>6} {'ipc':>5} {'warp_inst':>10}")
for tag, ks in (("orig", ao), ("u4", au)):
    for k in ks:
        w(f"{tag:5s} {k['dur_ns']/1e3:8.1f} {k['regs']:5.0f} {k['grid']:5.0f} {k['occ_ach']:7.1f} {k['occ_theo']:6.1f} "
          f"{k['dram_bytes']/1e6:8.1f} {k['dram_bytes']/k['dur_ns']:6.1f} {k['ipc']:5.2f} {k['inst']:10.3g}")
so, su = sum(k["dur_ns"] for k in ao), sum(k["dur_ns"] for k in au)
w(f"shmem aggs total: orig={so/1e3:.1f} us  u4={su/1e3:.1f} us  speedup={so/su:.2f}x  saved={(so-su)/1e3:.1f} us")
w("stalls orig: " + ", ".join(f"{r}={v:.0f}%" for r, v in stalls(ao).items()))
w("stalls u4:   " + ", ".join(f"{r}={v:.0f}%" for r, v in stalls(au).items()))
txt = "\n".join(lines)
open(f"{out}/comparison.txt", "w").write(txt + "\n")
print(txt)

fig, axs = plt.subplots(1, 2, figsize=(11, 3.8))
ph = sorted(po, key=lambda p: po[p])
y = range(len(ph))
axs[0].barh([i + 0.2 for i in y], [po[p] / 1e3 for p in ph], height=0.4, color="#8d96a3", label="unpatched")
axs[0].barh([i - 0.2 for i in y], [pu[p] / 1e3 for p in ph], height=0.4, color="#00798c", label="U=4")
axs[0].set_yticks(list(y)); axs[0].set_yticklabels(ph, fontsize=8)
axs[0].set_xlabel("GPU time (us, ncu serialized)"); axs[0].legend(fontsize=8)
axs[0].set_title(f"Q1 warm query by phase: {to/1e3:.0f} -> {tu/1e3:.0f} us", fontsize=10)
lab = [f"large batch\n({ao[0]['dram_bytes']/1e6:.0f} MB)", f"small batch\n({ao[1]['dram_bytes']/1e6:.0f} MB)", "merge\n(1 CTA)"][:len(ao)]
x = range(len(lab))
axs[1].bar([i - 0.2 for i in x], [k["dur_ns"] / 1e3 for k in ao], width=0.4, color="#8d96a3", label="unpatched")
axs[1].bar([i + 0.2 for i in x], [k["dur_ns"] / 1e3 for k in au], width=0.4, color="#00798c", label="U=4")
for i, (a, b) in enumerate(zip(ao, au)):
    axs[1].text(i + 0.2, b["dur_ns"] / 1e3, f"{a['dur_ns']/b['dur_ns']:.2f}x", ha="center", va="bottom", fontsize=8)
axs[1].set_xticks(list(x)); axs[1].set_xticklabels(lab)
axs[1].set_ylabel("us"); axs[1].legend(fontsize=8)
axs[1].set_title(f"single_pass_shmem_aggs_kernel: {so/1e3:.0f} -> {su/1e3:.0f} us ({so/su:.2f}x)", fontsize=10)
plt.tight_layout(); plt.savefig(f"{out}/q1_u4_vs_orig.png", dpi=150)
