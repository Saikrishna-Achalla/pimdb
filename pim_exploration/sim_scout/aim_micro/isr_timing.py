#!/usr/bin/env python3
"""Per-ISR timing microbenchmarks on the (patched) AiM simulator built under sim_scout/aim_build/head.
For each ISR: cycles of a trace with N back-to-back copies (same row, or a new row each time), minus an empty
trace, divided by N. Output: aim_micro/isr_timing.txt.  Run: python3 isr_timing.py"""
import os, re, subprocess
S = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.join(S, "..", "aim_build", "head", "build", "ramulator2")
CFG = "/home/sai/aimdb/CENT/aim_simulator/test/example.yaml"
ALL = "0xffffffff"
def cyc(lines):
    p = os.path.join(S, "t.trace")
    open(p, "w").write("\n".join(["W GPR 0", "W GPR 1"] + lines + ["AiM EOC"]) + "\n")
    out = subprocess.run([SIM, "-f", CFG, "-t", p], capture_output=True, text=True, check=True).stdout
    return int(re.search(r"memory_system_cycles:\s*(\d+)", out).group(1))
base = cyc([])
cases = {
  "MAC_ABK  op=1  same row":      lambda i: f"AiM MAC_ABK 1 {ALL} 0",
  "MAC_ABK  op=64 same row":      lambda i: f"AiM MAC_ABK 64 {ALL} 0",
  "MAC_ABK  op=64 new row":       lambda i: f"AiM MAC_ABK 64 {ALL} {i}",
  "MAC_ABK  op=1  new row":       lambda i: f"AiM MAC_ABK 1 {ALL} {i}",
  "CMP_ABK  op=32 new row":       lambda i: f"AiM CMP_ABK 32 {ALL} {i}",
  "MMAC_ABK op=64 new row":       lambda i: f"AiM MMAC_ABK 64 {ALL} {i}",
  "EWMUL    op=64 new row":       lambda i: f"AiM EWMUL 64 {ALL} {i}",
  "COPY_BKGB op=1 new row b0":    lambda i: f"AiM COPY_BKGB 1 {ALL} 0 {i}",
  "COPY_GBBK op=1 new row b0":    lambda i: f"AiM COPY_GBBK 1 {ALL} 0 {i}",
  "WR_GB    op=1":                lambda i: f"AiM WR_GB 1 0 {ALL}",
  "WR_BIAS":                      lambda i: f"AiM WR_BIAS 0 {ALL}",
  "RD_MAC (blocking)":            lambda i: f"AiM RD_MAC 0 {ALL}",
  "RD_MASK (blocking)":           lambda i: f"AiM RD_MASK 0 {ALL}",
  "WR_ABK ch0 new row":           lambda i: f"AiM WR_ABK 0 0x1 {i}",
  "RD_SBK ch-all b0 new row":     lambda i: f"AiM RD_SBK 0 {ALL} 0 {i}",
  "R MEM ch0 b0 same row (conv)": lambda i: f"R MEM 0 0 0",
}
with open(os.path.join(S, "isr_timing.txt"), "w") as f:
    f.write(f"empty trace: {base} cycles (tCK 0.5 ns)\n")
    for name, gen in cases.items():
        row = []
        for n in (1, 64):
            try:
                c = cyc([gen(i) for i in range(n)])
                row.append(f"N={n}: {c-base:>7} cyc ({(c-base)/n:7.1f}/ISR)")
            except subprocess.CalledProcessError as e:
                row.append(f"N={n}: ERROR {e.stderr.strip()[-80:] if e.stderr else ''}")
        f.write(f"{name:30s} " + "  ".join(row) + "\n")
print(open(os.path.join(S, "isr_timing.txt")).read())
