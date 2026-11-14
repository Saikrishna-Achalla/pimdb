"""Part B summary: residency log checks for every Part-B run, sampled vs unsampled wall times, and the grouping of the
GPU-idle engine time into (i)..(vi).

Usage: <venv>/bin/python -I partB_summary.py      (after run_all_partB.sh and cpu_attrib.py for 6 3 9 18)
Writes partB_summary.json and partB_summary.txt.
"""
import glob, json, os, re, statistics, subprocess, sys, sqlite3
H = os.path.dirname(os.path.abspath(__file__)); D = os.path.dirname(H)
sys.path.insert(0, H)
import siriuslog

QS = [6, 3, 9, 18]
NWARM = 3
GROUP = [  # (group, predicate on category name)
    ("i_cuda_launch", lambda c: c.startswith("cuda:launch")),
    ("i_cuda_sync_copy_event_other", lambda c: c.startswith(("cuda:sync", "cuda:memcpy", "cuda:event", "cuda:other",
                                                             "cuda_driver_outside_api", "cudart_outside_traced_api"))),
    ("ii_alloc", lambda c: c.startswith(("cuda:alloc", "rmm", "sirius:memory_batches"))),
    ("iii_cudf_host", lambda c: c.startswith("cudf")),
    ("iii_sirius_operator_host", lambda c: c.startswith(("sirius:operators", "sirius:other", "sirius:logging"))),
    ("iv_sirius_sched_handoff", lambda c: c.startswith(("sirius:scheduler", "wait:", "all_off_cpu"))),
    ("v_duckdb_plan_result", lambda c: c.startswith("duckdb")),
    ("profiler_artifact", lambda c: "profiler" in c),
    ("vi_unattributed", lambda c: True),
]


def group_of(c):
    if "profiler" in c: return "profiler_artifact"
    for g, f in GROUP:
        if f(c): return g


def timers(run):
    t = [float(x) * 1e3 for x in re.findall(r"Run Time \(s\): real ([0-9.]+)", open(f"{run}/run.txt").read())]
    return t[NWARM:]


out = {"runs": {}, "queries": {}}
lines = []
P = lambda *a: lines.append(" ".join(str(x) for x in a))
for q in QS:
    tables = subprocess.run(["python3", "-I", f"{H}/gen_sql.py", "tables", str(q)], capture_output=True, text=True,
                            check=True).stdout.split()
    rq = {}
    for mode in ["plain", "cudatrace", "cpu"]:
        run = f"{D}/runs/q{q}_{mode}"
        if not os.path.isdir(run): continue
        L, procs = siriuslog.read_run(f"{run}/sirius_log")
        checks, _ = siriuslog.check_log(f"q{q}_{mode}", L, tables, 153)
        t = timers(run)
        # Sirius-log query window (QueryBegin SQL -> QueryEnd), 1 ms stamps, measured iterations
        _, _, iters = siriuslog.parse(L)
        rq[mode] = {"checks_ok": all(v["ok"] for v in checks.values()),
                    "failed": {k: v["detail"] for k, v in checks.items() if not v["ok"]},
                    "timer_ms_median": statistics.median(t), "timer_ms_mean": statistics.mean(t),
                    "timer_ms_min": min(t), "timer_ms_max": max(t), "n": len(t)}
        if mode != "plain":  # H2D bytes per measured iteration from the CUDA trace (table data must not cross PCIe)
            c = sqlite3.connect(f"{run}/q{q}.sqlite")
            h2d = c.execute("select count(*), coalesce(sum(bytes),0), coalesce(max(bytes),0) from CUPTI_ACTIVITY_KIND_MEMCPY where copyKind=1").fetchone()
            nk = c.execute("select count(*) from CUPTI_ACTIVITY_KIND_KERNEL").fetchone()[0]
            rq[mode]["trace_h2d_copies_bytes_max"] = h2d; rq[mode]["trace_kernels"] = nk
        out["runs"][f"q{q}_{mode}"] = rq[mode]
    a = json.load(open(f"{D}/cpu_attrib_q{q}.json"))
    w = dict(a["gpu_idle_wall_attrib_ms_per_iter"])
    w["all_off_cpu"] = a["gpu_idle_all_app_threads_off_cpu_ms_per_iter"]
    grp = {}
    for c_, v in w.items():
        g = group_of(c_); grp[g] = grp.get(g, 0) + v
    tot = sum(grp.values())
    out["queries"][q] = {"timer": {m: rq[m]["timer_ms_median"] for m in rq}, "gpu_idle_ms": a["gpu_idle_engine_ms_per_iter"],
                         "engine_ms": a["engine_ms_median"], "planning_ms": a["planning_ms_median"],
                         "gpu_busy_ms": a["gpu_busy_ms_median"], "groups_ms": grp, "groups_sum_ms": tot,
                         "all_off_cpu_ms": a["gpu_idle_all_app_threads_off_cpu_ms_per_iter"],
                         "all_off_cpu_blocked_in": a["all_off_cpu_pipeline_threads_blocked_in_ms_per_iter"]}
json.dump(out, open(f"{D}/partB_summary.json", "w"), indent=1)

P("Residency / log checks (siriuslog.check_log, same checks as the SF1 pipeline) and CUDA-trace H2D per run")
for k, v in out["runs"].items():
    P(f"  {k:14s} checks {'PASS' if v['checks_ok'] else 'FAIL ' + str(v['failed'])}  n={v['n']}  "
      f"timer median {v['timer_ms_median']:.1f} ms (mean {v['timer_ms_mean']:.2f}, min {v['timer_ms_min']:.0f}, max {v['timer_ms_max']:.0f})"
      + (f"  H2D copies/bytes/max over whole trace {v['trace_h2d_copies_bytes_max']} kernels {v['trace_kernels']}" if "trace_kernels" in v else ""))
P("\nSampling inflation (.timer mean, 1 ms resolution, 150 measured iterations each)")
for q in QS:
    r = out["runs"]
    p_, c_, s_ = r[f"q{q}_plain"]["timer_ms_mean"], r[f"q{q}_cudatrace"]["timer_ms_mean"], r[f"q{q}_cpu"]["timer_ms_mean"]
    P(f"  q{q}: plain {p_:.2f} ms, CUDA trace {c_:.2f} ms (x{c_/p_:.2f}), CUDA trace + osrt + CPU sampling {s_:.2f} ms (x{s_/p_:.2f})")
P("\nGPU-idle engine time per iteration in the sampled run, grouped (ms; wall-weighted samples + exact all-threads-off-CPU time)")
G = [g for g, _ in GROUP]
P(f"{'q':>3} {'idle':>6} {'sum':>6} " + " ".join(f"{g[:14]:>14}" for g in G))
for q in QS:
    x = out["queries"][q]
    P(f"{q:>3} {x['gpu_idle_ms']:6.2f} {x['groups_sum_ms']:6.2f} " + " ".join(f"{x['groups_ms'].get(g,0):14.3f}" for g in G))
P("shares of the grouped GPU-idle time (all 4 queries summed), with and without the profiler artifact:")
tot = {g: sum(out["queries"][q]["groups_ms"].get(g, 0) for q in QS) for g in G}
T = sum(tot.values()); T2 = T - tot["profiler_artifact"]
for g in G:
    P(f"  {g:30s} {tot[g]:7.3f} ms  {100*tot[g]/T:5.1f}%  " + (f"{100*tot[g]/T2:5.1f}% (excl. profiler)" if g != "profiler_artifact" else ""))
open(f"{D}/partB_summary.txt", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
