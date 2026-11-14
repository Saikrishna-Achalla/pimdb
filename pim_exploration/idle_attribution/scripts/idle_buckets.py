"""Part A: wall-clock decomposition of warm Sirius iterations from the existing nsys CUDA traces (Q2..Q22, SF1).

Usage: <venv>/bin/python -I idle_buckets.py [results_root] [out_dir]
Inputs (read-only): tpch_q1_analysis/analysis/results/q<N>/{traces/q<N>_nsys.sqlite, traces/sirius_log_nsys,
  traces/nsys_run.txt, pcie.json, query_plan.txt}, results/summary/summary_data.json
Outputs: <out_dir>/idle_buckets.json (per query: per measured iteration + medians), <out_dir>/gap_stats.csv,
  <out_dir>/launch_after_readback.csv, <out_dir>/idle_buckets_table.txt

Definitions (all timestamps are nsys ns except where marked "log" = Sirius log, 1 ms resolution):
  iteration i (measured = after the 3 warm-up iterations): log QueryBegin(SQL) qb_i; the nsys window is
     [qb_i - 1 ms, qb_{i+1} - 1 ms) (iterations are separated by 0.3 s `.shell sleep`).
  engine span = [first CUDA API call of the duckdb process in the window, max(last API end, last GPU op end)].
  pre_engine  = engine start - qb (log stamp on one side -> +-1 ms): DuckDB bind/plan + Sirius plan + engine setup
                before the first CUDA call. log_planning = tb - qb (both log) is reported for reference.
  post_engine = qe(log) - engine end (may be negative within log resolution); timer_ms = DuckDB `.timer` real.
  Inside the engine span every ns goes to exactly one bucket:
     gpu_active: >= 1 kernel/memcpy/memset executing (CUPTI activity)
     api:<cat>  : GPU idle and >= 1 thread inside a CUDA API call; split fractionally among the calls active at
                  that instant (k overlapping calls -> 1/k each)
     host_only  : GPU idle and no thread inside any CUDA API call
"""
import bisect, collections, csv, glob, json, os, re, sqlite3, statistics, sys
import numpy as np

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1")
import siriuslog  # read-only import of the pipeline's log parser

CATS = ["launch", "alloc", "memcpy", "sync", "event", "other"]


def cat_of(n):
    n = re.sub(r"_v\d+$", "", n)
    if n in ("cudaLaunchKernel", "cuLaunchKernel", "cudaLaunchKernelExC", "cuLaunchKernelEx", "cudaGraphLaunch",
             "cuKernelGetName", "cuLibraryGetKernel", "cuGetProcAddress", "cudaGetDriverEntryPointByVersion",
             "cudaOccupancyAvailableDynamicSMemPerBlock", "cuLibraryLoadData"):
        return "launch"
    if n in ("cudaMallocFromPoolAsync", "cudaFreeAsync", "cudaMallocAsync", "cudaMalloc", "cudaFree", "cudaHostAlloc",
             "cudaFreeHost", "cudaHostRegister", "cudaHostUnregister") or n.startswith("cudaMemPool") or n.startswith("cuMemAlloc"):
        return "alloc"
    if n.startswith("cudaMemcpy") or n.startswith("cudaMemset") or n.startswith("cuMemcpy") or n.startswith("cuMemset"):
        return "memcpy"
    if n in ("cudaStreamSynchronize", "cuStreamSynchronize", "cudaEventSynchronize", "cuEventSynchronize",
             "cudaDeviceSynchronize", "cuCtxSynchronize"):
        return "sync"
    if n.startswith("cudaEvent") or n.startswith("cuEvent") or n == "cudaStreamWaitEvent" or n == "cuStreamWaitEvent":
        return "event"
    return "other"


def is_launch(n):
    return re.sub(r"_v\d+$", "", n) in ("cudaLaunchKernel", "cuLaunchKernel", "cudaLaunchKernelExC", "cuLaunchKernelEx")


def union_list(iv):
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1][1] = e
        else:
            out.append([s, e])
    return out


def size_class(b):
    if b <= 16: return "le16B"
    if b <= 1024: return "le1KiB"
    if b <= 65536: return "le64KiB"
    if b <= 1 << 20: return "le1MiB"
    return "gt1MiB"


def pct(a, p):
    return float(np.percentile(a, p)) if len(a) else 0.0


