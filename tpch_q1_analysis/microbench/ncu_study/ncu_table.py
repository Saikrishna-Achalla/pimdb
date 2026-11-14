#!/usr/bin/env python3
"""Join an ncu JSON (extract_ncu.py output; kernels in launch order) with the variant names printed in the run log.
usage: ncu_table.py <json> <log>"""
import json, re, sys
ks = json.load(open(sys.argv[1]))["kernels"]
names = [l[:26].strip() for l in open(sys.argv[2]) if re.search(r"\s(OK|MISMATCH)\s*$", l)]
assert len(names) == len(ks), (len(names), len(ks))
print(f"{'variant':26s} {'regs':>4} {'ncu_us':>7} {'DRAM_GB/s':>9} {'DRAM_MB':>7} {'occ%':>5} {'waves':>5} {'warp_inst':>9} {'longSB%':>7} {'shortSB%':>8} {'barrier%':>8} {'wait%':>6} {'sel%':>5} {'ldreq':>8}")
for n, k in zip(names, ks):
    st = k["stalls"]; tot = sum(st.values()) or 1
    p = lambda r: 100 * st.get(r, 0) / tot
    print(f"{n:26s} {int(k['regs']):4d} {k['dur_ns']/1e3:7.1f} {k['achieved_bw_gbs']:9.1f} {k['dram_bytes']/1e6:7.1f} {k['occ_ach']:5.1f} {k['waves']:5.2f} "
          f"{int(k['inst']):9d} {p('long_scoreboard'):7.1f} {p('short_scoreboard'):8.1f} {p('barrier'):8.1f} {p('wait'):6.1f} {p('selected'):5.1f} {int(k['ldreq_glob'] or 0):8d}")
