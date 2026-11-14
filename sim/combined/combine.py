"""Combine the Vortex baseline (simx, scaled-down RTX 5070) and the AiM bank-level DB unit (Ramulator2) into speedups.

Run:  /home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I sim/combined/combine.py
Reads only (never writes outside sim/combined/):
  sim/vortex_baseline/results/{operators,chains,chains_totals,calibration,mapping_q6,mapping_q1}.csv
  sim/aim_pim/results/{operators,chains,normalization,sirius_to_pim_mapping}.csv, sim/aim_pim/isr_spec.json,
  sim/aim_pim/cache/ref_sf*.npz (compaction selectivity of the PIM data)
  real GPU (measured): tpch_q1_analysis/analysis/results/q6/, pim_exploration/sf10_scaling/{q6,q1,q1/sf1_sf1pipe}/
    (nsys sqlite read-only, Sirius log windows exactly as nsys_breakdown.py, timing.json)
Writes: operators_speedup.csv, chains_speedup.csv, end_to_end.csv, realgpu_amdahl_detail.csv, combined_numbers.json

Labels: simulated = simx / Ramulator2 output; measured = real RTX 5070 file; modeled = arithmetic on an assumption
(stated in the 'basis' / 'note' column).
"""
import collections, csv, glob, json, os, re, sqlite3, statistics, sys

ROOT = "/home/sai/cs254_project"
OUT = os.path.join(ROOT, "sim/combined")
VX = os.path.join(ROOT, "sim/vortex_baseline/results")
AM = os.path.join(ROOT, "sim/aim_pim/results")

# ---------------------------------------------------------------- configuration constants (from the files / brief)
CAL = list(csv.DictReader(open(f"{VX}/calibration.csv")))
BW = {r["config"]: float(r["configured_gbs"]) for r in CAL if r["kind"] == "stream" and r["config"] in ("S1", "S4")}
STREAM_EFF = {r["config"]: float(r["pct_of_configured"]) for r in CAL if r["run"] in ("S1_16M_g1024", "S4_16M_g4096")}
NORM = list(csv.DictReader(open(f"{AM}/normalization.csv")))
CH = {"S1": float(NORM[0]["S1_channels"]), "S4": float(NORM[0]["S4_channels"]), "5070": float(NORM[0]["rtx5070_channels"])}
CORES = {"S1": 1, "S4": 4, "5070": 48}
BW["5070"] = 672.0  # GB/s peak of the real RTX 5070 (BRIEF_COMMON); S(f) = 672 * f
assert abs(BW["S1"] - 672 / 48) < 1e-9 and abs(CH["S1"] - BW["S1"] / 32) < 1e-9, "same-memory normalization mismatch"
REAL_LAUNCH_US = 2.5   # modeled: GPU-side cost of one real 5070 launch (note 10: "about 2-3 us")
GAP_ALLOC_US, GAP_READBACK_US = 7.4, 33.6  # measured real-GPU medians (note 04), as used by both builders
POSTED_NS, SYNC_NS = 1.0, 300.0            # note 09 issue models per host command
SEQ_START_COMPLETE_US = None               # taken from chains.csv (t_sequencer_us - time_us)

f = lambda x: float(x) if x not in ("", None) else None


def wcsv(name, rows, cols=None):
    cols = cols or list(rows[0].keys())
    with open(os.path.join(OUT, name), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})


# ---------------------------------------------------------------- load simulator results
VOPS = {}
for r in csv.DictReader(open(f"{VX}/operators.csv")):
    VOPS[(r["run"], r["config"], f(r["sf"]))] = r
VCH = [r for r in csv.DictReader(open(f"{VX}/chains.csv"))]
VTOT = {(r["chain"], r["config"], f(r["sf"])): r for r in csv.DictReader(open(f"{VX}/chains_totals.csv"))}

POPS = {}
for r in csv.DictReader(open(f"{AM}/operators.csv")):
    if r["time_us"]:
        POPS[(r["workload"], r["schedule"], r["issuer"], f(r["sf"]))] = r
PCH = {}
for r in csv.DictReader(open(f"{AM}/chains.csv")):
    PCH[(r["workload"], r["schedule"], f(r["sf"]), r["config"] or "1ch")] = r
PNORM = {(r["workload"], r["schedule"], r["issuer"], f(r["sf"])): r for r in NORM}
SPEC = json.load(open(os.path.join(ROOT, "sim/aim_pim/isr_spec.json")))
TCK_NS = SPEC["device"]["tCK_ns"]

issues = []  # inconsistencies found while combining


def pim_scaled(row, cfg):
    """1-channel simulated time -> configuration cfg (modeled: linear in channels)."""
    return f(row["time_us"]) / CH[cfg]


# sanity: our normalization equals the AiM builder's normalization.csv
for k, r in PNORM.items():
    src = POPS.get(k) or PCH.get((k[0], k[1], k[3], "1ch"))
    if src is None:
        continue
    for cfg, col in (("S1", "t_S1_us_modeled"), ("S4", "t_S4_us_modeled"), ("5070", "t_5070_us_linear_modeled")):
        mine = pim_scaled(src, cfg)
        if abs(mine - f(r[col])) > 0.002 * mine + 0.002:
            issues.append(f"normalization.csv {k} {col}={r[col]} vs recomputed {mine:.3f}")

# ---------------------------------------------------------------- cross-checks of the two builders' assumptions
lin = {}
for sf in (0.01, 0.1, 1):
    p = os.path.join(ROOT, f"sim/aim_pim/cache/ref_sf{sf:g}.npz")
    if os.path.exists(p):
        import numpy as np
        z = np.load(p, allow_pickle=False)
        lin[sf] = {"n": int(z["n"]), "compact_sel": len(z["compact_ids"]) / int(z["n"])}
for sf in (0.01, 0.1, 1):
    vn = [int(r["rows"]) for r in VCH if f(r["sf"]) == sf][:1]
    pn = [int(r["n_records"]) for r in PCH.values() if f(r["sf"]) == sf and r["config"] == ""][:1]
    if vn and pn and vn[0] != pn[0]:
        issues.append(f"row count differs at SF{sf}: Vortex {vn[0]} vs PIM {pn[0]}")
