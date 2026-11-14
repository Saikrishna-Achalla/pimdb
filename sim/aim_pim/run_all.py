#!/usr/bin/env python3
"""Runs every DB-PU workload: functional check against DuckDB, ISR trace, simulation (+ breakdown), pacing model,
same-memory normalization, sensitivity. Writes sim/aim_pim/results/*.csv.
Usage: /home/sai/aimdb/.venv/bin/python -B run_all.py [--sf 0.01 0.1 1] [--jobs 16] [--skip-sens]"""
import argparse, csv, math, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import dbpu as P
import data as D
import workloads as WL
import regress_owner_q6 as OQ

RES = os.path.join(P.HERE, "results")
# ---- modeled pacing / host constants (labelled in the CSVs) ----
C_ISR_POST_NS = 1.0      # one ISR = one 32 B posted write over the channel's 32 GB/s link (overlapped with execution)
C_ISR_SYNC_NS = 300.0    # one ISR waits one GPU->DRAM round trip (RTX 5070 DRAM latency ~858 cyc @ 2.866 GHz)
GAP_LAUNCH_US = 7.4      # measured real-GPU median host gap with only an allocation (note 04, gap_by_host.csv)
GAP_READBACK_US = 33.6   # measured real-GPU median host gap with a size read-back (note 04)
CH_S1, CH_S4, CH_5070 = 672 / 48 / 32, 4 * 672 / 48 / 32, 672 / 32   # 0.4375, 1.75, 21 AiM channels
EXT_GBS_PER_CH = 32.0


def row_for(w, sched, issuer, sf, res, info, ok, extra=None):
    L = w.L
    t_us = res["cycles"] * P.TCK_NS / 1000
    cmd = res["cmd"]; chn = L.n_channels
    pu_cmds = sum(cmd.get(k, 0) for k in ("CMP16", "ALU16", "MUL16", "GAG16", "PUWR16", "MAC16")) / chn
    touched = pu_cmds * P.WORD_B * P.BANKS_PER_CH * chn
    rdmac = sum(op.readout for op in w.ops)
    readbacks = sum(1 for op in w.ops if isinstance(op, P.COMPACT))
    t_post = info["isr_lines"] * C_ISR_POST_NS / 1000
    t_sync = info["isr_lines"] * C_ISR_SYNC_NS / 1000
    main = {"pred_and": "tile", "member_in8": "tile"}.get(w.name, "op") == sched if w.kind == "operator" else (
        sched == "tile" or w.name == "q6_owner_fused")
    r = dict(workload=w.name, kind=w.kind, schedule=sched, issuer=issuer, main_variant=main, sf=sf, n_records=L.n, channels=chn,
             T_records_per_row=L.T, rows_per_bank=L.rows, base_row_util=round(L.base_util, 3), check_vs_duckdb=ok,
             cycles=res["cycles"], time_us=round(t_us, 3), input_bytes=w.input_bytes,
             eff_input_bw_GBs=round(w.input_bytes / (t_us * 1e3), 1) if t_us else 0,
             pu_column_cmds_per_ch=int(pu_cmds), pu_touched_bytes=int(touched),
             internal_bw_GBs=round(touched / (t_us * 1e3), 1) if t_us else 0,
             act16_per_ch=cmd.get("ACT16", 0) // chn, refab_per_ch=cmd.get("REFab", 0) // 32,  # all 32 controllers refresh
             dram_cmds_per_ch=int(sum(v for k, v in cmd.items() if k != "REFab") / chn + cmd.get("REFab", 0) / 32),
             isr_lines=info["isr_lines"], op_row_steps=info["op_steps"], n_ops=info["n_ops"],
             compute_cyc=round(res.get("compute_cyc", 0)), rowov_turnaround_cyc=round(res.get("rowov_cyc", 0)),
             readout_cyc=res.get("readout_cyc", 0), refresh_cyc=res.get("refresh_cyc", 0),
             host_cmds_hostpaced=info["isr_lines"], host_cmds_sequencer=info["consts"] + 2 + info["readout_isrs"],
             t_issue_post_us=round(t_post, 3), t_issue_sync_us=round(t_sync, 1),
             t_hostpaced_post_us=round(max(t_us, t_post), 3), t_hostpaced_sync_us=round(t_us + t_sync, 1),
             t_sequencer_us=round(t_us + 2 * C_ISR_SYNC_NS / 1000, 3),
             host_gaps_per_op_launch_us=round(info["n_ops"] * GAP_LAUNCH_US + readbacks * GAP_READBACK_US, 1),
             host_gaps_sequencer_us=round(GAP_LAUNCH_US + readbacks * GAP_READBACK_US, 1),
             note=w.note)
    if extra:
        r.update(extra)
    return r


