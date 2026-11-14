"""Machine-checkable validation of results/q<N>/ produced by profile_query.sh.

Usage: python3 -I validate_query.py <N> [--pipeline]
  --pipeline : report-writing checks (physical_floor.md, REPORT_*.md) print PENDING instead of FAIL.
Prints one `PASS|FAIL|PENDING <check> -- detail` line per check, then a summary.
Exit status: 0 if no FAIL, 1 otherwise.
"""
import collections, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from siriuslog import sql_pin_problems

ROOT = "/home/sai/cs254_project/tpch_q1_analysis"
N = int(sys.argv[1]); PIPELINE = "--pipeline" in sys.argv
R = os.environ.get("RESULTS_DIR", f"{ROOT}/analysis/results/q{N}")
results = []


def check(name, cond, detail="", pending_ok=False):
    st = "PASS" if cond else ("PENDING" if (pending_ok and PIPELINE) else "FAIL")
    results.append(st); print(f"{st:7s} {name} -- {detail}")


def load(p):
    try:
        return json.load(open(os.path.join(R, p)))
    except Exception:
        return None


def nonempty(p):
    return os.path.isfile(os.path.join(R, p)) and os.path.getsize(os.path.join(R, p)) > 0


def mtime(p):
    f = glob.glob(os.path.join(R, p))
    return max(os.path.getmtime(x) for x in f) if f else None


# --- stage a: SQL -------------------------------------------------------------
import subprocess
TABLES = subprocess.run(["python3", "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen_sql.py"), "tables", str(N)],
                        capture_output=True, text=True).stdout.split()
for s in ["timing", "cpu", "ncu_x3", "ncu_x4", "ncu_x5", "nsys"]:
    p = f"sql/q{N}_{s}.sql"
    probs = [] if s == "cpu" else (sql_pin_problems(open(os.path.join(R, p)).read(), TABLES) if nonempty(p) else ["missing"])
    check(f"sql:{s}" + ("" if s == "cpu" else ":all_pins_tier_gpu"), nonempty(p) and not probs, f"{p} {probs or ''}")
err = os.path.join(R, "ERROR.txt")
check("no_ERROR.txt", not os.path.exists(err), open(err).read()[:300] if os.path.exists(err) else "")

# --- stage b: timing ----------------------------------------------------------
T = load("timing.json")
check("timing.json", T is not None)
if T:
    w = T.get("timed_ms", [])
    check("timing:warmup>=3", T.get("warmup", 0) >= 3, f"warmup={T.get('warmup')}")
    check("timing:timed>=10", len(w) >= 10, f"timed={len(w)}")
    check("timing:positive", bool(w) and all(x > 0 for x in w) and T.get("median_ms", 0) > 0, f"median={T.get('median_ms')} ms")
    check("result:identical_across_iterations", T.get("results_identical") is True,
          f"{T.get('n_iterations_with_result')} iterations, {T.get('result_rows')} rows")
    check("result:nonempty", (T.get("result_rows") or 0) > 0, f"rows={T.get('result_rows')}")
    c = T.get("cpu") or {}
    check("cpu:timed>=10", len(c.get("timed_ms", [])) >= 10 and c.get("median_ms", 0) > 0, f"cpu median={c.get('median_ms')} ms")
    gv = T.get("gpu_vs_cpu") or {}
    check("result:gpu_equals_duckdb_cpu", T.get("gpu_equals_cpu") is True and gv.get("mode") not in (None, "MISMATCH"),
          f"mode={gv.get('mode')} max_rel_diff={gv.get('max_rel_diff')} tol={gv.get('rel_tol')} {gv.get('detail', '')}")
check("result.csv", nonempty("result.csv"))
check("timing_summary.txt", nonempty("timing_summary.txt"))
check("query_plan.txt", nonempty("query_plan.txt"))

# --- stage c: PCIe ------------------------------------------------------------
P = load("pcie.json")
txt = open(os.path.join(R, "pcie_verification.txt")).read() if nonempty("pcie_verification.txt") else ""
check("pcie:verification_file", bool(txt))
check("pcie:overall_pass", P is not None and P.get("overall") == "PASS" and "OVERALL: PASS" in txt,
      (P or {}).get("overall", "missing"))