# Q6 per-row input bytes on each side
q6_pim_Bpr = f(PCH[("q6_main", "tile", 1.0, "1ch")]["input_bytes"]) / 6001215
q1_pim_Bpr = f(PCH[("q1_main", "tile", 1.0, "1ch")]["input_bytes"]) / 6001215
fused_Bpr = f(PCH[("q6_owner_fused", "tile", 1.0, "1ch")]["input_bytes"]) / 6001215
VX_WIDTH = {"l_shipdate": 2, "l_quantity": 4, "l_extendedprice": 4, "l_discount": 4, "l_tax": 4}  # gen_data.py docstring
q6_vx_Bpr = VX_WIDTH["l_shipdate"] + VX_WIDTH["l_quantity"] + VX_WIDTH["l_extendedprice"] + VX_WIDTH["l_discount"]
q1_vx_Bpr = q6_vx_Bpr + VX_WIDTH["l_tax"] + 2 * (1 + 4)  # two cuDF string columns of 1-char strings: 1 B char + 4 B offset
issues.append(f"column split differs, totals agree for Q6: Vortex l_shipdate int16 + l_quantity int32, PIM l_shipdate int32 + "
              f"l_quantity int16 (isr_spec.json operand_widths); both {q6_vx_Bpr} vs {q6_pim_Bpr:.2f} B/row; both sides call the "
              f"split inferred from the 14.0 B/row pinned footprint")
issues.append(f"Q1 input widths differ: Vortex {q1_vx_Bpr} B/row (flags as cuDF strings 1 B + 4 B offset, as the real GPU) vs PIM "
              f"{q1_pim_Bpr:.2f} B/row (flags as 1-byte dictionary codes) -> favours PIM by {q1_vx_Bpr - q1_pim_Bpr:.0f} B/row; "
              f"floors below are given at both widths")
issues.append(f"owner's fused Q6 command reads {fused_Bpr:.1f} B/row (qty int32) vs {q6_pim_Bpr:.1f} B/row for the general "
              f"chain: the fused reference is not at the same widths")
issues.append("Q6 filter parameters: both simulators use the dbgen default substitution (1994, 0.05-0.07, qty<24; Vortex SF1 "
              "result 114,160 selected rows); the real-GPU runs use 1997 / 0.02-0.04 / qty<24 on the Parquet data "
              "(114,271 rows, physical_floor.md). Same selectivity (1.90 %), different rows; the PIM main plan's cost "
              "does not depend on the selected count, the Vortex gathers do (114,160 items)")
issues.append(f"clocks: simx core 2512 MHz, Ramulator2 AiM tCK {TCK_NS} ns (2 GHz); both reported in us, no clock "
              f"conversion is needed; the 5070's DRAM is GDDR7 and AiM is GDDR6 (projection)")
issues.append("end of an operation: Vortex kernels end when DRAM has drained the writes (patched); results stay in DRAM "
              "except scalars/counts read back by the host (host step not simulated). PIM operators end with results in "
              "the bank rows (masks, write-backs) or in PU registers read by RD_MAC (sums, group accumulators); mask and "
              "compaction-segment read-out to the GPU are separate '+readout' variants")

issues.append("mapping CSVs disagree on what the chain contains: Vortex mirrors the Sirius min/max SUM-widening pre-check "
              "(Q6 2 launches, Q1 10) while the PIM chains leave it out ('planner policy') -> chain row (a') drops it; "
              "Vortex omits Q1's batch_memcpy string path (6/batch) that PIM counts as 'removed'; Vortex mirrors the casts "
              "as launches that PIM folds into operand widths")
issues.append("Q6 compaction is in the Vortex chain (count/scan/scatter + 2 gathers) but replaced by a mask in the PIM main "
              "chain: (a)/(d) mixes a plan change that a GPU could also make (masked aggregate)")

# ---------------------------------------------------------------- 1. operator-level table
def vx_time(run, cfg, sf):
    r = VOPS.get((run, cfg, sf))
    return (f(r["time_us"]), f(r["pct_bw"]), r["bound"], f(r["logical_bytes"]), int(r["rows"])) if r else None


def vx_compaction(cfg, sf, sel):
    """Vortex compaction at the PIM data's selectivity: linear interpolation between compact_1 and compact_25 runs
    at SF0.1 (modeled); at SF1 only compact_25 exists, so SF1 = interp(SF0.1) * t(compact_25,SF1)/t(compact_25,SF0.1)."""
    pts = []
    for run, nsel in (("compact_1", None), ("compact_25", None), ("compact_49", None)):
        r = VOPS.get((run, cfg, 0.1))
        if r:
            ver = [v for v in csv.DictReader(open(f"{VX}/verification.csv")) if v["config"] == cfg and f(v["sf"]) == 0.1 and v["run"] == run]
            k = int(re.match(r"(\d+)", ver[0]["detail"]).group(1))
            pts.append((k / int(r["rows"]), f(r["time_us"]), f(r["pct_bw"]), r["bound"]))
    pts.sort()
    for (s0, t0, p0, b0), (s1, t1, p1, b1) in zip(pts, pts[1:]):
        if s0 <= sel <= s1:
            t = t0 + (sel - s0) / (s1 - s0) * (t1 - t0)
            p = p0 + (sel - s0) / (s1 - s0) * (p1 - p0)
            break
    if sf == 0.1:
        return t, p, b0, pts
    a, b = VOPS.get(("compact_25", cfg, sf)), VOPS.get(("compact_25", cfg, 0.1))
    if not a:
        return None
    return t * f(a["time_us"]) / f(b["time_us"]), f(a["pct_bw"]), a["bound"] + " (compact_25 at SF1)", pts


