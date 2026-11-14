"""Per-instruction hotspot + instruction-mix analysis from `ncu --page source --print-source sass --csv`.

Usage: python3 -I sass_hotspots.py <source.csv> <out_prefix>
Writes <out_prefix>_inst_inventory.csv (opcode class table: whole kernel, executed-weighted)
and prints: total executed, top stall-sample instructions, opcode-class mix, hot PC range.
"""
import csv, sys, re, collections

src, out = sys.argv[1], sys.argv[2]
rows = list(csv.reader(open(src)))
hdr_i = next(i for i, r in enumerate(rows) if r and r[0] == "Address")
h = rows[hdr_i]; c = {n: i for i, n in enumerate(h)}
ins = []
seen = set()
for r in rows[hdr_i + 1:]:
    if len(r) < len(h) or not r[0].startswith("0x"):
        continue
    # ncu omits columns a kernel cannot produce (e.g. "L1 Wavefronts Shared Excessive" without shared memory): treat as 0
    f = lambda n: float(r[c[n]] or 0) if n in c and r[c[n]] not in ("-", "") else 0.0
    if r[0] in seen:
        continue
    seen.add(r[0])
    sass = r[c["Source"]].strip()
    op = re.sub(r"^@!?U?P[T0-9]+\s+", "", sass).split(" ")[0].rstrip(";")
    ins.append(dict(pc=int(r[0], 16), sass=sass, op=op, exe=f("Instructions Executed"),
                    samp=f("Warp Stall Sampling (All Samples)"),
                    thr=f("Avg. Threads Executed"),
                    l2ex=f("L2 Theoretical Sectors Global Excessive"),
                    shconf=f("L1 Wavefronts Shared Excessive"),
                    st={n[6:]: f(n) for n in h if n.startswith("stall_") and "(Not Issued)" not in n and f(n) > 0}))
base = ins[0]["pc"]
tot_exe = sum(i["exe"] for i in ins); tot_s = sum(i["samp"] for i in ins)
print(f"static instructions={len(ins)}  executed(warp)={tot_exe:.4g}  stall samples={tot_s:.0f}")
live = [i for i in ins if i["exe"] > 0]
print(f"static instructions ever executed: {len(live)} ({100*len(live)/len(ins):.1f}% of the binary)")


def cls(op):
    o = op.split(".")[0]
    if o in ("LDG",): return "Global Load"
    if o in ("STG",): return "Global Store"
    if o in ("ATOMG", "ATOM", "RED", "REDG"): return "Global Atomic"
    if o in ("LDS", "LDSM"): return "Shared Load"
    if o in ("STS",): return "Shared Store"
    if o in ("ATOMS",): return "Shared Atomic"
    if o in ("LDC", "ULDC", "LDCU"): return "Const Load"
    if o in ("LDL", "STL"): return "Local (spill)"
    if o in ("FFMA", "FADD", "FMUL", "DFMA", "DADD", "DMUL", "HFMA2", "FSETP", "DSETP", "FMNMX", "MUFU", "F2F", "I2F", "F2I", "I2FP", "F2IP"): return "FP Arithmetic"
    if o in ("IMAD", "IADD3", "IADD", "LEA", "LOP3", "SHF", "IMNMX", "VIMNMX", "ISETP", "SEL", "PRMT", "POPC", "FLO", "BREV", "IABS", "SGXT", "BMSK", "IMUL", "IADD32I", "LOP", "LEA.HI", "ISCADD", "VIADD", "VIADDMNMX", "IDP", "IMNMX3", "UMOV"): return "Int Arithmetic"
    if o.startswith("U"): return "Uniform datapath"
    if o in ("SHFL", "VOTE", "VOTEU", "MATCH", "REDUX", "CREDUX"): return "Warp collective"
    if o in ("BRA", "BRX", "BRXU", "JMP", "JMX", "CALL", "RET", "EXIT", "BSSY", "BSYNC", "WARPSYNC", "BREAK", "YIELD", "ACQBULK", "NANOSLEEP"): return "Control Flow"
    if o in ("BAR", "MEMBAR", "ERRBAR", "DEPBAR", "CCTL", "FENCE"): return "Barrier/Fence"
    if o in ("MOV", "S2R", "S2UR", "CS2R", "NOP", "P2R", "R2P", "PLOP3", "R2UR", "MOV32I"): return "Move/Special"
    return "Other"


agg = collections.defaultdict(lambda: [0, 0.0, 0.0])
for i in ins:
    a = agg[cls(i["op"])]; a[0] += 1; a[1] += i["exe"]; a[2] += i["samp"]
with open(out + "_inst_inventory.csv", "w") as fo:
    w = csv.writer(fo); w.writerow(["class", "static_count", "executed_warp_inst", "pct_executed", "stall_samples", "pct_samples"])
    print(f"\n{'class':18s} {'static':>7} {'exec':>11} {'%exec':>6} {'%stall':>6}")
    for k, (n, e, s) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        w.writerow([k, n, int(e), f"{100*e/tot_exe:.2f}", int(s), f"{100*s/tot_s:.2f}"])
        print(f"{k:18s} {n:7d} {e:11.4g} {100*e/tot_exe:6.1f} {100*s/tot_s:6.1f}")

# hot PC window: smallest contiguous window holding 80% of stall samples
srt = sorted(ins, key=lambda i: -i["samp"])
print("\nTop 25 instructions by stall samples:")
for i in srt[:25]:
    top = ",".join(f"{k}={v:.0f}" for k, v in sorted(i["st"].items(), key=lambda kv: -kv[1])[:2])
    print(f"  +0x{i['pc']-base:05x} samp={i['samp']:6.0f} ({100*i['samp']/tot_s:4.1f}%) exe={i['exe']:9.0f} thr={i['thr']:4.1f} [{top}]  {i['sass'][:80]}")
hot = sorted(i["pc"] - base for i in srt if i["samp"] > 0.002 * tot_s)
print(f"\nhot PCs (>0.2% samples each) span +0x{hot[0]:x} .. +0x{hot[-1]:x}, n={len(hot)}")

# kernel-wide stall reasons from the per-instruction columns, and context windows around the 3 hottest PCs
# plus the 3 hottest by non-barrier samples (barrier samples land on the instruction after BAR.SYNC)
kst = collections.Counter()
for i in ins:
    kst.update(i["st"])
print("\nstall reasons (sum over instructions): " + ", ".join(f"{k}={100*v/max(1,sum(kst.values())):.1f}%" for k, v in kst.most_common(8)))
idx = {i["pc"]: n for n, i in enumerate(ins)}
nb = sorted(ins, key=lambda i: -(i["samp"] - i["st"].get("barrier", 0)))  # hottest by non-barrier stalls
ctx = srt[:3] + [i for i in nb[:3] if i not in srt[:3]]
for i in ctx:
    n = idx[i["pc"]]
    print(f"\ncontext around +0x{i['pc']-base:05x} (exe = warp-level executions, samp = stall samples):")
    for j in ins[max(0, n - 8): n + 3]:
        mark = ">>" if j is i else "  "
        print(f"  {mark} +0x{j['pc']-base:05x} exe={j['exe']:8.0f} samp={j['samp']:5.0f} thr={j['thr']:4.1f}  {j['sass'][:90]}")
