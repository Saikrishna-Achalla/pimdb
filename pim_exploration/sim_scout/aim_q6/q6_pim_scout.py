#!/usr/bin/env python3
"""TPC-H Q6 on an AiM-style CXL PIM device (CENT), extended with DB ISRs.

Q6:  SELECT sum(l_extendedprice * l_discount) FROM lineitem
     WHERE l_shipdate >= '1994-01-01' AND l_shipdate < '1995-01-01'
       AND l_discount BETWEEN 0.05 AND 0.07 AND l_quantity < 24

Three parts:
  1. functional  : encode lineitem (from DuckDB dbgen) into the per-bank tile layout,
                   execute the ISR semantics in numpy, check against DuckDB's exact answer.
  2. trace       : emit the AiM ISR trace for one CXL device holding its share of the table.
  3. simulate    : run the (modified) AiM Ramulator2 simulator on it and compare with
                   analytic link-bound / GPU-HBM baselines.

Layout (per bank, per tile of 256 records, INT32 = 8 values per 256-bit column):
  row 2t   : [ l_shipdate  x32 cols | l_quantity x32 cols ]
  row 2t+1 : [ l_extprice  x32 cols | l_discount x32 cols ]   <- paired so MMAC reads both from one open row
Per tile, broadcast to all channels/banks:
  CMP_ABK  32 row 2t      shipdate in [lo, hi)          -> mask  = ...
  CMP_ABK  32 row 2t      quantity < 24                 -> mask &= ...
  (CMP_ABK 32 row 2t+1    discount in [5,7]   only with --no-fuse)
  MMAC_ABK 64 row 2t+1    mask &= disc in [5,7]; acc64 += mask ? price*disc : 0
"""
import argparse, datetime, math, os, re, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
AIMDB = "/home/sai/aimdb"  # read-only
SIM = os.path.join(AIMDB, "CENT", "aim_simulator", "build", "ramulator2")
CFG = os.path.join(AIMDB, "CENT", "aim_simulator", "test", "example.yaml")

# ---- AiM / CENT device geometry (GDDR6_AiM_org in the simulator) ----
CHANNELS, BANKS_PER_CH = 32, 16
BANKS = CHANNELS * BANKS_PER_CH          # 512 near-bank PUs per CXL device
ROWS_PER_BANK = 1 << 14                  # 16K rows
COLS_PER_ROW = 64                        # 64 x 256-bit = 2 KB row
VALS_PER_COL = 8                         # INT32 lanes per 256-bit column
TILE = (COLS_PER_ROW // 2) * VALS_PER_COL  # 256 records per tile per bank
ROWS_PER_TILE = 2
TCK_NS = 0.5                             # tCK_ps = 500 in GDDR6_AiM_timing
BYTES_PER_REC = 16                       # 4 columns x INT32
PEAK_INTERNAL_TBPS = 16.0                # CENT Table 1, per device

# ---- CXL: CENT's analytical model (CENT/cent_simulation/cxl_latency.py) ----
# cxl_latency.py applies its MULTICAST adjustment (lane BW x0.5, PCIe latency x2) at import time.
# Q6 only does unicast transfers (result return / host pull), so we undo it and use the base constants.
sys.dont_write_bytecode = True  # never write __pycache__ into the read-only CENT tree
sys.path.insert(0, os.path.join(AIMDB, "CENT", "cent_simulation"))
import cxl_latency as _cent_cxl  # noqa: E402
_MC = 2.0 if _cent_cxl.MULTICAST else 1.0
CXL_GB_PER_LANE = _cent_cxl.bandwidth_per_lane * _MC                       # 8 (GB/s per PCIe6 lane)
CXL_RTT_NS = (_cent_cxl.cxl_port_latency * 4 + (_cent_cxl.pcie_latency / _MC) * 2
              + _cent_cxl.cxl_switch_latency)                               # 180 ns one-hop round trip
HOST_LANES = 16                                                            # CENT: host <-> switch x16


def cxl_transfer_ms(nbytes, lanes):
    """CENT's formula: 64 B messages, 3 per 256 B PBR flit, over `lanes` x 8 GB/s, plus one round trip."""
    flits = math.ceil(nbytes / 64 / 3)
    bw = lanes * CXL_GB_PER_LANE
    return (CXL_RTT_NS + flits * 256 / bw * 1e9 / 1024 / 1024 / 1024) / 1e6


EPOCH = datetime.date(1970, 1, 1)
D_LO = (datetime.date(1994, 1, 1) - EPOCH).days
D_HI = (datetime.date(1995, 1, 1) - EPOCH).days


def load_lineitem(sf):
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"CALL dbgen(sf={sf})")
    ref = con.execute("""
        SELECT sum(l_extendedprice * l_discount) FROM lineitem
        WHERE l_shipdate >= DATE '1994-01-01' AND l_shipdate < DATE '1995-01-01'
          AND l_discount BETWEEN 0.05 AND 0.07 AND l_quantity < 24""").fetchone()[0]
    cols = con.execute("""
        SELECT CAST(round(l_extendedprice*100) AS INTEGER),
               CAST(round(l_discount*100) AS INTEGER),
               CAST(l_quantity AS INTEGER),
               CAST(l_shipdate - DATE '1970-01-01' AS INTEGER)
        FROM lineitem""").fetchnumpy()
    price, disc, qty, ship = (np.asarray(cols[k], dtype=np.int32) for k in cols)
    return price, disc, qty, ship, ref


