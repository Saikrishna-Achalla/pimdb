#!/usr/bin/env python3
"""Per-command power / energy from PrimePower's per-cycle waveform (.out, interval = one clock).
Cycle t (VCD starts at cycle WIN0) is attributed to the command in stage 2 during that cycle, C[t-1] (its inputs are
applied at the start of cycle t and its state write happens at the rising edge mid-cycle).  Approximation: the same edge
also captures X of command t (stage 1) when HAS_XREG = 1.
usage: per_op.py <pwr_wave.out> <vec dir> <period_ns> [WIN0=100]"""
import sys, collections
OPS = ["NOP", "PWGB", "PCMP", "PLD_ROW", "PLD_GB", "PCC", "PSEL", "PMC", "PRD"]
wave, vec, per = sys.argv[1], sys.argv[2], float(sys.argv[3])
win0 = int(sys.argv[4]) if len(sys.argv) > 4 else 100
C = [int(l, 16) for l in open(vec + "/ctrl.hex")]
vals = []; t = None
for l in open(wave):
    l = l.strip()
    if not l or l[0] in ";.": continue
    f = l.split()
    if len(f) == 1: t = int(f[0])
    elif t is not None: vals.append((t, float(f[1])))
t0 = vals[0][0]; step = round(per * 1000)
acc = collections.defaultdict(lambda: [0, 0.0])
tot = []
for (tm, p) in vals:
    k = round((tm - t0) / step); cyc = win0 + k
    if cyc - 1 >= len(C) or cyc < 1: continue
    op = C[cyc - 1] & 0xF
    acc[OPS[op] if op < len(OPS) else "op%d" % op][0] += 1
    acc[OPS[op] if op < len(OPS) else "op%d" % op][1] += p
    tot.append(p)
mean = sum(tot) / len(tot)
print(f"cycles {len(tot)}  mean power {mean*1e3:.4f} mW  energy/slot {mean*per*1e3:.3f} pJ")
for k in OPS:
    if k in acc:
        n, s = acc[k]; m = s / n
        print(f"  {k:8s} n={n:6d} ({100*n/len(tot):4.1f}%)  {m*1e3:7.4f} mW  {m*per*1e3:7.3f} pJ/command")
