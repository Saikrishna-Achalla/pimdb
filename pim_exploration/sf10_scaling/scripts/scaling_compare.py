"""SF1 vs SF10 comparison across configs -> sf10_scaling/scaling_table.csv + scaling_summary.json (+ printed tables).

Usage: venv/bin/python -I scaling_compare.py
Inputs (all produced by scaling_extract.py, see run_extract.sh):
  q<N>/scaling_metrics.json                 SF10, CFG=main  (0.85 GPU pool, derived batch 262 MB)
  q<N>/sf1_main/scaling_metrics.json        SF1,  CFG=main  (same yaml)
  q<N>/sf10_b77/scaling_metrics.json        SF10, CFG=b77   (0.85 pool, batch settings forced to 77 MB)
  q<N>/sf1_pipeline_metrics.json            SF1,  existing tpch_sf1 pipeline results (0.25 pool -> batch 77 MB);
                                            for Q1 (no pipeline result) q1/sf1_sf1pipe/scaling_metrics.json (same yaml, rerun)
Comparisons: "asked" = SF10 main vs existing SF1 pipeline; "fixed_config" = SF10 main vs SF1 main;
             "fixed_batch" = SF10 b77 vs SF1 pipeline (both 77 MB batches).
Family launch classes (per comparison): const (ratio <= 1.25), grew (ratio >= 1.75), mid otherwise; new = absent at SF1.
Extrapolation (MODELED): two-point linear fits y = a + b*SF through SF1 and SF10 for wall, GPU busy and launches at a
fixed config; SF_max from the measured SF10 pool high-water scaled linearly with SF.
"""
import csv, json, os, statistics

E = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QS = [1, 3, 6, 9, 10, 13, 16, 18]
BATCH = {"sf10_main": 262.3, "sf1_main": 262.3, "sf10_b77": 77.2, "sf1_pipe": 77.2}
SFOF = {"sf10_main": 10, "sf1_main": 1, "sf10_b77": 10, "sf1_pipe": 1}
POOL = {"sf10_main": 0.85, "sf1_main": 0.85, "sf10_b77": 0.85, "sf1_pipe": 0.25}


def path(q, cfg):
    return {"sf10_main": f"{E}/q{q}/scaling_metrics.json", "sf1_main": f"{E}/q{q}/sf1_main/scaling_metrics.json",
            "sf10_b77": f"{E}/q{q}/sf10_b77/scaling_metrics.json",
            "sf1_pipe": f"{E}/q{q}/sf1_sf1pipe/scaling_metrics.json" if q == 1 else f"{E}/q{q}/sf1_pipeline_metrics.json"}[cfg]


def row(q, cfg, m):
    n = m["nsys_median"]; rows = sum(v for v in (m["table_rows"] or {}).values() if v)
    busy = n["gpu_busy_ms"]
    return {"query": q, "config": cfg, "sf": SFOF[cfg], "gpu_pool_fraction": POOL[cfg], "batch_MB": BATCH[cfg],
            "warm_ms": m["warm_ms"], "warm_min_ms": m["warm_min_ms"], "warm_max_ms": m["warm_max_ms"], "cpu_ms": m["cpu_ms"],
            "gpu_equals_cpu": m["gpu_equals_cpu"], "pcie": m["pcie_overall"],
            "planning_ms_log": m["timing_log_planning_ms"], "engine_ms_log": m["timing_log_engine_ms"],
            "engine_ms_nsys": n["engine_ms"], "gpu_busy_ms": round(busy, 4), "busy_pct_wall": round(100 * busy / m["warm_ms"], 2),
            "idle_ms": round(m["warm_ms"] - busy, 3),
            "kernels": n["kernels"], "gpu_ops": n["gpu_ops"], "kernel_ms": round(n["kernel_ms"], 4),
            "launches_lt5us": n["lt5us"], "launches_ge100us": n["ge100us"], "kernel_ms_in_ge100us": round(n["ge100us_ms"], 3),
            "launches_grid_lt48": n["grid_lt48"], "launches_grid_1": n["grid_1"],
            "pinned_MB": round((m["pinned_bytes"] or 0) / 1e6, 1), "pool_peak_after_pin_MB": round((m["pool_peak_after_pin_bytes"] or 0) / 1e6, 1),
            "floor_ms_pinned_once": round((m["pinned_bytes"] or 0) / 672e6, 4),
            "busy_x_floor": round(busy / ((m["pinned_bytes"] or 1) / 672e6), 2),
            "pool_peak_end_MB": round((m["pool_peak_end_bytes"] or 0) / 1e6, 1), "rows_in_tables": rows,
            "wall_ns_per_row": round(1e6 * m["warm_ms"] / rows, 3) if rows else None,
            "busy_ns_per_row": round(1e6 * busy / rows, 4) if rows else None, "result_rows": m["result_rows"]}