if P:
    for k, v in P.get("checks", {}).items():
        check(f"pcie:{k}", v.get("ok") is True, v.get("detail", "")[:160])
    nb = load("nsys_iteration_breakdown.json")
    check("nsys_iteration_breakdown", bool(nb) and all(r["gpu_busy_ms"] > 0 and r["engine_ms"] > 0 and r["kernels"] > 0 for r in nb),
          f"{len(nb or [])} measured iterations")
    lim, dflt = P.get("limits"), P.get("default_limits")
    reptxt = " ".join(open(f).read() for f in glob.glob(f"{R}/REPORT_*.md"))
    # an overridden limit is accepted only if the report names that exact variable (a generic "no PCIE_* override" does not count)
    _over = [k for k in (lim or {}) if (dflt or {}).get(k) != lim[k]]
    _named = all(("PCIE_" + k.upper()) in reptxt for k in _over)
    check("pcie:byte_limits_are_defaults", lim is not None and dflt is not None and (not _over or _named),
          f"limits {lim} defaults {dflt}" + ("" if not _over else f" (overridden: {_over}; the report must justify each with its PCIE_<NAME> variable)"))
    check("pcie:nsys_trace_present", bool(glob.glob(f"{R}/traces/*.nsys-rep")) and bool(glob.glob(f"{R}/traces/*.sqlite")))

# --- stage d: ncu list ----------------------------------------------------------
PL = load("ncu_plan.json"); KL = load("warm_kernel_list.json")
check("ncu_plan.json", PL is not None)
check("warm_kernel_list.json", bool(KL))
if PL and KL:
    check("launch_counts_stable", PL.get("stable") is True,
          f"per-iteration={PL.get('per_iteration_counts')} skip={PL.get('skip')} count={PL.get('count')}")
    tot = sum(k["dur_ns"] for k in KL)
    check("warm_gpu_time>0", tot > 0, f"{tot/1e3:.1f} us")
    if PL.get("nsys_kernels_per_warm_iter") is not None:
        check("ncu_count==nsys_count", PL["nsys_kernels_per_warm_iter"] == PL["count"],
              f"nsys {PL['nsys_kernels_per_warm_iter']} vs ncu {PL['count']}")
check("warm_kernel_summary.txt", nonempty("warm_kernel_summary.txt"))
for kind in ("list", "detail"):
    J = load(f"ncu_log_checks_{kind}.json")
    bad = [k for r in (J or {}).get("runs", {}).values() for k, v in r["checks"].items() if not v["ok"]]
    check(f"ncu_{kind}_run_logs_residency", J is not None and J.get("ok") is True and not bad and bool(J.get("runs")),
          f"{len((J or {}).get('runs', {}))} ncu {kind} run(s): {', '.join((J or {}).get('runs', {}).keys())} {bad[:3] or ''}")
SM = load("ncu_sysmem_check.json")
check("ncu_no_sysmem_aperture_access", SM is not None and SM.get("ok") is True,
      "; ".join(f"{r['report']}: {r['n_kernels_with_sysmem_sectors']} kernels with SM sysmem sectors, missing {r['missing_metrics'] or 'none'}"
                for r in (SM or {}).get("reports", [])))
ST = open(os.path.join(R, "selftest_negative_control.txt")).read() if nonempty("selftest_negative_control.txt") else ""
check("selftest_negative_control", "SELFTEST: PASS" in ST, ST.splitlines()[0] if ST else "missing (run stage selftest)")

# --- stage e: ncu detailed -----------------------------------------------------
S = load("ncu_slice_check.json")
check("ncu_report_present", bool(glob.glob(f"{R}/profiles/*.ncu-rep")))
check("ncu_slice_multiset_match", S is not None and all(x.get("match") for x in S.get("reports", [])) and bool(S.get("reports")),
      "; ".join(f"{x['report']}: {x['n_report']}/{x['n_expected']} match={x['match']}" for x in (S or {}).get("reports", [])))

