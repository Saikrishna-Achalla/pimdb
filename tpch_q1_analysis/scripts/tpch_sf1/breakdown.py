"""Phase / operator / family breakdowns and top-kernel details from ncu_warm_metrics.json.

Usage: python3 -I breakdown.py <results_dir> [n_top=8]
Writes phase_breakdown.txt/.json, operator_breakdown.txt, top_kernel_details.txt.
"""
import collections, json, sys

R = sys.argv[1]; NTOP = int(sys.argv[2]) if len(sys.argv) > 2 else 8
K = json.load(open(f"{R}/ncu_warm_metrics.json"))["kernels"]
tot = sum(k["dur_ns"] for k in K)
B = sum(k["dram_bytes"] for k in K)
SMS = 48


def table(key, title):
    a = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for k in K:
        x = a[k[key]]; x[0] += 1; x[1] += k["dur_ns"]; x[2] += k["dram_bytes"]
    rows = sorted(a.items(), key=lambda kv: -kv[1][1])
    s = f"{title:44s} {'kernels':>7} {'time_us':>9} {'pct':>6} {'DRAM_MB':>8} {'GB/s':>6}\n"
    for c, (n, t, b) in rows:
        s += f"{c[:44]:44s} {n:7d} {t/1e3:9.1f} {100*t/tot:6.1f} {b/1e6:8.2f} {b/t if t else 0:6.1f}\n"
    return s, rows


s, rows = table("phase", "phase")
d = sorted(k["dur_ns"] for k in K)
sub = [k for k in K if (k.get("waves") or 0) < 1]
foot = (f"TOTAL kernels={len(K)} gpu_time_us={tot/1e3:.1f} dram_MB={B/1e6:.2f} avg_GB/s={B/tot:.1f} (ncu: serialized, clock-locked, L2 flushed before each kernel -> DRAM bytes are cold-L2 traffic)\n"
        f"kernels <5us: {sum(x < 5e3 for x in d)}; <10us: {sum(x < 1e4 for x in d)}; time in <10us kernels: {sum(x for x in d if x < 1e4)/1e3:.1f} us "
        f"({100*sum(x for x in d if x < 1e4)/tot:.1f}%)\n"
        f"kernels with < 1 wave ({SMS} SMs): {len(sub)} ({sum(k['dur_ns'] for k in sub)/1e3:.1f} us); grid < {SMS} CTAs: "
        f"{sum((k.get('grid') or 0) < SMS for k in K)}\n"
        f"top-10 kernels share of GPU time: {100*sum(d[-10:])/tot:.1f}%\n")
open(f"{R}/phase_breakdown.txt", "w").write(s + foot)
json.dump({"total_us": tot / 1e3, "kernels": len(K), "phases": [{"phase": c, "kernels": n, "time_us": t / 1e3, "pct": 100 * t / tot,
           "dram_MB": b / 1e6} for c, (n, t, b) in rows]}, open(f"{R}/phase_breakdown.json", "w"), indent=1)
s2, _ = table("operator", "operator")
s3, _ = table("func", "family (function base name)")
open(f"{R}/operator_breakdown.txt", "w").write(s2 + "\n" + s3)


def g(k, f, fmt="{:.1f}"):
    v = k.get(f)
    return "n/a" if v is None else fmt.format(v)


with open(f"{R}/top_kernel_details.txt", "w") as f:
    f.write(f"Top {NTOP} warm-iteration kernels by ncu duration (of {len(K)}; total {tot/1e3:.1f} us)\n")
    f.write("ncu conditions: kernels serialized, SM clocks locked to base, L2 flushed before each kernel (--cache-control all): "
            "DRAM bytes and hit rates are cold-L2 values, not what the kernel sees inside a real query.\n")
    for k in sorted(K, key=lambda k: -k["dur_ns"])[:NTOP]:
        s = k["stalls"]; st = sum(s.values()) or 1
        f.write(f"== pos {k['pos']} [{k['phase']} / {k['operator']}] {k['func']}  ({100*k['dur_ns']/tot:.1f}% of GPU time)\n")
        f.write(f"   {k['name'][:220]}\n")
        f.write(f"  dur={k['dur_ns']/1e3:.1f}us grid={g(k,'grid','{:.0f}')} blk={g(k,'block','{:.0f}')} regs={g(k,'regs','{:.0f}')} "
                f"smem={(k.get('smem_dyn') or 0)+(k.get('smem_st') or 0):.0f}B occ ach/theo={g(k,'occ_ach')}/{g(k,'occ_theo')} "
                f"waves={g(k,'waves','{:.2f}')} ipc={g(k,'ipc','{:.2f}')} inst={g(k,'inst','{:.3g}')} active_lanes_per_inst(of 32)={g(k,'thread_eff')}\n")
        f.write(f"  SM%={g(k,'sm_pct')} Mem%={g(k,'mem_pct')} DRAM%={g(k,'dram_pct')} DRAM={k['dram_bytes']/1e6:.2f}MB "
                f"({g(k,'achieved_bw_gbs')} GB/s) L1hit={g(k,'l1_hit')} L2hit={g(k,'l2_hit')} "
                f"SM busy max/avg={(k.get('sm_active_max') or 0)/(k.get('sm_active_cyc') or 1):.2f} active_frac={g(k,'sm_active_frac','{:.2f}')}\n")
        f.write("  pipes%: " + " ".join(f"{p}={g(k,'pipe_'+p)}" for p in ["alu", "fma", "lsu", "adu", "cbu", "xu", "uniform", "fp64"]) + "\n")
        f.write(f"  global ld_req={g(k,'ldreq_glob','{:.3g}')} st_req={g(k,'streq_glob','{:.3g}')} atom={g(k,'atom_glob','{:.3g}')} | "
                f"shared ld={g(k,'ld_shared','{:.3g}')} st={g(k,'st_shared','{:.3g}')} bank_conf={g(k,'bank_conflicts','{:.3g}')}\n")
        f.write("  stalls%: " + (", ".join(f"{r}={100*v/st:.1f}" for r, v in sorted(s.items(), key=lambda x: -x[1])[:8]) or "n/a (light metrics only)") + "\n")
print(open(f"{R}/phase_breakdown.txt").read()); print(s2)