def fam_cmp(a, b):
    """a = SF1 metrics, b = SF10 metrics; per-family launches and kernel time (representative warm iteration)."""
    Fa, Fb = a["rep_iter"]["families"], b["rep_iter"]["families"]
    out = {}
    for f in set(Fa) | set(Fb):
        x, y = Fa.get(f, {"launches": 0, "ns": 0, "phase": Fb.get(f, {}).get("phase")}), Fb.get(f, {"launches": 0, "ns": 0, "phase": Fa.get(f, {}).get("phase")})
        lr = (y["launches"] / x["launches"]) if x["launches"] else None
        cls = "new" if not x["launches"] else "gone" if not y["launches"] else "const" if lr <= 1.25 else "grew" if lr >= 1.75 else "mid"
        out[f] = {"phase": x.get("phase") or y.get("phase"), "launches_sf1": x["launches"], "launches_sf10": y["launches"],
                  "launch_ratio": lr, "class": cls, "us_sf1": x["ns"] / 1e3, "us_sf10": y["ns"] / 1e3,
                  "time_ratio": (y["ns"] / x["ns"]) if x["ns"] else None}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["us_sf10"]))


def comp(a, b, ra, rb):
    F = fam_cmp(a, b)
    by = lambda c: sum(v["launches_sf10"] - v["launches_sf1"] for v in F.values() if v["class"] == c)
    return {"launches_sf1": ra["kernels"], "launches_sf10": rb["kernels"], "launch_ratio": rb["kernels"] / ra["kernels"],
            "gpu_ops_ratio": rb["gpu_ops"] / ra["gpu_ops"],
            "wall_ratio": rb["warm_ms"] / ra["warm_ms"], "busy_ratio": rb["gpu_busy_ms"] / ra["gpu_busy_ms"],
            "kernel_time_ratio": rb["kernel_ms"] / ra["kernel_ms"], "idle_ratio": rb["idle_ms"] / ra["idle_ms"] if ra["idle_ms"] > 0 else None,
            "busy_pct_wall_sf1": ra["busy_pct_wall"], "busy_pct_wall_sf10": rb["busy_pct_wall"],
            "wall_ns_per_row_sf1": ra["wall_ns_per_row"], "wall_ns_per_row_sf10": rb["wall_ns_per_row"],
            "added_launches_by_class": {c: by(c) for c in ("const", "mid", "grew", "new", "gone")},
            "families_grew": [f for f, v in F.items() if v["class"] in ("grew", "new")],
            "families_const": [f for f, v in F.items() if v["class"] == "const"],
            "families": F}


def lin(y1, y10):  # y = a + b*SF through (1, y1), (10, y10)
    b = (y10 - y1) / 9.0
    return y1 - b, b


rows, summ = [], {"note_labels": "measured: per-config rows; inferred: ratios; modeled: extrapolation", "queries": {}}
for q in QS:
    M = {c: json.load(open(path(q, c))) for c in BATCH if os.path.exists(path(q, c))}
    R = {c: row(q, c, m) for c, m in M.items()}
    rows += R.values()
    s = {"rows": R, "comparisons": {}}
    for name, (c1, c10) in {"asked_sf10main_vs_sf1pipeline": ("sf1_pipe", "sf10_main"),
                            "fixed_config_main": ("sf1_main", "sf10_main"),
                            "fixed_batch_77MB": ("sf1_pipe", "sf10_b77")}.items():
        if c1 in M and c10 in M:
            s["comparisons"][name] = comp(M[c1], M[c10], R[c1], R[c10])
    if "sf1_main" in R and "sf10_main" in R:  # MODELED extrapolation at fixed config (main yaml, batch 262 MB on 12 GB)
        a1, a10 = R["sf1_main"], R["sf10_main"]
        fit = {k: lin(a1[k], a10[k]) for k in ("warm_ms", "gpu_busy_ms", "kernels", "idle_ms")}
        peak10 = a10["pool_peak_end_MB"]
        sfmax12 = int(10 * 0.85 * 12227 * 1.048576 / peak10)  # 0.85 of 12,227 MiB, in MB
        ext = {"fit_y_eq_a_plus_b_SF": {k: {"a": v[0], "b": v[1]} for k, v in fit.items()},
               "sf_max_12GB_if_peak_scales_linearly": sfmax12}
        for sf in sorted({sfmax12, 30, 100}):
            w = fit["warm_ms"][0] + fit["warm_ms"][1] * sf; bz = fit["gpu_busy_ms"][0] + fit["gpu_busy_ms"][1] * sf
            ext[f"SF{sf}"] = {"warm_ms": w, "gpu_busy_ms": bz, "busy_pct_wall": 100 * bz / w,
                              "kernels": fit["kernels"][0] + fit["kernels"][1] * sf}
        w, bz = ext["SF100"]["warm_ms"], ext["SF100"]["gpu_busy_ms"]
        ext["SF100_hbm_5x_kernels_modeled"] = {"busy_ms": bz / 5, "busy_pct_wall": 100 * (bz / 5) / (w - bz + bz / 5),
            "assumption": "80 GB HBM-class GPU with ~5x the 672 GB/s; all GPU-busy time shrinks 5x (upper bound on GPU speed-up), "
                          "host/idle time (wall - busy) unchanged; same per-SF launch growth"}
        ext["assumptions"] = ("two points only; batch size fixed at 262 MB (on an 80 GB GPU Sirius would derive ~2 GB "
                              "batches, i.e. ~8x fewer per-batch launches); kernel time linear in data; host overhead "
                              "linear in launches; pool high-water linear in SF (it is partly bounded by batch size, so "
                              "SF_max is conservative)")
        s["extrapolation_modeled"] = ext
    if "sf10_main" in R and "sf10_b77" in R:  # same data, ~3.4x smaller batches: marginal cost of the extra launches
        a, b = R["sf10_main"], R["sf10_b77"]
        dk = b["kernels"] - a["kernels"]
        s["sf10_batch_size_effect"] = {"extra_launches_b77": dk, "wall_delta_ms": b["warm_ms"] - a["warm_ms"],
                                       "busy_delta_ms": round(b["gpu_busy_ms"] - a["gpu_busy_ms"], 3),
                                       "wall_us_per_extra_launch": round(1e3 * (b["warm_ms"] - a["warm_ms"]) / dk, 2) if dk else None,
                                       "note": "inferred; wall from 1 ms .timer medians"}
    summ["queries"][q] = s