def plan_ops(R):
    txt = open(f"{R}/query_plan.txt").read()
    ids = set(re.findall(r"[A-Z_]+ \(id=(\d+)\)", txt))
    pipes = set(re.findall(r"Pipeline #(\d+):", txt))
    return len(ids), len(pipes)


def analyse(q):
    R = f"{ROOT}/q{q}"
    c = sqlite3.connect(f"{R}/traces/q{q}_nsys.sqlite")
    names = dict(c.execute("select id, value from StringIds"))
    t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
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
    timer = [float(x) * 1e3 for x in re.findall(r"Run Time \(s\): real ([0-9.]+)", open(f"{R}/traces/nsys_run.txt").read())]
    gpid = c.execute("select globalPid from CUPTI_ACTIVITY_KIND_KERNEL limit 1").fetchone()[0]
    tname = {g: names.get(n, "?") for n, _, g in c.execute("select nameId, priority, globalTid from ThreadNames")}
    api = [(s, e, g, names[n], cid) for s, e, g, n, cid in c.execute(
        "select start, end, globalTid, nameId, correlationId from CUPTI_ACTIVITY_KIND_RUNTIME order by start")]
    api = [a for a in api if (a[2] >> 24) == (gpid >> 24)]
    api_starts = [a[0] for a in api]
    kern = c.execute("select start, end, correlationId, streamId from CUPTI_ACTIVITY_KIND_KERNEL order by start").fetchall()
    mcp = c.execute("select start, end, correlationId, streamId, bytes, copyKind from CUPTI_ACTIVITY_KIND_MEMCPY order by start").fetchall()
    mst = c.execute("select start, end, correlationId, streamId from CUPTI_ACTIVITY_KIND_MEMSET order by start").fetchall()
    syn = {cid: (st, s, e, ty) for s, e, cid, st, ty in c.execute(
        "select start, end, correlationId, streamId, syncType from CUPTI_ACTIVITY_KIND_SYNCHRONIZATION")}
    gpu_all = sorted([(s, e, st, "k") for s, e, _, st in kern] + [(s, e, st, "m") for s, e, _, st, _, _ in mcp] +
                     [(s, e, st, "s") for s, e, _, st in mst])
    gstarts = [g[0] for g in gpu_all]
    by_cid_m = collections.defaultdict(list)
    for m in mcp:
        by_cid_m[m[2]].append(m)
    kern_by_cid = {k[2]: k for k in kern}
    nops, npipes = plan_ops(R)
    iters = []
    for i in range(nwarm, len(qb)):
        lo = qb[i] - 1e6
        hi = (qb[i + 1] - 1e6) if i + 1 < len(qb) else lo + 0.29e9
        A = api[bisect.bisect_left(api_starts, lo):bisect.bisect_left(api_starts, hi)]
        G = gpu_all[bisect.bisect_left(gstarts, lo):bisect.bisect_left(gstarts, hi)]
        es = A[0][0]
        ee = max(max(a[1] for a in A), max(g[1] for g in G))
        span = ee - es
        busy = union_list([(s, e) for s, e, _, _ in G])
        busy_ns = sum(e - s for s, e in busy)
        # ---- sweep: elementary segments
        pts = {es, ee}
        for s, e in busy: pts.add(s); pts.add(e)
        for a in A: pts.add(a[0]); pts.add(a[1])
        pts = sorted(p for p in pts if es <= p <= ee)
        # active GPU indicator via busy list; active API calls via event sweep
        ev = collections.defaultdict(list)
        for k, a in enumerate(A):
            ev[a[0]].append((1, k)); ev[a[1]].append((-1, k))
        active = set(); bi = 0
        buckets = collections.Counter()
        thr = collections.defaultdict(collections.Counter)  # thread -> {(state, gpu): ns}
        threads = sorted({a[2] for a in A})
        for j in range(len(pts) - 1):
            p, pn = pts[j], pts[j + 1]
            for d, k in ev.get(p, []):
                if d < 0: active.discard(k)
            for d, k in ev.get(p, []):
                if d > 0 and A[k][1] > p: active.add(k)
            dt = pn - p
            if dt <= 0: continue
            while bi < len(busy) and busy[bi][1] <= p: bi += 1
            g = bi < len(busy) and busy[bi][0] <= p
            if g:
                buckets["gpu_active"] += dt
            elif active:
                for k in active:
                    buckets["api:" + cat_of(A[k][3])] += dt / len(active)
            else:
                buckets["host_only"] += dt
            inapi = {}
            for k in active:
                inapi[A[k][2]] = cat_of(A[k][3])
            for t in threads:
                thr[t][(inapi.get(t, "not_in_api"), "gpu_busy" if g else "gpu_idle")] += dt
        # ---- counts
        n_k = sum(1 for g in G if g[3] == "k")
        n_launch_api = sum(1 for a in A if is_launch(a[3]))
        api_by = collections.defaultdict(lambda: [0, 0])
        for a in A:
            x = api_by[re.sub(r"_v\d+$", "", a[3])]; x[0] += 1; x[1] += a[1] - a[0]
        mlo, mhi = bisect.bisect_left([m[0] for m in mcp], lo), bisect.bisect_left([m[0] for m in mcp], hi)
        M = mcp[mlo:mhi]
        mc = collections.Counter(); mb = collections.Counter()
        kindn = {1: "H2D", 2: "D2H", 8: "D2D", 10: "P2P", 9: "H2H"}
        for m in M:
            d = kindn.get(m[5], str(m[5])); mc[f"{d}:{size_class(m[4])}"] += 1; mb[d] += m[4]
        n_memset = sum(1 for g in G if g[3] == "s")
        n_sync = sum(1 for a in A if cat_of(a[3]) == "sync")
        # ---- launch-after-readback, per thread
        lar = []
        pending = {}
        for a in A:
            s, e, t, n, cid = a
            ct = cat_of(n)
            if ct == "memcpy" and any(m[5] == 2 for m in by_cid_m.get(cid, [])):
                gend = max(m[1] for m in by_cid_m[cid] if m[5] == 2)
                if e >= gend:  # the call returned after the copy finished: the host waited for it (blocking readback)
                    pending[t] = ("d2h", gend, e)
            elif ct == "sync":
                gend = e
                sy = syn.get(cid)
                if sy is not None:
                    st = sy[0]
                    cands = [g[1] for g in G if g[1] <= e and (g[2] == st or st in (None, 4294967295))]
                    gend = max(cands) if cands else sy[2]
                pending[t] = ("sync", min(gend, e), e)
            elif is_launch(n):
                if t in pending:
                    kind, gend, aend = pending.pop(t)
                    k = kern_by_cid.get(cid)
                    lar.append({"kind": kind, "host_gap_ns": s - gend, "after_return_ns": s - aend,
                                "bubble_ns": (k[0] - gend) if k else None, "thread": tname.get(t, str(t)),
                                "gend": gend, "lstart": s})
        hg = [x["host_gap_ns"] for x in lar]
        # wall time (GPU idle) covered by at least one thread's readback->next-launch host gap
        lar_iv = union_list([(x["gend"], x["lstart"]) for x in lar if x["lstart"] > x["gend"]])
        lar_wall = sum(e - s for s, e in lar_iv)
        lar_wall_idle = lar_wall - sum(max(0, min(e, be) - max(s, bs)) for s, e in lar_iv for bs, be in busy
                                       if be > s and bs < e)
        # ---- gaps between consecutive GPU activities (union)
        gaps = [busy[j + 1][0] - busy[j][1] for j in range(len(busy) - 1)]
        lead = busy[0][0] - es if busy else span
        tail = ee - busy[-1][1] if busy else 0
        ksum = sum(g[1] - g[0] for g in G if g[3] == "k")
        osum = sum(g[1] - g[0] for g in G)
        per_thread = {}
        for t in threads:
            d = thr[t]
            per_thread[tname.get(t, str(t)) + f"#{t & 0xffffff}"] = {
                "api_ms": {ct: sum(v for (s_, _), v in d.items() if s_ == ct) / 1e6 for ct in CATS},
                "not_in_api_ms": sum(v for (s_, _), v in d.items() if s_ == "not_in_api") / 1e6,
                "not_in_api_gpu_idle_ms": d[("not_in_api", "gpu_idle")] / 1e6,
                "in_api_gpu_idle_ms": sum(v for (s_, g_), v in d.items() if s_ != "not_in_api" and g_ == "gpu_idle") / 1e6,
                "api_calls": sum(1 for a in A if a[2] == t), "launches": sum(1 for a in A if a[2] == t and is_launch(a[3]))}
        it = {"iter": i + 1, "timer_ms": timer[i] if i < len(timer) else None,
              "log_query_ms": (qe[i] - qb[i]) / 1e6, "log_planning_ms": (tb[i] - qb[i]) / 1e6,
              "pre_engine_ms": (es - qb[i]) / 1e6, "engine_ms": span / 1e6, "post_engine_ms": (qe[i] - ee) / 1e6,
              "engine_minus_log_tb_ms": (es - tb[i]) / 1e6,
              "buckets_ms": {k: buckets.get(k, 0) / 1e6 for k in ["gpu_active"] + ["api:" + x for x in CATS] + ["host_only"]},
              "gpu_busy_ms": busy_ns / 1e6, "kernel_sum_ms": ksum / 1e6, "gpu_op_sum_ms": osum / 1e6,
              "lead_in_ms": lead / 1e6, "tail_ms": tail / 1e6,
              "kernels": n_k, "launch_api": n_launch_api, "gpu_ops": len(G), "memset": n_memset,
              "memcpy_by_dir_size": dict(mc), "memcpy_bytes": dict(mb), "blocking_sync_calls": n_sync,
              "api_calls": len(A), "api": {k: {"calls": v[0], "ms": v[1] / 1e6} for k, v in api_by.items()},
              "launch_after_readback": {"count": len(lar), "d2h": sum(x["kind"] == "d2h" for x in lar),
                                        "sync": sum(x["kind"] == "sync" for x in lar),
                                        "host_gap_us_median": pct(hg, 50) / 1e3, "host_gap_us_p90": pct(hg, 90) / 1e3,
                                        "host_gap_ms_sum": sum(hg) / 1e6,
                                        "wall_ms_union": lar_wall / 1e6, "wall_ms_union_gpu_idle": lar_wall_idle / 1e6,
                                        "bubble_ms_sum": sum(x["bubble_ns"] for x in lar if x["bubble_ns"] is not None) / 1e6},
              "gaps_ns": gaps, "lar_host_gap_ns": hg, "per_thread": per_thread}
        iters.append(it)
    return {"q": q, "plan_ops": nops, "pipelines": npipes, "iterations": iters}