# --- stage f: extraction ---------------------------------------------------------
M = load("ncu_warm_metrics.json")
check("ncu_warm_metrics.json", M is not None and bool(M.get("kernels")))
if M and PL:
    K = M["kernels"]
    check("metrics_kernel_count==warm_count", len(K) == PL["count"], f"{len(K)} vs {PL['count']}")
    bad = []
    for k in K:
        for f in ("sm_pct", "dram_pct", "mem_pct", "occ_theo"):
            v = k.get(f)
            if v is not None and not (0 <= v <= 100.5):
                bad.append(f"{k['pos']}:{f}={v}")
        # achieved occupancy is a ratio of two sampled averages; ncu reads >100% on tiny ~1-wave kernels
        # (Q5 pos 31: 106.65% on a 7 us kernel), like the sector hit rates below -> same 150% sanity bound
        v = k.get("occ_ach")
        if v is not None and not (0 <= v <= 150):
            bad.append(f"{k['pos']}:occ_ach={v}")
        for f in ("l1_hit", "l2_hit"):  # raw value: ncu sector hit rates read up to 114% on tiny kernels (Q2)
            v = k.get(f + "_raw", k.get(f))
            if v is not None and not (0 <= v <= 150):
                bad.append(f"{k['pos']}:{f}={v}")
        if not (k.get("dur_ns") or 0) > 0:
            bad.append(f"{k['pos']}:dur={k.get('dur_ns')}")
    check("metrics_percentages_in_range_and_dur>0", not bad, ",".join(bad[:5]) +
          f" (hit rates >100% clamped to 100: {len(M.get('clamped_hit_rates', []))}; kernels with achieved occupancy >100%: "
          f"{sum((k.get('occ_ach') or 0) > 100.5 for k in K)})")
    full = [k for k in K if k.get("has_full")]
    nfull = sum(x["n_report"] for x in (S or {}).get("reports", []) if not x["report"].endswith("_light.ncu-rep"))
    cov = sum(k["dur_ns"] for k in full) / max(1, sum(k["dur_ns"] for k in K))
    check("full_set_kernels==full_report_kernels_and_cover>=90%", len(full) == nfull and cov >= 0.9,
          f"{len(full)} kernels carry --set full metrics, full/families report(s) hold {nfull}; {100*cov:.1f}% of warm time")
for f in ["phase_breakdown.txt", "operator_breakdown.txt", "top_kernel_details.txt"]:
    check(f, nonempty(f))
hs = glob.glob(f"{R}/sass/*_hotspots.txt")
check("sass_hotspots>=1", bool(hs) and all(os.path.getsize(h) > 200 for h in hs), ", ".join(os.path.basename(h) for h in hs))
for p in ["phase_breakdown", "kernel_sequence", "roofline", "stalls"]:
    check(f"plot:{p}", nonempty(f"plots/q{N}_{p}.png"))

# --- freshness: every stage output must be newer than its inputs (a rerun of an early stage invalidates later ones)
order = [("timing.json", ["sql/q%d_timing.sql" % N]), ("pcie.json", ["timing.json", "traces/q%d_nsys.sqlite" % N]),
         ("ncu_plan.json", ["traces/ncu_list_x5.csv", "pcie.json"]), ("ncu_slice_check.json", ["profiles/*.ncu-rep", "ncu_plan.json"]),
         ("ncu_sysmem_check.json", ["profiles/*.ncu-rep"]), ("ncu_warm_metrics.json", ["profiles/*.ncu-rep", "ncu_plan.json"]),
         ("phase_breakdown.json", ["ncu_warm_metrics.json"]), ("sass/*_hotspots.txt", ["ncu_warm_metrics.json"]),
         ("plots/*.png", ["ncu_warm_metrics.json"])]
stale = []
for out, ins in order:
    o = glob.glob(os.path.join(R, out))
    oldest = min((os.path.getmtime(x) for x in o), default=None)
    newest_in = max((mtime(i) or 0 for i in ins), default=0)
    if oldest is None or oldest + 1e-6 < newest_in:
        stale.append(out)
check("outputs_newer_than_inputs", not stale, f"stale or missing: {stale}" if stale else f"{len(order)} output groups fresh")

# --- report (hand-written) --------------------------------------------------------
check("physical_floor.md", nonempty("physical_floor.md"), pending_ok=True)
rep = glob.glob(f"{R}/REPORT_tpch_q{N}_sf1.md")
check("REPORT_tpch_q%d_sf1.md" % N, bool(rep), pending_ok=True)
if rep:  # the report must embed (not merely name) the four plots
    _t = open(rep[0]).read()
    _missing = [k for k in ("phase_breakdown", "kernel_sequence", "roofline", "stalls") if f"](plots/q{N}_{k}.png)" not in _t]
    check("report_embeds_plots", not _missing, "missing image embeds: " + ",".join(_missing) if _missing else "4 plots embedded")
if rep:
    t = open(rep[0]).read().lower()
    need = ["executive summary", "pcie", "physical floor", "root cause", "limitation", "measured", "inferred"]
    miss = [x for x in need if x not in t]
    check("report:sections", not miss, f"missing={miss}")

c = collections.Counter(results)
print(f"SUMMARY q{N}: {c['PASS']} PASS, {c['FAIL']} FAIL, {c['PENDING']} PENDING")
sys.exit(1 if c["FAIL"] else 0)