def prepare(w, sched, issuer, tag):
    pu = P.run_functional(w.L, w.base, w.setup + w.ops)
    ok = bool(w.check(pu))
    tr = os.path.join(P.TRACES, f"{tag}.trace")
    info = P.write_trace(tr, w.L, pu, w.ops, sched, mask_readout=w.mask_readout, compact_readout=w.compact_readout,
                         issuer=issuer)
    return tr, info, ok


def isr_timing():
    """Per-ISR cycles: N back-to-back copies on the same row / a new row each time (refresh off, main timing)."""
    tr = os.path.join(P.TRACES, "isr.trace")
    def cyc(lines):
        open(tr, "w").write("\n".join(["W GPR 0", "W GPR 1"] + lines + ["AiM EOC"]) + "\n")
        return P.simulate(tr, P.TIMING_MAIN, refresh=False)["cycles"]
    base = cyc([])
    ch = "0x1"
    cases = [("MAC_ABK (AiM MAC16)", "AiM MAC_ABK {n} " + ch + " {r}"), ("CMP_ABK owner (MAC16 alias)", "AiM CMP_ABK {n} " + ch + " {r}"),
             ("MMAC_ABK owner (MAC16 alias)", "AiM MMAC_ABK {n} " + ch + " {r}"),
             ("PCMP_ABK (CMP16)", "AiM PCMP_ABK {n} " + ch + " {r}"), ("PALU_ABK (ALU16)", "AiM PALU_ABK {n} " + ch + " {r}"),
             ("PMUL_ABK (MUL16)", "AiM PMUL_ABK {n} " + ch + " {r}"), ("PGAG_ABK (GAG16)", "AiM PGAG_ABK {n} " + ch + " {r}"),
             ("PWB_ABK (PUWR16)", "AiM PWB_ABK {n} " + ch + " {r}")]
    rows = []
    for name, f in cases:
        for n in (1, 8, 64):
            for mode in ("same_row", "new_row"):
                N = 64
                c = cyc([f.format(n=n, r=(0 if mode == "same_row" else i)) for i in range(N)])
                rows.append(dict(isr=name, opsize_words=n, rows=mode, isrs=N, cycles=c - base,
                                 cycles_per_isr=round((c - base) / N, 2), ns_per_isr=round((c - base) / N * P.TCK_NS, 2),
                                 GBs_per_channel=round(N * n * 512 / ((c - base) * P.TCK_NS), 1)))
    # read then write-back on one row (PU turnaround), and the register read-out
    for nr, nw in ((8, 8), (16, 16), (32, 8)):
        c = cyc([l for i in range(64) for l in (f"AiM PALU_ABK {nr} {ch} {i}", f"AiM PWB_ABK {nw} {ch} {i}")])
        rows.append(dict(isr=f"PALU {nr} + PWB {nw} (new row each)", opsize_words=nr + nw, rows="new_row", isrs=64,
                         cycles=c - base, cycles_per_isr=round((c - base) / 64, 2), ns_per_isr=round((c - base) / 64 * P.TCK_NS, 2),
                         GBs_per_channel=round(64 * (nr + nw) * 512 / ((c - base) * P.TCK_NS), 1)))
    for name, l in (("RD_MAC (blocking, 32 B/ch)", f"AiM RD_MAC 0 {ch}"), ("WR_GB", f"AiM WR_GB 1 0 {ch}")):
        c = cyc([l] * 64)
        rows.append(dict(isr=name, opsize_words=1, rows="-", isrs=64, cycles=c - base, cycles_per_isr=round((c - base) / 64, 2),
                         ns_per_isr=round((c - base) / 64 * P.TCK_NS, 2), GBs_per_channel=""))
    c = cyc([f"AiM RD_SBK 0 {ch} {b} {r}" for r in range(4) for b in range(16)])
    rows.append(dict(isr="RD_SBK 1 word, 16 banks interleaved (GPU read)", opsize_words=1, rows="new_row", isrs=64,
                     cycles=c - base, cycles_per_isr=round((c - base) / 64, 2), ns_per_isr=round((c - base) / 64 * P.TCK_NS, 2),
                     GBs_per_channel=round(64 * 32 / ((c - base) * P.TCK_NS), 1)))
    write_csv("isr_timing.csv", rows)
    # refresh cost on a long streaming ISR sequence
    lines = [f"AiM PALU_ABK 64 {ch} {i}" for i in range(2000)]
    open(tr, "w").write("\n".join(["W GPR 0", "W GPR 1"] + lines + ["AiM EOC"]) + "\n")
    a = P.simulate(tr, P.TIMING_MAIN, refresh=True)["cycles"]; b = P.simulate(tr, P.TIMING_MAIN, refresh=False)["cycles"]
    print(f"[isr_timing] base {base} cyc; PALU 64 x 2000 rows: {b} cyc no refresh, {a} with refresh (+{100*(a/b-1):.1f} %)")


