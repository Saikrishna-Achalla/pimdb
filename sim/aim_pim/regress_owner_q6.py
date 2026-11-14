#!/usr/bin/env python3
"""Regression test: the owner's fused Q6 trace (aimdb/q6/q6_pim.py write_trace, re-implemented here verbatim) on
the project-owned build. Expected (owner README, scout): SF1 = 20,865 cycles -> 0.011 ms; SF10 = 207,089 cycles.
Also reports the same trace with refresh enabled (this project's fix), which the owner's number does not include.
Usage: /home/sai/aimdb/.venv/bin/python -B regress_owner_q6.py"""
import math, os, sys
import numpy as np
import dbpu, data

CH, BANKS, TILE = 32, 512, 256
EXPECT = {1: 20865, 10: 207089}


def owner_trace(path, tiles, fuse=True):
    allch = "0x%x" % ((1 << CH) - 1)
    with open(path, "w") as f:
        f.write("# aimdb TPC-H Q6 trace: %d tiles x %d banks x %d recs\n" % (tiles, BANKS, TILE))
        f.write("W GPR 0\nW GPR 1\n")
        f.write(f"AiM WR_GB 1 0 {allch}\n")
        f.write(f"AiM WR_BIAS 1 {allch}\n")
        for t in range(tiles):
            r0, r1 = 2 * t, 2 * t + 1
            f.write(f"AiM CMP_ABK 32 {allch} {r0}\n")
            f.write(f"AiM CMP_ABK 32 {allch} {r0}\n")
            if not fuse:
                f.write(f"AiM CMP_ABK 32 {allch} {r1}\n")
            f.write(f"AiM MMAC_ABK 64 {allch} {r1}\n")
        for _ in range(4):
            f.write(f"AiM RD_MAC 0 {allch}\n")
        f.write("AiM EOC\n")


def owner_functional(sf):
    d = data.lineitem(sf)
    n = len(d["price"])
    tiles = math.ceil(n / (BANKS * TILE))
    lay = lambda a, pad: np.concatenate([a, np.full(tiles * BANKS * TILE - n, pad, a.dtype)]).reshape(tiles, BANKS, TILE)
    P, D, Q, S = lay(d["price"], 0), lay(d["disc"], 0), lay(d["qty"].astype(np.int32), 0), lay(d["ship"], -1)
    m = (S >= data.days(1994, 1, 1)) & (S < data.days(1995, 1, 1)) & (Q < 2400) & (D >= 5) & (D <= 7)
    return int(np.where(m, P.astype(np.int64) * D, 0).sum())


def main():
    ok = True
    ref = data.reference(0.01)["q6"]
    got = owner_functional(0.01)
    print(f"[functional SF0.01] owner-layout Q6 = {got}  DuckDB = {ref}  {'MATCH' if got == ref else 'MISMATCH'}")
    ok &= got == ref
    os.makedirs(dbpu.TRACES, exist_ok=True)
    rows = []
    for sf in (1, 10):
        n = int(6_001_215 * sf)
        tiles = math.ceil(n / (BANKS * TILE))
        tr = os.path.join(dbpu.TRACES, f"owner_q6_sf{sf}.trace")
        owner_trace(tr, tiles)
        up = dbpu.simulate(tr, yaml_path=dbpu.BASE_YAML)["cycles"]          # upstream yaml: no refresh
        rf = dbpu.simulate(tr, dbpu.TIMING_MAIN, refresh=True)["cycles"]    # this project's config
        ms = up * dbpu.TCK_NS * 1e-6
        print(f"SF{sf}: {up:,} cycles = {ms*1e3:.2f} us scan (+0.187 us CXL return in the owner's total) "
              f"[expected {EXPECT[sf]:,}: {'OK' if up == EXPECT[sf] else 'FAIL'}];  with refresh: {rf:,} cycles "
              f"(+{100*(rf/up-1):.1f} %)")
        ok &= up == EXPECT[sf]
        rows.append((sf, up, rf))
    with open(os.path.join(dbpu.HERE, "results", "owner_q6_regression.csv"), "w") as f:
        f.write("sf,channels,cycles_upstream_yaml_no_refresh,cycles_with_refresh,expected,match\n")
        for sf, up, rf in rows:
            f.write(f"{sf},32,{up},{rf},{EXPECT[sf]},{up == EXPECT[sf]}\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