OPS = [
    # id, vortex run, floor bytes/row (in+out the GPU operator must move), [(pim workload, schedule, issuer, result location)],
    # width note, normalization factor applied to the PIM time (1 = none)
    ("predicate int32 < const -> mask", "pred_i32", 4 + 1,
     [("pred_ship32", "op", "host", "1-bit mask stays in the bank rows"),
      ("pred_ship32_bool8out", "op", "host", "bool8 mask (cuDF format) stays in the bank rows"),
      ("pred_ship32+maskreadout", "op", "host", "1-bit mask read out by the GPU")],
     "int32 in on both sides; Vortex writes a bool8 mask to DRAM", 1.0),
    ("cast int32 -> int64", "cast", 4 + 8, [("ew_widen32to64", "op", "host", "int64 column written back to the rows")],
     "same widths", 1.0),
    ("multiply int64 x int64 -> int64", "mul", 8 + 8 + 8, [("ew_mul64x64", "op", "host", "int64 column written back to the rows")],
     "same widths", 1.0),
    ("sum int32", "reduce_i32", 4, [("sum_int32", "op", "host", "scalar read out (RD_MAC; Vortex: final tile + host read)")],
     "same widths", 1.0),
    ("sum int64", "reduce_i64", 8, [("sum_int64", "op", "host", "scalar read out (RD_MAC; Vortex: final tile + host read)")],
     "same widths", 1.0),
    ("compaction mask -> row ids", "COMPACT", None,
     [("compact_ids", "op", "host", "bank-local id segments stay in the rows (host-paced: whole slot written)"),
      ("compact_ids", "op", "seq", "bank-local id segments stay in the rows (sequencer: max-count writes)"),
      ("compact_ids+readout", "op", "host", "segments read out by the GPU (host-paced)"),
      ("compact_ids+readout", "op", "seq", "segments read out by the GPU (sequencer)")],
     "Vortex: global record-order int32 ids from a bool8 mask; PIM: bank-order ids from a 1-bit mask (different output "
     "order/semantics); Vortex time interpolated to the PIM selectivity (modeled)", 1.0),
    ("membership in 8-key set -> mask", "probe_8", 4 + 1,
     [("member_in8", "tile", "seq", "1-bit mask in the rows (8 compares on the open row, one operator)"),
      ("member_in8", "op", "host", "1-bit mask in the rows (8 separate compare operators)")],
     "width differs: Vortex int32 key column, PIM int16 (2 B/row); PIM time x2 (modeled: column commands scale with "
     "words per row)", 2.0),
    ("conjunctive range filter -> mask", "filter_conj", 10 + 1,
     [("pred_and", "tile", "seq", "1-bit mask in the rows (one operator, 2 ranges)"),
      ("pred_and", "op", "host", "1-bit mask in the rows (2 operators)")],
     "semantics differ: Vortex 3 ranges on 2+4+4 B columns (Q6 WHERE), PIM 2 ranges on 4+4 B; PIM time x 10/8 "
     "(modeled: per input byte)", 10 / 8),
]
op_rows = []
for name, vrun, fbpr, pims, wnote, nf in OPS:
    for sf in (0.1, 1.0):
        if vrun == "COMPACT":
            sel = lin[sf]["compact_sel"]
            vc = vx_compaction("S1", sf, sel)
            if not vc:
                continue
            tv, pct, bound, pts = vc
            rows = lin[sf]["n"]
            fbytes = rows * (1 + 4 * sel)
            vnote = (f"Vortex time modeled: interpolated at selectivity {100*sel:.2f} % between compact_1/25/49 "
                     f"({', '.join(f'{100*s:.1f}%={t:.1f}us' for s, t, _, _ in pts)}) at SF0.1" + (" and scaled by compact_25 SF1/SF0.1" if sf == 1 else ""))
            vlabel = "modeled (from simulated)"
        else:
            v = vx_time(vrun, "S1", sf)
            if not v:
                continue
            tv, pct, bound, lb, rows = v
            fbytes = rows * fbpr
            vnote = f"logical_bytes in operators.csv = {lb/rows:.2f} B/row"
            vlabel = "simulated"
        floor = fbytes / (BW["S1"] * 1e3)  # us
        for (w, sch, iss, loc) in pims:
            p = POPS.get((w, sch, iss, sf))
            if not p:
                continue
            if int(p["n_records"]) != rows:
                issues.append(f"{name} SF{sf}: rows Vortex {rows} vs PIM {p['n_records']}")
            tp = pim_scaled(p, "S1") * nf
            op_rows.append({
                "operator": name, "sf": sf, "rows": rows, "vortex_run": vrun if vrun != "COMPACT" else "compact_1/25/49",
                "vortex_S1_us": tv, "vortex_label": vlabel, "vortex_pct_of_configured_bw": pct, "vortex_bound": bound,
                "floor_bytes": fbytes, "floor_S1_us": floor, "floor_basis": f"bytes the GPU operator must read+write / {BW['S1']} GB/s (S1 configured)",
                "pim_variant": f"{w} [{sch}/{iss}]", "pim_result_location": loc,
                "pim_1ch_us_simulated": f(p["time_us"]), "pim_S1_us_modeled": tp, "pim_norm_factor": nf,
                "pim_T_records_per_row": int(p["T_records_per_row"]),
                "speedup_vs_sim_baseline": tv / tp, "speedup_vs_bw_floor": floor / tp,
                "width_semantics_note": wnote, "vortex_note": vnote,
                "label": "speedup modeled: simulated Vortex S1 (or modeled interpolation) / simulated PIM 1-ch time x 1/0.4375"})
# operators without a PIM counterpart run, or not executable
for name, run, why in [
    ("predicate int16", "pred_i16", "executable in principle (PCMP 16-bit lanes); no PIM run at int16"),
    ("range predicate int16", "range_i16", "executable in principle (one PCMP with lo/hi); no PIM run at int16"),
    ("mask AND", "mask_and", "PIM: register-only op folded into PCMP combine mode (no DRAM traffic, no separate timing)"),
    ("min/max int64", "minmax_i64", "not in isr_spec.json (no MIN/MAX accumulator); Sirius' use is a SUM-widening pre-check"),
    ("small-group aggregation", "groupby", "not comparable: Vortex 2 string keys (hash map) + 3 SUM(int64) + COUNT, 50 B/row moved; "
     "PIM gagg_sum_count: 1 uint8 key + 1 SUM(int16) + COUNT, 3 B/row; excluded from speedups"),
    ("gather 4 B", "gather_i32_25", "not executable at bank level (per-bank addresses; isr_spec not_executable_at_bank_level)"),
    ("gather 8 B", "gather_i64_25", "not executable at bank level"),
    ("hash build/probe", "-", "not executable at bank level (no inter-bank path)"),
    ("sort / merge / radix partition", "-", "not executable at bank level (inter-bank permutation)"),
    ("strings / LIKE", "-", "not executable at bank level (variable length; dictionary codes required)")]:
    v = vx_time(run, "S1", 0.1) if run != "-" else None
    extra = {}
    if run == "groupby":
        p = POPS.get(("gagg_sum_count", "op", "host", 0.1))
        extra = {"pim_variant": "gagg_sum_count [op/host] (not comparable)", "pim_1ch_us_simulated": f(p["time_us"]),
                 "pim_S1_us_modeled": pim_scaled(p, "S1")}
    op_rows.append({"operator": name, "sf": 0.1 if v else "", "rows": v[4] if v else "", "vortex_run": run,
                    "vortex_S1_us": v[0] if v else "", "vortex_label": "simulated" if v else "",
                    "vortex_pct_of_configured_bw": v[1] if v else "", "vortex_bound": v[2] if v else "",
                    "pim_variant": extra.get("pim_variant", "none"), "pim_1ch_us_simulated": extra.get("pim_1ch_us_simulated", ""),
                    "pim_S1_us_modeled": extra.get("pim_S1_us_modeled", ""), "pim_result_location": why,
                    "speedup_vs_sim_baseline": "", "speedup_vs_bw_floor": "", "label": "no speedup computed"})