def layout(arrays, n_banks=BANKS):
    """Pad to whole tiles and reshape to [tile, bank, 256]. Padding fails the predicate."""
    n = len(arrays[0])
    tiles = math.ceil(n / (n_banks * TILE))
    out = []
    for a, pad in zip(arrays, (0, 0, 0, -1)):          # shipdate pad = -1 -> outside range
        b = np.full(tiles * n_banks * TILE, pad, dtype=np.int32)
        b[:n] = a
        out.append(b.reshape(tiles, n_banks, TILE))
    return tiles, out


def functional(price, disc, qty, ship, fuse=True):
    tiles, (P, D, Q, S) = layout((price, disc, qty, ship))
    # CMP_ABK on row 2t: range compare vs GB constants, AND into per-bank mask
    mask = (S >= D_LO) & (S < D_HI)
    mask &= (Q < 24)
    # discount range: fused into MMAC (or separate CMP_ABK on row 2t+1) -- same semantics
    mask &= (D >= 5) & (D <= 7)
    # MMAC_ABK: per-bank INT64 accumulator
    acc = np.where(mask, P.astype(np.int64) * D.astype(np.int64), 0).sum(axis=(0, 2))  # [bank]
    assert acc.shape == (BANKS,)
    # PNM: reduce 512 bank partials (CENT reduction trees / accumulators)
    total = int(acc.sum())
    return tiles, total, int(mask.sum())


def write_trace(path, tiles, fuse=True):
    allch = "0x%x" % ((1 << CHANNELS) - 1)
    with open(path, "w") as f:
        f.write("# aimdb TPC-H Q6 trace: %d tiles x %d banks x %d recs\n" % (tiles, BANKS, TILE))
        f.write("W GPR 0\nW GPR 1\n")
        f.write(f"AiM WR_GB 1 0 {allch}\n")          # predicate constants -> global buffers
        f.write(f"AiM WR_BIAS 1 {allch}\n")          # zero accumulators
        for t in range(tiles):
            r0, r1 = ROWS_PER_TILE * t, ROWS_PER_TILE * t + 1
            f.write(f"AiM CMP_ABK 32 {allch} {r0}\n")   # shipdate range
            f.write(f"AiM CMP_ABK 32 {allch} {r0}\n")   # quantity < 24
            if not fuse:
                f.write(f"AiM CMP_ABK 32 {allch} {r1}\n")  # discount range
            f.write(f"AiM MMAC_ABK 64 {allch} {r1}\n")  # masked price*discount
        for _ in range(4):                               # 16 banks x INT64 = 4 x 256b per channel
            f.write(f"AiM RD_MAC 0 {allch}\n")
        f.write("AiM EOC\n")