with open(f"{E}/scaling_table.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
json.dump(summ, open(f"{E}/scaling_summary.json", "w"), indent=1)

print(f"{'Q':>3} {'cfg':9s} {'plan':>4} {'xflr':>5} {'SF':>2} {'B_MB':>5} {'wall':>6} {'cpu':>6} {'busy':>7} {'busy%':>6} {'idle':>6} {'kern':>5} {'ops':>5} {'<5us':>5} {'g<48':>5} {'pinMB':>7} {'peakMB':>7} {'ns/row':>7}")
for r in rows:
    print(f"{r['query']:3d} {r['config']:9s} {r['planning_ms_log']:4.1f} {r['busy_x_floor']:5.1f} {r['sf']:2d} {r['batch_MB']:5.0f} {r['warm_ms']:6.1f} {r['cpu_ms']:6.1f} {r['gpu_busy_ms']:7.3f} {r['busy_pct_wall']:6.1f} "
          f"{r['idle_ms']:6.2f} {r['kernels']:5d} {r['gpu_ops']:5d} {r['launches_lt5us']:5d} {r['launches_grid_lt48']:5d} {r['pinned_MB']:7.0f} {r['pool_peak_end_MB']:7.0f} {r['wall_ns_per_row'] or 0:7.3f}")
print()
for q, s in summ["queries"].items():
    for name, c in s["comparisons"].items():
        print(f"Q{q} {name:32s} launches {c['launches_sf1']}->{c['launches_sf10']} (x{c['launch_ratio']:.2f}), wall x{c['wall_ratio']:.2f}, "
              f"busy x{c['busy_ratio']:.2f}, kern x{c['kernel_time_ratio']:.2f}, idle x{(c['idle_ratio'] or 0):.2f}, busy% {c['busy_pct_wall_sf1']:.1f}->{c['busy_pct_wall_sf10']:.1f}, "
              f"added launches {c['added_launches_by_class']}")
    if "sf10_batch_size_effect" in s:
        print("   SF10 b77 vs main:", s["sf10_batch_size_effect"])
    if "extrapolation_modeled" in s:
        x = s["extrapolation_modeled"]; k = f"SF{x['sf_max_12GB_if_peak_scales_linearly']}"
        print(f"   modeled: SFmax(12GB)={x['sf_max_12GB_if_peak_scales_linearly']}: wall {x[k]['warm_ms']:.0f} ms, busy {x[k]['gpu_busy_ms']:.0f} ms ({x[k]['busy_pct_wall']:.0f}%), kernels {x[k]['kernels']:.0f}; "
              f"SF100: busy% {x['SF100']['busy_pct_wall']:.0f}, kernels {x['SF100']['kernels']:.0f}, wall {x['SF100']['warm_ms']:.0f} ms; SF100 w/ 5x faster GPU: busy% {x['SF100_hbm5x_kernels_modeled' if False else 'SF100_hbm_5x_kernels_modeled']['busy_pct_wall']:.0f}")