OPCOLS = ["operator", "sf", "rows", "vortex_run", "vortex_S1_us", "vortex_label", "vortex_pct_of_configured_bw", "vortex_bound",
          "floor_bytes", "floor_S1_us", "pim_variant", "pim_result_location", "pim_1ch_us_simulated", "pim_S1_us_modeled",
          "pim_norm_factor", "pim_T_records_per_row", "speedup_vs_sim_baseline", "speedup_vs_bw_floor", "width_semantics_note",
          "vortex_note", "floor_basis", "label"]
wcsv("operators_speedup.csv", op_rows, OPCOLS)

# ---------------------------------------------------------------- 2. chain-level table
def vx_chain(q, cfg, sf, drop_precheck=False):
    rows = [r for r in VCH if r["chain"] == f"chain_{q}" and r["config"] == cfg and f(r["sf"]) == sf]
    if not rows:
        return None
    t = sum(f(r["time_us"]) for r in rows if not (drop_precheck and "minmax" in r["tag"]))
    n = sum(1 for r in rows if not (drop_precheck and "minmax" in r["tag"]))
    tot = VTOT[(f"chain_{q}", cfg, sf)]
    if not drop_precheck and abs(t - f(tot["sim_time_us"])) > 0.01 * t:
        issues.append(f"chains.csv sum {t} != chains_totals {tot['sim_time_us']} for {q} {cfg} {sf}")
    return t, n, tot


PWL = {"q6": {"main": "q6_main", "mirror": "q6_mirror_sirius", "mulwb": "q6_mulwb_sum", "fused": "q6_owner_fused"},
       "q1": {"main": "q1_main"}}
ch_rows, CHAIN = [], {}
for q in ("q6", "q1"):
    for sf in (0.01, 0.1, 1.0):
        for cfg in ("S1", "S4"):
            a = vx_chain(q, cfg, sf)
            if not a or (PWL[q]["main"], "tile", sf, "1ch") not in PCH:
                continue
            a_np = vx_chain(q, cfg, sf, drop_precheck=True)
            n = int(a[2]["rows"])
            bpr_pim = f(PCH[(PWL[q]["main"], "tile", sf, "1ch")]["input_bytes"]) / n
            bpr_gpu = q6_vx_Bpr if q == "q6" else q1_vx_Bpr
            T = {"a": a[0], "a_noprecheck": a_np[0],
                 "b_samebytes": n * bpr_pim / (BW[cfg] * 1e3), "b_gpuwidth": n * bpr_gpu / (BW[cfg] * 1e3),
                 "c": pim_scaled(PCH[(PWL[q]["main"], "op", sf, "1ch")], cfg),
                 "d": pim_scaled(PCH[(PWL[q]["main"], "tile", sf, "1ch")], cfg)}
            for k, key in (("e", "mirror"), ("e_op", "mirror"), ("mulwb", "mulwb"), ("f", "fused")):
                if key in PWL[q]:
                    sch = "op" if k == "e_op" else "tile"
                    r = PCH.get((PWL[q][key], sch, sf, "1ch"))
                    if r:
                        T[k] = pim_scaled(r, cfg)
            CHAIN[(q, sf, cfg)] = T
            desc = {
                "a": ("(a) baseline: Sirius-structured multi-kernel chain on Vortex " + cfg, "simulated",
                      f"{a[1]} launches incl. simx launch cost; incl. Sirius min/max SUM pre-check; host steps not included"),
                "a_noprecheck": ("(a') baseline without the min/max pre-check launches", "simulated",
                                 f"{a_np[1]} launches; PIM chains leave the pre-check out (planner policy), so (a') is the like-for-like baseline"),
                "b_samebytes": ("(b) baseline lower bound: GPU reads each input byte once at the configured bandwidth", "modeled",
                                f"{bpr_pim:.2f} B/row (the bytes the PIM chain reads) / {BW[cfg]} GB/s; stream reaches {STREAM_EFF.get(cfg)} % in calibration"),
                "b_gpuwidth": ("(b2) same, at the GPU's own column format", "modeled",
                               f"{bpr_gpu} B/row (Vortex/cuDF widths) / {BW[cfg]} GB/s"),
                "c": ("(c) PIM operator-at-a-time (one general operator sweeps the table per command sequence)", "modeled (simulated 1 ch / channels)",
                      f"{PWL[q]['main']} op/host; {CH[cfg]} channels"),
                "d": ("(d) PIM tile-at-a-time (in-memory sequencer runs the chain on each open row)", "modeled (simulated 1 ch / channels)",
                      f"{PWL[q]['main']} tile/seq"),
                "e": ("(e) PIM Sirius mirror: 2 casts + 64x64 multiply with write-back + masked sum, tile-at-a-time", "modeled (simulated 1 ch / channels)",
                      "q6_mirror_sirius tile/seq (compaction+gathers still replaced by the mask)"),
                "e_op": ("(e-op) PIM Sirius mirror, operator-at-a-time", "modeled (simulated 1 ch / channels)", "q6_mirror_sirius op/host"),
                "mulwb": ("(e2) PIM multiply written back then masked sum, tile-at-a-time", "modeled (simulated 1 ch / channels)", "q6_mulwb_sum tile/seq"),
                "f": ("(f) owner's fused command (non-compliant reference: query-specific fusion)", "modeled (simulated 1 ch / channels)",
                      f"q6_owner_fused; reads {fused_Bpr:.1f} B/row (qty int32), not the same widths"),
            }
            for k, v in T.items():
                ch_rows.append({"query": q.upper(), "sf": sf, "config": cfg, "rows": n, "row_id": k, "description": desc[k][0],
                                "time_us": v, "ratio": "", "label": desc[k][1], "note": desc[k][2]})
            for num, den, txt in (("a", "c", "simulated baseline vs PIM operator-at-a-time"),
                                  ("a", "d", "simulated baseline vs PIM tile-at-a-time (mixes in the plan change: masked aggregate replaces compaction+gather)"),
                                  ("a_noprecheck", "d", "like-for-like work (no pre-check) vs PIM tile-at-a-time (still mixes in the plan change)"),
                                  ("b_samebytes", "d", "HONEST PIM-specific: best memory-bound GPU plan reading the same bytes vs PIM tile-at-a-time"),
                                  ("b_gpuwidth", "d", "GPU floor at cuDF widths vs PIM tile-at-a-time (includes the narrower PIM format)"),
                                  ("b_samebytes", "c", "GPU floor vs PIM operator-at-a-time"),
                                  ("a", "e", "simulated baseline vs PIM Sirius mirror"),
                                  ("b_samebytes", "e", "GPU floor vs PIM Sirius mirror"),
                                  ("a", "f", "simulated baseline vs fused reference (not compliant)")):
                if num in T and den in T:
                    ch_rows.append({"query": q.upper(), "sf": sf, "config": cfg, "rows": n, "row_id": f"{num}/{den}",
                                    "description": txt, "time_us": "", "ratio": T[num] / T[den], "label": "modeled speedup", "note": ""})