def simulate(trace):
    t0 = time.time()
    out = subprocess.run([SIM, "-f", CFG, "-t", trace], capture_output=True, text=True, check=True).stdout
    cyc = int(re.search(r"memory_system_cycles:\s*(\d+)", out).group(1))
    stat = lambda k: int(re.search(rf"CH0_{k}:\s*(\d+)", out).group(1))
    return cyc, {k: stat(k) for k in ("num_MAC16_commands", "num_ACT16_commands", "AiM_ISR_CMP_ABK_cycles",
                                      "AiM_ISR_MMAC_ABK_cycles", "AiM_ISR_RD_MAC_cycles")}, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-sf", type=float, default=0.1, help="SF for functional check vs DuckDB")
    ap.add_argument("--sf", type=float, nargs="+", default=[1, 10, 100, 1000], help="SFs to simulate")
    ap.add_argument("--no-fuse", action="store_true", help="separate CMP for discount instead of fusing into MMAC")
    ap.add_argument("--dev-lanes", type=int, default=4, help="PCIe6 lanes per CXL device (CENT: x4)")
    ap.add_argument("--gpu-hbm-tbps", type=float, default=3.35 * 0.9, help="GPU achievable HBM BW (H100 x 0.9)")
    ap.add_argument("--gpu-mem-gb", type=float, default=80.0)
    args = ap.parse_args()
    fuse = not args.no_fuse
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)

    # ---- 1. functional check on real TPC-H data ----
    price, disc, qty, ship, ref = load_lineitem(args.check_sf)
    tiles, total, sel = functional(price, disc, qty, ship, fuse)
    got = total / 10000  # cents * hundredths
    ok = abs(got - float(ref)) < 1e-6 * max(1.0, abs(float(ref)))
    exact = (total == int(round(float(ref) * 10000)))
    print(f"[functional] SF={args.check_sf}: {len(price):,} rows, {tiles} tiles/bank, "
          f"selected {sel:,} ({100*sel/len(price):.2f}%)")
    print(f"[functional] PIM revenue = {got:.4f}   DuckDB = {ref}   -> {'MATCH (exact)' if exact else ('match' if ok else 'MISMATCH')}")
    if not ok:
        sys.exit(1)

    # ---- 2+3. trace + timing per scale factor ----
    rows_per_sf = 6_001_215
    cap_tiles = ROWS_PER_BANK // ROWS_PER_TILE
    print(f"\n{'SF':>6} {'rows':>14} {'dev':>3} {'tiles/bank':>10} {'sim cyc':>10} {'PIM ms':>9} "
          f"{'eff TB/s':>8} {'CXL-pull ms':>11} {'GPU-HBM ms':>10} {'vs CXL':>7} {'vs GPU':>7}")
    for sf in args.sf:
        n = int(rows_per_sf * sf)
        devices = max(1, math.ceil(n / (cap_tiles * BANKS * TILE)))
        n_dev = math.ceil(n / devices)
        tiles = math.ceil(n_dev / (BANKS * TILE))
        trace = os.path.join(HERE, "out", f"q6_sf{sf:g}{'' if fuse else '_nofuse'}.trace")
        write_trace(trace, tiles, fuse)
        cyc, st, wall = simulate(trace)
        # PIM: simulated scan (devices in parallel) + each device returns its 8 B PNM-reduced sum over CXL.
        # PNM reduction of 512 bank partials (~33 ns by CENT's VEC constants) is not timed.
        scan_ms = cyc * TCK_NS * 1e-6
        ret_ms = cxl_transfer_ms(8, args.dev_lanes)
        pim_ms = scan_ms + ret_ms
        bytes_dev = n_dev * BYTES_PER_REC
        eff = bytes_dev / (cyc * TCK_NS * 1e-9) / 1e12
        # Baseline: host pulls the Q6 columns; bounded by each device's link and the host's x16 link.
        cxl_ms = max(cxl_transfer_ms(bytes_dev, args.dev_lanes), cxl_transfer_ms(n * BYTES_PER_REC, HOST_LANES))
        fits = n * BYTES_PER_REC <= args.gpu_mem_gb * 1e9
        gpu_ms = n * BYTES_PER_REC / (args.gpu_hbm_tbps * 1e12) * 1e3
        print(f"{sf:>6g} {n:>14,} {devices:>3} {tiles:>10} {cyc:>10,} {pim_ms:>9.3f} {eff:>8.2f} "
              f"{cxl_ms:>11.2f} {gpu_ms if fits else float('nan'):>10.3f} {cxl_ms/pim_ms:>6.0f}x "
              f"{(gpu_ms/pim_ms if fits else float('nan')):>6.1f}x")
        print(f"       ch0: MAC16={st['num_MAC16_commands']:,} ACT16={st['num_ACT16_commands']:,} "
              f"CMP={st['AiM_ISR_CMP_ABK_cycles']:,}cyc MMAC={st['AiM_ISR_MMAC_ABK_cycles']:,}cyc "
              f"RD_MAC={st['AiM_ISR_RD_MAC_cycles']}cyc  (sim wall {wall:.1f}s)  "
              f"scan {scan_ms*1e3:.1f} us + CXL return {ret_ms*1e3:.3f} us")
    print(f"\nCXL (CENT model, unicast): {CXL_GB_PER_LANE:g} GB/s/lane, device x{args.dev_lanes}, host x{HOST_LANES}, "
          f"RTT {CXL_RTT_NS:g} ns, 192 B payload per 256 B flit. Peak internal BW {PEAK_INTERNAL_TBPS} TB/s/device.\n"
          f"GPU baseline assumes data already resident in {args.gpu_mem_gb:g} GB HBM (n/a when it doesn't fit).")


if __name__ == "__main__":
    main()