def write_csv(name, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    for r in rows[1:]:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(os.path.join(RES, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote results/{name} ({len(rows)} rows)")


class OwnerLayout:
    """Owner's layout (aimdb q6_pim.py): tile = 256 int32 records per bank over 2 rows (ship|qty, price|disc)."""
    def __init__(self, n, ch):
        self.n, self.n_channels, self.T, self.nb = n, ch, 256, 16 * ch
        self.rows = 2 * math.ceil(n / (16 * ch * 256)); self.base_util = 1.0
        self.cols = self.widths = {"ship": 4, "qty": 4, "price": 4, "disc": 4}


def owner_fused_job(sf, n, ch, tag):
    tiles = math.ceil(n / (16 * ch * 256))
    tr = os.path.join(P.TRACES, f"{tag}.trace")
    allch = P.chmask(ch)
    with open(tr, "w") as f:
        f.write(f"W GPR 0\nW GPR 1\nAiM WR_GB 1 0 {allch}\nAiM WR_BIAS 1 {allch}\n")
        for t in range(tiles):
            f.write(f"AiM CMP_ABK 32 {allch} {2*t}\nAiM CMP_ABK 32 {allch} {2*t}\nAiM MMAC_ABK 64 {allch} {2*t+1}\n")
        f.write("".join(f"AiM RD_MAC 0 {allch}\n" for _ in range(4)) + "AiM EOC\n")
    info = dict(isr_lines=3 * tiles + 6, op_steps=3 * tiles, n_ops=3, consts=1, readout_isrs=4)
    return tr, info, tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=float, nargs="+", default=[0.01, 0.1, 1])
    ap.add_argument("--jobs", type=int, default=16)
    ap.add_argument("--skip-sens", action="store_true")
    ap.add_argument("--skip-isr", action="store_true")
    a = ap.parse_args()
    os.makedirs(RES, exist_ok=True); os.makedirs(P.TRACES, exist_ok=True)
    t0 = time.time()
    if not a.skip_isr:
        isr_timing()
    pool = ThreadPoolExecutor(a.jobs)
    op_rows, ch_rows, sens_rows, futs = [], [], [], []

    def submit(target, w, sched, issuer, sf, tr, info, ok, timing=None, extra=None):
        fut = pool.submit(P.measure, tr, timing, w.L.n_channels, True)
        futs.append((target, w, sched, issuer, sf, info, ok, extra, fut))

    for sf in a.sf:
        d, ref = D.lineitem(sf), D.reference(sf)
        n = len(d["price"])
        print(f"SF{sf:g}: {n:,} rows ({time.time()-t0:.0f}s)", flush=True)
        for w in WL.micro(sf, d, ref):
            variants = [("op", "host")]
            if w.name.startswith("compact"):
                variants.append(("op", "seq"))
            if w.name in ("pred_and", "member_in8"):
                variants.append(("tile", "seq"))
            for sched, issuer in variants:
                tr, info, ok = prepare(w, sched, issuer, f"{w.name}_{sched}_{issuer}_sf{sf:g}")
                print(f"  {w.name:24s} {sched}/{issuer}: check={'OK' if ok else 'FAIL'} T={w.L.T} rows={w.L.rows}", flush=True)
                submit(op_rows, w, sched, issuer, sf, tr, info, ok)
        chains = WL.q6_chains(sf, d, ref) + WL.q1_chain(sf, d, ref)
        for w in chains:
            for sched in ("op", "tile"):
                tr, info, ok = prepare(w, sched, None, f"{w.name}_{sched}_sf{sf:g}")
                print(f"  {w.name:24s} {sched}: check={'OK' if ok else 'FAIL'} T={w.L.T} rows={w.L.rows}", flush=True)
                submit(ch_rows, w, sched, "host" if sched == "op" else "seq", sf, tr, info, ok)
        # owner's fused variant (owner layout: 2 rows x 256 int32 records, MAC16 timing aliases)
        tr, info, tiles = owner_fused_job(sf, n, 1, f"q6_owner_fused_1ch_sf{sf:g}")
        okf = OQ.owner_functional(sf) == int(ref["q6"])
        wf = WL.Workload("q6_owner_fused", OwnerLayout(n, 1), {}, [],
                         None, kind="chain", note="owner's CMP_ABK x2 + MMAC_ABK with embedded discount range check (fused); qty int32")
        wf.ops = [P.CMP("ship", 0, 0), P.CMP("qty", 0, 0), P.MMAC("price", "disc")]
        submit(ch_rows, wf, "tile", "host", sf, tr, info, okf)
    # ---- full device (32 channels) Q6 at SF1, and per-channel share of the RTX 5070 (21 channels) at SF1
    if 1 in a.sf or 1.0 in a.sf:
        d, ref = D.lineitem(1), D.reference(1)
        n = len(d["price"])
        for w in WL.q6_chains(1, d, ref, ch=32):
            for sched in ("op", "tile"):
                tr, info, ok = prepare(w, sched, None, f"{w.name}_{sched}_32ch_sf1")
                submit(ch_rows, w, sched, "host" if sched == "op" else "seq", 1, tr, info, ok, extra=dict(config="device_32ch"))
        tr, info, tiles = OQ_tr = owner_fused_job(1, n, 32, "q6_owner_fused_32ch_sf1")
        wf = WL.Workload("q6_owner_fused", OwnerLayout(n, 32),
                         {}, [], None, kind="chain", note="owner's fused trace = README configuration")
        wf.ops = [P.CMP("ship", 0, 0), P.CMP("qty", 0, 0), P.MMAC("price", "disc")]
        submit(ch_rows, wf, "tile", "host", 1, tr, info, OQ.owner_functional(1) == int(ref["q6"]), extra=dict(config="device_32ch"))
        nshare = math.ceil(n / 21)
        for w in WL.q6_chains(1, d, ref, n=nshare) + WL.q1_chain(1, d, ref, n=nshare):
            for sched in ("op", "tile"):
                tr, info, ok = prepare(w, sched, None, f"{w.name}_{sched}_share21_sf1")
                submit(ch_rows, w, sched, "host" if sched == "op" else "seq", 1, tr, info, "n/a (timing only)",
                       extra=dict(config="5070_share_1of21"))
        # ---- sensitivity (SF1, 1 channel)
        if not a.skip_sens:
            M = P.TIMING_MAIN
            variants = {"main": {}, "CMP 4 tCK": dict(nCCDCMP=4), "MUL slot 4 tCK": dict(nCCDMUL=4),
                        "MUL slot 8 tCK": dict(nCCDMUL=8), "GAG 4 tCK": dict(nCCDGAG=4), "ALU 4 tCK": dict(nCCDALU=4),
                        "tRFC 210 ns": dict(nRFC=420), "write turnaround 0": dict(nPUWTR=0),
                        "write turnaround 22": dict(nPUWTR=22), "PU ACT offset 0 (nRCDRDMAC 36)": dict(nRCDRDMAC=36)}
            sens_w = [w for w in WL.q6_chains(1, d, ref) + WL.q1_chain(1, d, ref) if w.name in ("q6_main", "q6_mulwb_sum", "q1_main")]
            sens_w += [w for w in WL.micro(1, d, ref) if w.name in ("pred_ship32", "ew_mul32x32", "gagg_sum_count")]
            for w in sens_w:
                for sched in (("op", "tile") if w.kind == "chain" else ("op",)):
                    tr, info, ok = prepare(w, sched, None, f"sens_{w.name}_{sched}")
                    for vn, ov in variants.items():
                        tm = dict(M, **ov)
                        fut = pool.submit(P.measure, tr, tm, 1, False)
                        futs.append((sens_rows, w, sched, vn, 1, info, ok, None, fut))
    print(f"waiting for {len(futs)} simulations ({time.time()-t0:.0f}s)", flush=True)
    for target, w, sched, issuer, sf, info, ok, extra, fut in futs:
        res = fut.result()
        if target is sens_rows:
            sens_rows.append(dict(workload=w.name, schedule=sched, variant=issuer, sf=sf, cycles=res["cycles"],
                                  time_us=round(res["cycles"] * P.TCK_NS / 1000, 3)))
        else:
            target.append(row_for(w, sched, issuer, sf, res, info, ok, extra))
    pool.shutdown()
    # relative sensitivity
    base = {(r["workload"], r["schedule"]): r["cycles"] for r in sens_rows if r["variant"] == "main"}
    for r in sens_rows:
        r["rel_to_main"] = round(r["cycles"] / base[(r["workload"], r["schedule"])], 3)
    # not-executable operators (no faked timing)
    for name, why in (("gather_4B", "per-bank addresses needed; lockstep shares one row/column address (isr_spec.json)"),
                      ("gather_8B", "same as gather_4B"),
                      ("hash_build_probe", "bucket in an arbitrary bank; no inter-bank path"),
                      ("sort", "inter-bank permutation needed")):
        op_rows.append(dict(workload=name, kind="operator", schedule="-", issuer="-", check_vs_duckdb="not executable",
                            note=why))
    write_csv("operators.csv", op_rows)
    write_csv("chains.csv", ch_rows)
    write_csv("sensitivity.csv", sens_rows)
    normalization(op_rows, ch_rows)
    print(f"done in {time.time()-t0:.0f}s")


def normalization(op_rows, ch_rows):
    """Same-memory normalization (modeled): 1 simulated channel -> S1 (0.4375 ch), S4 (1.75 ch), RTX 5070 (21 ch)."""
    out = []
    direct = {(r["workload"], r["schedule"]): r for r in ch_rows if r.get("config") == "5070_share_1of21"}
    for r in op_rows + ch_rows:
        if "time_us" not in r or r.get("config") or r["channels"] != 1:
            continue
        t = r["time_us"]
        d = direct.get((r["workload"], r["schedule"])) if r["sf"] == 1 else None
        tr_bytes = r["input_bytes"]
        out.append(dict(
            workload=r["workload"], schedule=r["schedule"], issuer=r["issuer"], sf=r["sf"],
            t_1ch_us_simulated=t,
            S1_channels=CH_S1, t_S1_us_modeled=round(t / CH_S1, 3),
            S4_channels=CH_S4, t_S4_us_modeled=round(t / CH_S4, 3),
            rtx5070_channels=CH_5070, t_5070_us_linear_modeled=round(t / CH_5070, 3),
            t_5070_us_direct_sim_1of21=(d["time_us"] if d else ""),
            layout_transform_1ch_us_modeled=round(2 * tr_bytes / (EXT_GBS_PER_CH * 1e3), 1),
            layout_transform_5070_us_modeled=round(2 * tr_bytes / (EXT_GBS_PER_CH * CH_5070 * 1e3), 1),
            host_gaps_per_op_launch_us_measured_median=r["host_gaps_per_op_launch_us"],
            host_gaps_sequencer_us_measured_median=r["host_gaps_sequencer_us"],
            assumptions="bank-parallel work on evenly spread data scales linearly with channels (S1 = 7 banks); "
                        "GDDR6-AiM channel (32 GB/s ext, 512 GB/s int) stands in for GDDR7; layout transform = read "
                        "+ write every input byte once over the external bus, one-time per table load, not in t_*; "
                        "host gaps are real-GPU medians (note 04), not added to t_*"))
    write_csv("normalization.csv", out)


if __name__ == "__main__":
    main()