# scaling invariance S4 vs S1
for (q, sf, cfg), T in list(CHAIN.items()):
    if cfg != "S4" or (q, sf, "S1") not in CHAIN:
        continue
    T1 = CHAIN[(q, sf, "S1")]
    for num, den in (("a", "c"), ("a", "d"), ("b_samebytes", "d"), ("a", "e")):
        if num in T and den in T:
            r4, r1 = T[num] / T[den], T1[num] / T1[den]
            ok = abs(r4 / r1 - 1) <= 0.10
            ch_rows.append({"query": q.upper(), "sf": sf, "config": "S4 vs S1", "rows": "", "row_id": f"check {num}/{den}",
                            "description": f"scaling invariance: S4 speedup / S1 speedup ({'within' if ok else 'OUTSIDE'} 10 %)",
                            "time_us": "", "ratio": r4 / r1, "label": "check",
                            "note": f"S1 {r1:.2f}x, S4 {r4:.2f}x; Vortex S4/S1 time {T1[num]/T[num]:.2f}x vs 4.00x ideal" if num == "a" else f"S1 {r1:.2f}x, S4 {r4:.2f}x"})
            if not ok:
                issues.append(f"{q} SF{sf}: speedup {num}/{den} S4 {r4:.2f} vs S1 {r1:.2f} differs > 10 %")
# full RTX 5070 projection (48 cores vs 21 channels)
for (q, sf, cfg), T in list(CHAIN.items()):
    if cfg != "S1":
        continue
    P = {}
    P["a"] = T["a"] / 48 * 1.0  # S1 x 1/48 (modeled linear in cores and bandwidth)
    P["a_noprecheck"] = T["a_noprecheck"] / 48
    tot = VTOT[(f"chain_{q}", "S1", sf)]
    P["a_launchfix"] = (T["a"] - f(tot["launch_cost_us_in_sim"])) / 48 + int(tot["launches"]) * REAL_LAUNCH_US
    if (q, sf, "S4") in CHAIN:
        P["a_fromS4"] = CHAIN[(q, sf, "S4")]["a"] / 12
    n = int(VTOT[(f"chain_{q}", "S1", sf)]["rows"])
    P["b_samebytes"] = T["b_samebytes"] * BW["S1"] / BW["5070"]
    P["b_gpuwidth"] = T["b_gpuwidth"] * BW["S1"] / BW["5070"]
    for k in ("c", "d", "e", "e_op", "mulwb", "f"):
        if k in T:
            P[k] = T[k] * CH["S1"] / CH["5070"]
    for k, wl, sch in (("d_direct", PWL[q]["main"], "tile"), ("c_direct", PWL[q]["main"], "op")):
        r = PCH.get((wl, sch, sf, "5070_share_1of21"))
        if r:
            P[k] = f(r["time_us"])
    CHAIN[(q, sf, "5070")] = P
    notes = {"a": "S1 x 1/48: assumes simx time scales linearly with cores+bandwidth (S4/S1 checks this) INCLUDING the simx launch cost",
             "a_noprecheck": "(a') x 1/48",
             "a_launchfix": f"(S1 - simx launch cost {tot['launch_cost_us_in_sim']} us)/48 + {tot['launches']} launches x {REAL_LAUNCH_US} us real-GPU launch time (modeled)",
             "a_fromS4": "S4 x 1/12 (cross-check of the linear projection)",
             "b_samebytes": "same bytes / 672 GB/s", "b_gpuwidth": "cuDF-width bytes / 672 GB/s",
             "c": "1 ch / 21 (linear in channels)", "d": "1 ch / 21 (linear in channels)", "e": "1 ch / 21", "e_op": "1 ch / 21",
             "mulwb": "1 ch / 21", "f": "1 ch / 21",
             "d_direct": "simulated 1/21 share on one channel (AiM builder's direct check)", "c_direct": "simulated 1/21 share on one channel"}
    for k, v in P.items():
        ch_rows.append({"query": q.upper(), "sf": sf, "config": "5070 (projected)", "rows": n, "row_id": k,
                        "description": "full RTX 5070: " + k, "time_us": v, "ratio": "",
                        "label": "simulated" if k.endswith("direct") else "modeled", "note": notes[k]})
    for num, den in (("a", "c"), ("a", "d"), ("a_noprecheck", "d"), ("b_samebytes", "d"), ("a", "e"), ("a_launchfix", "d"), ("a_fromS4", "d")):
        if num in P and den in P:
            ch_rows.append({"query": q.upper(), "sf": sf, "config": "5070 (projected)", "rows": n, "row_id": f"{num}/{den}",
                            "description": "full-5070 speedup", "time_us": "", "ratio": P[num] / P[den], "label": "modeled speedup",
                            "note": "identical to S1 by construction for a/x and b/x (both sides scaled linearly: 48/1 cores, 21/0.4375 channels)" if num in ("a", "b_samebytes", "a_noprecheck") else ""})
wcsv("chains_speedup.csv", ch_rows, ["query", "sf", "config", "rows", "row_id", "description", "time_us", "ratio", "label", "note"])

# ---------------------------------------------------------------- 3a. host term and end-to-end at full-5070 scale (modeled)
e2e = []


def add(sec, q, sf, case, metric, value, unit, label, basis):
    e2e.append({"section": sec, "query": q, "sf": sf, "case": case, "metric": metric, "value": value, "unit": unit,
                "label": label, "basis": basis})


SEQ_OVH = {}
for (wl, sch, sf, cf), r in PCH.items():
    SEQ_OVH[(wl, sch, sf, cf)] = f(r["t_sequencer_us"]) - f(r["time_us"])
