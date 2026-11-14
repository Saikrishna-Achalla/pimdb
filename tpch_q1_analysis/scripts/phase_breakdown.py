"""Phase breakdown + top-kernel details from an extract_ncu.py JSON.
Usage: python3 -I phase_breakdown.py <ncu.json> <phase_out.txt> <details_out.txt> [n_top]"""
import json, sys, collections

src, out_phase, out_det = sys.argv[1:4]
NTOP = int(sys.argv[4]) if len(sys.argv) > 4 else 6
K = json.load(open(src))["kernels"]


def cat(n):
    if any(s in n for s in ("parquet::", "unsnap", "nvcomp", "decompress", "codec", "PageInfo")): return "parquet_decode"
    if any(s in n for s in ("groupby", "cuco", "insert_and_find")): return "hash_groupby"
    if "compute_column_kernel" in n or "ast::" in n: return "expression_eval(AST)"
    if "merge_sort" in n or "Sort" in n or "sort" in n: return "sort/order_by"
    if "Memcpy" in n or "concatenate" in n or "gather" in n: return "copy/concat/gather"
    if "Scan" in n or "Reduce" in n or "Select" in n or "Compact" in n: return "cub scan/select/reduce"
    return "other(transform/fill/misc)"


with open(out_phase, "w") as f:
    agg = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for k in K:
        a = agg[cat(k["name"])]; a[0] += 1; a[1] += k["dur_ns"]; a[2] += k["dram_bytes"]
    tot = sum(a[1] for a in agg.values())
    f.write(f"{'phase':28s} {'kernels':>7} {'time_us':>8} {'pct':>6} {'DRAM_MB':>8} {'GB/s':>6}\n")
    for c, (n, t, b) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        f.write(f"{c:28s} {n:7d} {t/1e3:8.1f} {100*t/tot:6.1f} {b/1e6:8.1f} {b/t:6.1f}\n")
    B = sum(k["dram_bytes"] for k in K)
    f.write(f"TOTAL kernels={len(K)} gpu_time_us={tot/1e3:.1f} dram_MB={B/1e6:.1f} avg_GB/s={B/tot:.1f}\n")
    dur = sorted(k["dur_ns"] for k in K)
    f.write(f"kernels <5us: {sum(x < 5000 for x in dur)}; <10us: {sum(x < 10000 for x in dur)}; "
            f"time in <10us kernels (us): {sum(x for x in dur if x < 10000)/1e3:.1f}\n")
    f.write("top-10 kernels share of GPU time: %.1f%%\n" % (100 * sum(dur[-10:]) / tot))
    lw = [k for k in K if (k["waves"] or 0) < 1]
    f.write(f"kernels <1 wave: {len(lw)}, {sum(k['dur_ns'] for k in lw)/1e3:.0f}us\n")

with open(out_det, "w") as f:
    for k in sorted(K, key=lambda k: -k["dur_ns"])[:NTOP]:
        s = k["stalls"]; t = sum(s.values()) or 1
        f.write(f"== id {k['id']} {k['name'][:150]}\n")
        f.write(f"  dur={k["dur_ns"]/1e3:.1f}us grid={k['grid']:.0f} blk={k['block']:.0f} regs={k['regs']:.0f} "
                f"smem={((k['smem_dyn'] or 0)+(k['smem_st'] or 0)):.0f}B occ ach/theo={k['occ_ach']:.1f}/{k['occ_theo']:.1f} "
                f"waves={k['waves']:.2f} ipc={k['ipc']:.2f} inst={k['inst']:.3g} thread_eff={k['thread_eff']:.1f}\n")
        f.write(f"  SM%={k['sm_pct']:.1f} Mem%={k['mem_pct']:.1f} DRAM%={k['dram_pct']:.1f} L1hit={k['l1_hit']:.1f} "
                f"L2hit={k['l2_hit']:.1f} dramMB={k['dram_bytes']/1e6:.1f}\n")
        f.write("  pipes%: " + " ".join(f"{p}={k['pipe_'+p]:.1f}" for p in ['alu', 'fma', 'lsu', 'adu', 'cbu', 'xu', 'uniform', 'fp64']) + "\n")
        f.write(f"  global ld_req={k['ldreq_glob']:.3g} st_req={k['streq_glob']:.3g} atom_req={k['atom_glob']:.3g} | "
                f"shared ld={k['ld_shared']:.3g} st={k['st_shared']:.3g} bank_conf={k['bank_conflicts']:.3g}\n")
        f.write("  stalls%: " + ", ".join(f"{r}={100*v/t:.1f}" for r, v in sorted(s.items(), key=lambda x: -x[1])[:7]) + "\n")
print(open(out_phase).read())