def med(its, f):
    return statistics.median(f(x) for x in its)


def main():
    S = {r["q"]: r for r in json.load(open(f"{ROOT}/summary/summary_data.json"))}
    allq = {}
    for q in range(2, 23):
        d = analyse(q)
        its = d["iterations"]
        d["pinned_mb"] = S[q]["pinned_mb"]
        m = {k: med(its, lambda x, k=k: x[k]) for k in ["timer_ms", "log_query_ms", "log_planning_ms", "pre_engine_ms",
             "engine_ms", "post_engine_ms", "engine_minus_log_tb_ms", "gpu_busy_ms", "kernel_sum_ms", "gpu_op_sum_ms",
             "lead_in_ms", "tail_ms", "kernels", "launch_api", "gpu_ops", "memset", "blocking_sync_calls", "api_calls"]}
        m["buckets_ms"] = {k: med(its, lambda x, k=k: x["buckets_ms"][k]) for k in its[0]["buckets_ms"]}
        m["lar"] = {k: med(its, lambda x, k=k: x["launch_after_readback"][k]) for k in its[0]["launch_after_readback"]}
        keys = set().union(*[x["memcpy_by_dir_size"] for x in its])
        m["memcpy_by_dir_size"] = {k: med(its, lambda x, k=k: x["memcpy_by_dir_size"].get(k, 0)) for k in sorted(keys)}
        keys = set().union(*[x["memcpy_bytes"] for x in its])
        m["memcpy_bytes"] = {k: med(its, lambda x, k=k: x["memcpy_bytes"].get(k, 0)) for k in sorted(keys)}
        d["median"] = m
        allq[q] = d
        print(f"q{q}: engine {m['engine_ms']:.2f} ms busy {m['gpu_busy_ms']:.2f} kernels {m['kernels']}", flush=True)
    # gap stats
    with open(f"{OUT}/gap_stats.csv", "w", newline="") as f:
        w = csv.writer(f)
        bins = [0, 2e3, 5e3, 10e3, 20e3, 50e3, 100e3, 1e6, 1e12]
        bl = ["lt2us", "2_5us", "5_10us", "10_20us", "20_50us", "50_100us", "100us_1ms", "gt1ms"]
        w.writerow(["q", "iters", "engine_ms", "kernel_sum_ms", "gpu_busy_ms", "gaps_per_iter", "gap_median_us", "gap_p90_us",
                    "gap_p99_us", "gap_max_us", "gap_sum_ms", "lead_in_ms", "tail_ms"] + [f"n_{b}" for b in bl] +
                   [f"ms_{b}" for b in bl] + ["remain_backtoback_kernels_pct", "remain_backtoback_allops_pct",
                    "honest_remaining_ms", "honest_remaining_pct", "plan_ops"])
        for q, d in allq.items():
            its = d["iterations"]; n = len(its); m = d["median"]
            g = np.array([x for it in its for x in it["gaps_ns"]])
            cnt = np.histogram(g, bins)[0] / n
            sm = np.histogram(g, bins, weights=g)[0] / n / 1e6
            gmed = float(np.median(g)) if len(g) else 0
            # honest bound (modeled): keep kernel+copy time, lead-in, tail, and one median gap per plan operator
            honest = m["gpu_op_sum_ms"] + m["lead_in_ms"] + m["tail_ms"] + d["plan_ops"] * gmed / 1e6
            d["median"]["honest_remaining_ms"] = honest
            d["median"]["gap_median_us"] = gmed / 1e3
            w.writerow([q, n, round(m["engine_ms"], 4), round(m["kernel_sum_ms"], 4), round(m["gpu_busy_ms"], 4), len(g) / n,
                        round(gmed / 1e3, 2), round(pct(g, 90) / 1e3, 2), round(pct(g, 99) / 1e3, 2),
                        round(float(g.max()) / 1e3 if len(g) else 0, 1), round(g.sum() / n / 1e6, 4), round(m["lead_in_ms"], 4),
                        round(m["tail_ms"], 4)] + [round(x, 1) for x in cnt] + [round(x, 4) for x in sm] +
                       [round(100 * m["kernel_sum_ms"] / m["engine_ms"], 2), round(100 * m["gpu_op_sum_ms"] / m["engine_ms"], 2),
                        round(honest, 4), round(100 * honest / m["engine_ms"], 2), d["plan_ops"]])
    with open(f"{OUT}/launch_after_readback.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["q", "iters", "lar_per_iter", "d2h_per_iter", "sync_per_iter", "host_gap_median_us", "host_gap_p90_us",
                    "host_gap_sum_ms_per_iter", "bubble_sum_ms_per_iter", "wall_union_gpu_idle_ms_per_iter",
                    "n_gap_le50us", "sum_gap_le50us_ms", "n_gap_gt50us", "sum_gap_gt50us_ms", "engine_ms", "kernels_per_iter"])
        for q, d in allq.items():
            its = d["iterations"]; n = len(its)
            hg = np.array([x for it in its for x in it["lar_host_gap_ns"]])
            w.writerow([q, n, sum(it["launch_after_readback"]["count"] for it in its) / n,
                        sum(it["launch_after_readback"]["d2h"] for it in its) / n,
                        sum(it["launch_after_readback"]["sync"] for it in its) / n,
                        round(pct(hg, 50) / 1e3, 2), round(pct(hg, 90) / 1e3, 2), round(hg.sum() / n / 1e6, 4),
                        round(sum(it["launch_after_readback"]["bubble_ms_sum"] for it in its) / n, 4),
                        round(sum(it["launch_after_readback"]["wall_ms_union_gpu_idle"] for it in its) / n, 4),
                        (hg <= 50e3).sum() / n, round(hg[hg <= 50e3].sum() / n / 1e6, 4),
                        (hg > 50e3).sum() / n, round(hg[hg > 50e3].sum() / n / 1e6, 4),
                        round(d["median"]["engine_ms"], 4), sum(it["kernels"] for it in its) / n])
    for d in allq.values():  # keep the json readable: drop raw gap lists
        for it in d["iterations"]:
            it.pop("gaps_ns"); it.pop("lar_host_gap_ns")
    json.dump(allq, open(f"{OUT}/idle_buckets.json", "w"), indent=1)


if __name__ == "__main__":
    main()