for q, sf, proj in (("q6", 1.0, False), ("q1", 0.1, False), ("q1", 1.0, True)):
    Q = q.upper()
    base_sf = 0.1 if proj else sf
    P = CHAIN[(q, base_sf, "5070")]
    k = 10.0 if proj else 1.0  # Q1 SF1 baseline: SF0.1 x 10 (modeled linear in rows)
    tot = VTOT[(f"chain_{q}", "S1", base_sf)]
    projnote = " (Q1 SF1 baseline = SF0.1 simulated x 10, modeled linear in rows; Vortex Q6 per-row time fell 11 % SF0.1->SF1)" if proj else ""
    base_kernel = P["a"] * k
    base_kernel_lf = (f(tot["sim_time_us"]) * k - f(tot["launch_cost_us_in_sim"])) / 48 + int(tot["launches"]) * REAL_LAUNCH_US
    host = f(tot["host_term_us_modeled"])
    host_chk = int(tot["host_gaps_readback"]) * GAP_READBACK_US + int(tot["host_gaps_alloc"]) * GAP_ALLOC_US
    assert abs(host - host_chk) < 0.2, (host, host_chk)
    host_sw = (int(tot["host_gaps_readback"]) + int(tot["host_gaps_alloc"])) * GAP_ALLOC_US
    omit = int(tot["omitted_launches"]) * REAL_LAUNCH_US
    add("host+e2e", Q, sf, "baseline", "kernel time, S1 x 1/48", base_kernel, "us", "modeled (from simulated)", "chains_totals sim_time_us / 48" + projnote)
    add("host+e2e", Q, sf, "baseline", "kernel time, launch-cost corrected", base_kernel_lf, "us", "modeled",
        f"(sim - simx launch cost)/48 + {tot['launches']} x {REAL_LAUNCH_US} us")
    add("host+e2e", Q, sf, "baseline", "host gaps (measured medians x chain gaps)", host, "us", "modeled",
        f"{tot['host_gaps_readback']} read-back gaps x {GAP_READBACK_US} + {tot['host_gaps_alloc']} alloc gaps x {GAP_ALLOC_US} (chains_totals.csv); one batch")
    add("host+e2e", Q, sf, "baseline", "host gaps if size read-backs removed in software", host_sw, "us", "modeled",
        "all gaps priced as alloc-only gaps (notes 05/06: over-allocation / device-side sizes remove the read-back without PIM)")
    add("host+e2e", Q, sf, "baseline", "omitted bookkeeping launches", omit, "us", "modeled", f"{tot['omitted_launches']} x {REAL_LAUNCH_US} us")
    add("host+e2e", Q, sf, "baseline", "END-TO-END (kernel + host gaps + omitted)", base_kernel + host + omit, "us", "modeled", "")
    add("host+e2e", Q, sf, "baseline", "END-TO-END, software-improved host", base_kernel + host_sw + omit, "us", "modeled", "")
    wl = PWL[q]["main"]
    tile_1ch = PCH[(wl, "tile", sf, "1ch")]
    op_1ch = PCH[(wl, "op", sf, "1ch")]
    share = PCH.get((wl, "tile", sf, "5070_share_1of21"))
    share_op = PCH.get((wl, "op", sf, "5070_share_1of21"))
    t_tile = pim_scaled(tile_1ch, "5070"); t_op = pim_scaled(op_1ch, "5070")
    seq_cmds = int(tile_1ch["host_cmds_sequencer"])
    hp_cmds = int(share_op["host_cmds_hostpaced"]) if share_op else int(op_1ch["host_cmds_hostpaced"]) / 21
    hp_src = "simulated 1/21 share" if share_op else "1-ch count / 21 (modeled)"
    ovh = SEQ_OVH[(wl, "tile", sf, "1ch")]
    n_ops = int(op_1ch["n_ops"])
    for model, ns in (("posted", POSTED_NS), ("synchronous", SYNC_NS)):
        seq_host = ovh + seq_cmds * ns / 1e3 + GAP_ALLOC_US
        add("host+e2e", Q, sf, f"PIM tile/sequencer, {model}", "PIM chain time", t_tile, "us", "modeled (from simulated)", "1 ch / 21")
        add("host+e2e", Q, sf, f"PIM tile/sequencer, {model}", "host: start+completion+params+read-out", ovh + seq_cmds * ns / 1e3, "us", "modeled",
            f"{ovh:.2f} us start/completion (chains.csv) + {seq_cmds} host commands x {ns:g} ns (note 09 issue model)")
        add("host+e2e", Q, sf, f"PIM tile/sequencer, {model}", "host gap to launch the chain", GAP_ALLOC_US, "us", "modeled",
            "one alloc-only real-GPU gap (measured median, note 04)")
        add("host+e2e", Q, sf, f"PIM tile/sequencer, {model}", "END-TO-END", t_tile + seq_host, "us", "modeled", "")
        hp_host = n_ops * GAP_ALLOC_US + hp_cmds * ns / 1e3
        add("host+e2e", Q, sf, f"PIM operator/host-paced, {model}", "PIM chain time", t_op, "us", "modeled (from simulated)", "1 ch / 21")
        add("host+e2e", Q, sf, f"PIM operator/host-paced, {model}", "host: gaps + issued commands", hp_host, "us", "modeled",
            f"{n_ops} operator launches x {GAP_ALLOC_US} us + {hp_cmds:.0f} commands ({hp_src}) x {ns:g} ns")
        add("host+e2e", Q, sf, f"PIM operator/host-paced, {model}", "END-TO-END", t_op + hp_host, "us", "modeled", "")
    b_e2e = base_kernel + host + omit
    for model, ns in (("posted", POSTED_NS), ("synchronous", SYNC_NS)):
        p_e2e = t_tile + ovh + seq_cmds * ns / 1e3 + GAP_ALLOC_US
        add("host+e2e", Q, sf, f"speedup tile/seq {model}", "baseline e2e / PIM e2e", b_e2e / p_e2e, "x", "modeled", "")
        add("host+e2e", Q, sf, f"speedup tile/seq {model}", "baseline e2e (software-improved host) / PIM e2e",
            (base_kernel + host_sw + omit) / p_e2e, "x", "modeled", "")
        floor_e2e = P["b_samebytes"] * k + (1 + 0) * GAP_ALLOC_US
        add("host+e2e", Q, sf, f"speedup tile/seq {model}", "GPU floor + one launch gap / PIM e2e", floor_e2e / p_e2e, "x", "modeled",
            "best memory-bound GPU plan: one pass at 672 GB/s + one alloc-only gap")

# ---------------------------------------------------------------- 3b. query-level Amdahl on the real GPU (measured + modeled)
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, "pim_exploration/sf10_scaling/scripts"))
import siriuslog  # read-only helper (same file as tpch_sf1/siriuslog.py)

MAP = list(csv.DictReader(open(f"{AM}/sirius_to_pim_mapping.csv")))


def norm_name(n):
    """nsys demangled name -> the namespace-stripped form the AiM builder's regexes were written against
    (tpch_q1_analysis/analysis/results/q1/q1_warm_kernel_list.json style)."""
    n = re.sub(r"__\d+::", "", n)
    n = n.replace("binops::compiled::ops::", "binops::").replace("binops::compiled::", "binops::")
    n = n.replace("cub::detail::", "").replace("cuco::detail::", "cuco::").replace("cudf::detail::", "")
    n = n.replace("thrust::", "").replace("cudf::", "").replace("cuda::std::", "std::")
    n = re.sub(r"\((?:bool|cub::\w+|[\w:]+)\)(\d+)", r"\1", n)
    return n


def classify(name, q):
    nm = norm_name(name)
    for r in MAP:
        if not r["query"].upper().startswith(q) or r["sirius_kernel_regex"].startswith("("):
            continue
        if re.search(r["sirius_kernel_regex"], nm) or re.search(r["sirius_kernel_regex"], name):
            return r["status"], r["sirius_role"]
    return "UNMATCHED", ""


def union(iv):
    tot, cs, ce = 0, None, None
    for s, e in sorted(iv):
        if ce is None or s > ce:
            if ce is not None:
                tot += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return tot + ((ce - cs) if ce is not None else 0)


UNM = collections.defaultdict(collections.Counter)


def real_run(R, q):
    con = sqlite3.connect(f"file:{glob.glob(f'{R}/traces/q*_nsys.sqlite')[0]}?mode=ro", uri=True)
    t0 = con.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
    ts = lambda l: siriuslog.ts_ms(l) * 1e6 - t0
    P = json.load(open(f"{R}/pcie.json")); nwarm = sum(not p["measured"] for p in P["per_iteration"])
    L, _ = siriuslog.read_run(f"{R}/traces/sirius_log_nsys")
    qb, tb, qe = [], [], []
    for l in L:
        sql = siriuslog.sql_of(l)
        if sql is not None:
            if not sql.lower().startswith(siriuslog.DDL):
                qb.append(ts(l))
        elif "QueryBegin: transparent_execution" in l:
            tb.append(ts(l))
        elif l.endswith("QueryEnd") and "sirius_context" in l and len(qe) < len(tb):
            qe.append(ts(l))
    S = dict(con.execute("select id, value from StringIds"))
    K = [(s, e, S[d]) for s, e, d in con.execute("select start, end, demangledName from CUPTI_ACTIVITY_KIND_KERNEL")]
    O = [(s, e) for s, e in con.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMCPY")] + \
        [(s, e) for s, e in con.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMSET")]
    its = []
    for i in range(len(qb)):
        if i < nwarm or i >= len(tb) or i >= len(qe):
            continue
        lo, hi = tb[i] - 1e6, qe[i] + 1e6
        ks = [(s, min(e, hi), n) for s, e, n in K if lo <= s < hi]
        os_ = [(s, min(e, hi)) for s, e in O if lo <= s < hi]
        cls = collections.defaultdict(lambda: [0, 0])
        repl, keep, keep_pc, batches = [], [], [], 0
        for s, e, n in ks:
            st, role = classify(n, q)
            cls[st][0] += 1; cls[st][1] += e - s
            if st == "UNMATCHED":
                UNM[(q, R)][norm_name(n)[:160]] += 1
            if "LessEqual" in norm_name(n) and q == "Q1" or "compute_column_kernel" in n and q == "Q6":
                batches += 1
            (repl if st.startswith(("mapped", "removed")) else keep).append((s, e))
            if not st.startswith(("mapped", "removed", "left out")):
                keep_pc.append((s, e))
        busy = union([(s, e) for s, e, _ in ks] + os_)
        its.append({"iter": i + 1, "planning_ms": (tb[i] - qb[i]) / 1e6, "engine_ms": (qe[i] - tb[i]) / 1e6,
                    "busy_ms": busy / 1e6, "busy_wo_repl_ms": union(keep + os_) / 1e6,
                    "busy_wo_repl_pc_ms": union(keep_pc + os_) / 1e6,
                    "kernel_sum_ms": sum(e - s for s, e, _ in ks) / 1e6, "launches": len(ks), "batches": batches,
                    "cls": {k: (v[0], v[1] / 1e6) for k, v in cls.items()}})
    # cross-check against the existing breakdown
    B = json.load(open(f"{R}/nsys_iteration_breakdown.json"))
    for it in its:
        b = [x for x in B if x["iter"] == it["iter"]][0]
        if abs(b["gpu_busy_ms"] - it["busy_ms"]) > 1e-3 or b["kernels"] != it["launches"]:
            issues.append(f"{R} iter {it['iter']}: busy {it['busy_ms']:.4f} vs breakdown {b['gpu_busy_ms']:.4f}")
    return its


RUNS = [("Q6", 1, "tpch_q1_analysis/analysis/results/q6", "SF1 pipeline yaml (0.25 pool, ~77 MB batches)"),
        ("Q6", 10, "pim_exploration/sf10_scaling/q6", "sf10_main (0.85 pool, 262 MB batches)"),
        ("Q1", 1, "pim_exploration/sf10_scaling/q1/sf1_sf1pipe", "SF1 pipeline yaml (0.25 pool, ~77 MB batches)"),
        ("Q1", 10, "pim_exploration/sf10_scaling/q1", "sf10_main (0.85 pool, 262 MB batches)")]
detail = []
med = statistics.median
AMD = {}
for Q, sf, rel, cfgnote in RUNS:
    R = os.path.join(ROOT, rel)
    its = real_run(R, Q)
    tj = json.load(open(f"{R}/timing.json"))
    wall = tj["mean_ms"]
    m = {k: med(it[k] for it in its) for k in ("planning_ms", "engine_ms", "busy_ms", "busy_wo_repl_ms", "busy_wo_repl_pc_ms",
                                                "kernel_sum_ms", "launches", "batches")}
    cls_keys = sorted({k for it in its for k in it["cls"]})
    for k in cls_keys:
        m[f"n[{k}]"] = med(it["cls"].get(k, (0, 0))[0] for it in its)
        m[f"ms[{k}]"] = med(it["cls"].get(k, (0, 0))[1] for it in its)
    if "UNMATCHED" in cls_keys:
        issues.append(f"{Q} SF{sf}: {m['n[UNMATCHED]']} launches/iteration not matched by sirius_to_pim_mapping.csv regexes "
                      f"(counted as not replaceable): " + "; ".join(f"{c//len(its)}x {k[:90]}" for k, c in UNM[(Q, R)].most_common(6)))
    repl_ms = m["busy_ms"] - m["busy_wo_repl_ms"]
    repl_pc_ms = m["busy_ms"] - m["busy_wo_repl_pc_ms"]
    q = Q.lower()
    sim_sf = 1.0 if q == "q6" else 0.1
    T = CHAIN[(q, sim_sf, "S1")]; P5 = CHAIN[(q, sim_sf, "5070")]
    s_ad = T["a_noprecheck"] / T["d"]; s_bd = T["b_samebytes"] / T["d"]
    t_pim_abs_ms = P5["d"] / 1e3 * (sf / sim_sf)  # projected PIM chain on all rows of this SF (modeled linear in rows)
    tot = VTOT[(f"chain_{q}", "S1", sim_sf)]
    gaps_per_batch = f(tot["host_term_us_modeled"]) / 1e3
    host_removed_raw = max(0.0, m["batches"] * (gaps_per_batch - GAP_ALLOC_US / 1e3))
    idle_ms = m["engine_ms"] - m["busy_ms"]  # GPU-idle time inside the (traced) engine window
    host_removed_ms = min(host_removed_raw, idle_ms)
    if host_removed_raw > idle_ms:
        issues.append(f"{Q} SF{sf}: modeled chain host gaps {host_removed_raw:.2f} ms exceed the measured GPU-idle engine time "
                      f"{idle_ms:.2f} ms -> capped (the 4 pipeline threads overlap their gaps; the per-batch gap model overcounts)")
    AMD[(Q, sf)] = {"wall_ms": wall, "wall_median_ms": tj["median_ms"], **m, "repl_busy_ms": repl_ms, "repl_busy_pc_ms": repl_pc_ms,
                    "s_ad": s_ad, "s_bd": s_bd, "t_pim_abs_ms": t_pim_abs_ms, "host_removed_ms": host_removed_ms, "cfg": cfgnote, "rel": rel}
    for it in its:
        detail.append({"query": Q, "sf": sf, "run": rel, "iter": it["iter"], "planning_ms": it["planning_ms"], "engine_ms": it["engine_ms"],
                       "busy_ms": it["busy_ms"], "busy_wo_repl_ms": it["busy_wo_repl_ms"], "kernel_sum_ms": it["kernel_sum_ms"],
                       "launches": it["launches"], "batches": it["batches"],
                       **{f"ms[{k}]": it["cls"].get(k, (0, 0))[1] for k in cls_keys}, **{f"n[{k}]": it["cls"].get(k, (0, 0))[0] for k in cls_keys}})
    lab = "measured (real GPU, nsys sqlite + timing.json)"
    src = f"{rel}; {cfgnote}"
    add("amdahl", Q, sf, "real GPU", "wall (untraced .timer mean)", wall, "ms", "measured", f"{rel}/timing.json (1 ms resolution; median {tj['median_ms']})")
    add("amdahl", Q, sf, "real GPU", "planning (median, nsys run)", m["planning_ms"], "ms", lab, src + "; 1 ms log stamps")
    add("amdahl", Q, sf, "real GPU", "engine window (median, nsys run)", m["engine_ms"], "ms", lab, src)
    add("amdahl", Q, sf, "real GPU", "GPU busy (union kernel+copy+memset)", m["busy_ms"], "ms", lab, src)
    add("amdahl", Q, sf, "real GPU", "kernel time summed", m["kernel_sum_ms"], "ms", lab, src)
    add("amdahl", Q, sf, "real GPU", "launches / scan batches", f"{m['launches']:.0f} / {m['batches']:.0f}", "", lab, src)
    for k in cls_keys:
        add("amdahl", Q, sf, "real GPU", f"kernel ms by PIM mapping status: {k}", m[f"ms[{k}]"], "ms", lab,
            f"{m[f'n[{k}]']:.0f} launches; sim/aim_pim/results/sirius_to_pim_mapping.csv regexes")
    add("amdahl", Q, sf, "real GPU", "replaceable share of GPU busy (mapped+removed)", repl_ms / m["busy_ms"], "fraction", lab,
        "busy - union(busy without replaceable kernels); overlap-aware")
    add("amdahl", Q, sf, "real GPU", "replaceable share incl. min/max pre-check", repl_pc_ms / m["busy_ms"], "fraction", lab,
        "pre-check is planner policy (left out by both PIM mapping and as removable in software)")
    for case, s, extra in (("chain speedup (b)/(d) = same-bytes GPU floor / PIM tile", s_bd, 0.0),
                           ("chain speedup (a')/(d) = simulated baseline / PIM tile", s_ad, 0.0),
                           ("speedup -> infinity (upper bound)", float("inf"), 0.0),
                           ("replace by projected PIM chain time (absolute)", None, 0.0),
                           ("(b)/(d) + chain host gaps removed", s_bd, host_removed_ms),
                           ("infinity + chain host gaps removed", float("inf"), host_removed_ms)):
        saved_busy = repl_ms - t_pim_abs_ms if s is None else repl_ms * (1 - 1 / s)
        saved_busy = max(saved_busy, 0.0)
        new_wall = wall - saved_busy - extra
        add("amdahl", Q, sf, case, "accelerated factor s", s if s is not None else "abs", "x", "modeled",
            f"Q6 from SF1 chain, Q1 from SF0.1 chain (S1); PIM abs time = {t_pim_abs_ms*1e3:.1f} us (5070 linear, x SF/{sim_sf:g})")
        add("amdahl", Q, sf, case, "GPU busy after", m["busy_ms"] - saved_busy, "ms", "modeled", "")
        add("amdahl", Q, sf, case, "GPU-busy speedup", m["busy_ms"] / (m["busy_ms"] - saved_busy), "x", "modeled", "")
        add("amdahl", Q, sf, case, "host time removed", extra, "ms", "modeled",
            (f"{m['batches']:.0f} batches x ({gaps_per_batch*1e3:.1f} us chain gaps - {GAP_ALLOC_US} us sequencer gap) = "
             f"{host_removed_raw:.3f} ms, capped at the measured GPU-idle engine time {idle_ms:.3f} ms") if extra else "")
        add("amdahl", Q, sf, case, "wall after", new_wall, "ms", "modeled", "planning and non-replaceable kernels stay; saved kernel time assumed on the critical path (upper bound)")
        add("amdahl", Q, sf, case, "wall-clock speedup", wall / new_wall, "x", "modeled", "")
wcsv("end_to_end.csv", e2e, ["section", "query", "sf", "case", "metric", "value", "unit", "label", "basis"])
dcols = sorted({k for d in detail for k in d}, key=lambda k: (k.startswith(("ms[", "n[")), k))
for d in detail:
    for k in dcols:
        d.setdefault(k, 0)
wcsv("realgpu_amdahl_detail.csv", detail, ["query", "sf", "run", "iter"] + [k for k in dcols if k not in ("query", "sf", "run", "iter")])

json.dump({"chains": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in CHAIN.items()},
           "amdahl": {f"{k[0]}|SF{k[1]}": v for k, v in AMD.items()},
           "pim_compaction_selectivity": lin, "issues": issues,
           "constants": {"BW_GBs": BW, "channels": CH, "REAL_LAUNCH_US": REAL_LAUNCH_US, "GAP_ALLOC_US": GAP_ALLOC_US,
                         "GAP_READBACK_US": GAP_READBACK_US, "stream_eff_pct": STREAM_EFF}},
          open(os.path.join(OUT, "combined_numbers.json"), "w"), indent=1, default=str)
print("ISSUES:"); [print(" -", i) for i in issues]
