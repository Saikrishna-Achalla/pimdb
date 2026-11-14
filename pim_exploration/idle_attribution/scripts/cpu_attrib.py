"""Part B: attribute host CPU samples / thread states inside warm-iteration engine spans (nsys CPU-sampled runs).

Usage: <venv>/bin/python -I cpu_attrib.py <N> [run_dir]     (run_dir default: runs/q<N>_cpu)
Inputs: <run_dir>/q<N>.sqlite (nsys: CUDA trace + osrt + process-tree IP sampling with LBR backtraces + context
        switches), <run_dir>/sirius_log, <run_dir>/run.txt
Outputs: cpu_samples_q<N>.csv (one row per category x window), cpu_attrib_q<N>.json (summary, top functions,
         thread-state accounting, GPU-idle wall attribution)

Windows (per measured iteration = after 3 warm-ups): planning = [qb(log), engine start); engine = CUDA span as in
idle_buckets.py; GPU-busy/idle inside the engine from CUPTI activity.
Sample classification (first rule that matches):
  1. thread inside a CUDA API call at the sample time (CUPTI runtime intervals) -> cuda:<launch|alloc|memcpy|sync|event|other>
     with sub-label 'profiler' when the leaf frame is in nsys injection / CUPTI.
  2. leaf in nsys injection / CUPTI (outside an API call) -> profiler
  3. waiting/polling symbols anywhere in the top 3 frames (cond wait, futex, sem, poll, yield, nanosleep, Sirius
     worker idle loops) -> wait:spin_or_poll
  4. by module of the leaf, with libc/libstdc++/ld.so leaves attributed to the first non-runtime caller module:
     libcudf -> cudf, librmm or rmm:: symbols -> rmm, libsirius -> sirius:<sub>, duckdb binary -> duckdb:<sub>,
     libcuda outside an API call -> cuda_driver_other, kernel/vdso -> kernel_or_vdso
Wall attribution of GPU-idle engine time: each sample of an application thread gets weight dt / k, where dt is the
calibrated thread-CPU time per sample and k the number of application threads on-CPU at that instant (sched events);
GPU-idle engine time with no application thread on-CPU is measured exactly from the sched events ("all_off_cpu") and
split by what the pipeline threads were blocked in (OSRT calls).
"""
import bisect, collections, csv, json, os, re, sqlite3, sys
import numpy as np

N = int(sys.argv[1])
D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = sys.argv[2] if len(sys.argv) > 2 else f"{D}/runs/q{N}_cpu"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog
from idle_buckets import cat_of, union_list

NWARM = 3
c = sqlite3.connect(f"{RUN}/q{N}.sqlite")
names = dict(c.execute("select id, value from StringIds"))
t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
ts = lambda l: siriuslog.ts_ms(l) * 1e6 - t0
L, _ = siriuslog.read_run(f"{RUN}/sirius_log")
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
timer = [float(x) * 1e3 for x in re.findall(r"Run Time \(s\): real ([0-9.]+)", open(f"{RUN}/run.txt").read())]

gpid = c.execute("select globalPid from CUPTI_ACTIVITY_KIND_KERNEL limit 1").fetchone()[0]
PID = gpid >> 24
tname = {g: names.get(n, "?") for n, _, g in c.execute("select nameId, priority, globalTid from ThreadNames")}
PROF_THREADS = ("[NSys]", "[NSys Comms]", "CUPTI worker thread", "*2CommsProcesso")
is_app = lambda g: (g >> 24) == PID and not tname.get(g, "").startswith(PROF_THREADS)

api = [(s, e, g, names[n]) for s, e, g, n in c.execute(
    "select start, end, globalTid, nameId from CUPTI_ACTIVITY_KIND_RUNTIME order by start") if (g >> 24) == PID]
api_starts = [a[0] for a in api]
gpu = sorted([(s, e) for s, e in c.execute("select start, end from CUPTI_ACTIVITY_KIND_KERNEL")] +
             [(s, e) for s, e in c.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMCPY")] +
             [(s, e) for s, e in c.execute("select start, end from CUPTI_ACTIVITY_KIND_MEMSET")])
gstarts = [g[0] for g in gpu]
kern_starts = sorted(s for (s,) in c.execute("select start from CUPTI_ACTIVITY_KIND_KERNEL"))

# per-thread CUDA API intervals (for rule 1)
api_by_t = collections.defaultdict(list)
for s, e, g, n in api:
    api_by_t[g].append((s, e, cat_of(n)))
api_by_t_starts = {g: [x[0] for x in v] for g, v in api_by_t.items()}


def in_api(g, t):
    v = api_by_t.get(g)
    if not v: return None
    i = bisect.bisect_right(api_by_t_starts[g], t) - 1
    # nested calls (runtime -> driver) can overlap: look back a few entries
    for j in range(i, max(-1, i - 4), -1):
        if v[j][0] <= t < v[j][1]:
            return v[j][2]
    return None


# sched intervals per application thread
sched = collections.defaultdict(list)
for s, cpu, isin, g, st, blk in c.execute("select start, cpu, isSchedIn, globalTid, threadState, threadBlock from SCHED_EVENTS order by start"):
    if is_app(g):
        sched[g].append((s, isin))
oncpu = {}
for g, ev in sched.items():
    iv, cur = [], None
    for s, isin in ev:
        if isin and cur is None: cur = s
        elif not isin and cur is not None: iv.append((cur, s)); cur = None
    if cur is not None: iv.append((cur, cur + 1))
    oncpu[g] = iv
# global "number of app threads on CPU" step function
edges = sorted([(s, 1) for iv in oncpu.values() for s, _ in iv] + [(e, -1) for iv in oncpu.values() for _, e in iv])
e_t = [x[0] for x in edges]; e_k = np.cumsum([x[1] for x in edges])
k_at = lambda t: int(e_k[bisect.bisect_right(e_t, t) - 1]) if bisect.bisect_right(e_t, t) > 0 else 0

# OSRT blocking calls per thread (for off-CPU explanation)
osrt = collections.defaultdict(list)
for s, e, g, n in c.execute("select start, end, globalTid, nameId from OSRT_API"):
    if is_app(g): osrt[g].append((s, e, names.get(n, "?")))
for g in osrt: osrt[g].sort()
osrt_starts = {g: [x[0] for x in v] for g, v in osrt.items()}


def osrt_at(g, t):
    v = osrt.get(g)
    if not v: return None
    i = bisect.bisect_right(osrt_starts[g], t) - 1
    for j in range(i, max(-1, i - 6), -1):
        if v[j][0] <= t < v[j][1]: return v[j][2]
    return None


# samples with call stacks
frames = collections.defaultdict(list)
for cid, sym, mod, depth in c.execute("select id, symbol, module, stackDepth from SAMPLING_CALLCHAINS order by id, stackDepth"):
    frames[cid].append((names.get(sym, str(sym)), names.get(mod, str(mod))))
samples = [(s, g, cid) for cid, s, g in c.execute("select id, start, globalTid from COMPOSITE_EVENTS")]

PROF_MOD = ("libToolsInjection", "libcupti", "libnvperf")
RUNTIME_MOD = ("libc.so", "libstdc++", "ld-linux", "libm.so", "libgcc_s", "libpthread")
WAIT_SYM = re.compile(r"pthread_cond_(timed)?wait|__futex|futex_wait|sem_(timed)?wait|__poll|epoll_wait|sched_yield|"
                      r"nanosleep|clock_nanosleep|this_thread::yield|worker_loop|processing_loop|management_eventloop|"
                      r"wait_for|condition_variable::wait|io_uring_wait|__internal_syscall_cancel|syscall_cancel")


def modname(m):
    return os.path.basename(m)


def sirius_sub(fr):
    """Sirius sub-area from the stack (leaf upward over frames, first match wins)."""
    for sym, mod in fr[:12]:
        s = sym
        if re.search(r"spdlog|fmt::|vformat|logger|log_msg|format_to|to_string", s): return "sirius:logging_format"
        if re.search(r"task_scheduler|scheduler|task_queue|task_creator|pipeline_executor|thread_pool|"
                     r"parallel::|management_eventloop|dispatch|notify|executor", s): return "sirius:scheduler_taskqueue"
        if re.search(r"cucascade|memory_space|reservation|downgrade|data_batch|repository|allocation_tracker|"
                     r"memory_reservation|pool", s):
            return "sirius:memory_batches"
        if re.search(r"op::|operator|physical|gpu_|hash_join|aggregate|filter|projection|scan|sort|join|partition|concat",
                     s, re.I) and "libsirius" in mod:
            return "sirius:operators"
    return "sirius:other"


def duckdb_sub(fr):
    """DuckDB sub-phase from the whole stack (leaf upward, first match wins)."""
    for sym, _ in fr:
        if re.search(r"ThriftFileTransport|thrift::|duckdb_parquet::|ParquetReader|MultiFileReader|ParquetMetaData|ParquetScan", sym):
            return "duckdb:parquet_metadata_bind"
        if re.search(r"MatchStack|Matcher|ListMatchProcess|PEG|Transformer|Parser::|ParseQuery|Tokenize|KeywordHelper", sym):
            return "duckdb:parse"
        if re.search(r"Binder|::Bind|Catalog", sym):
            return "duckdb:bind"
        if re.search(r"Optimizer|Planner|FilterPushdown|JoinOrder|Rewriter|LogicalOperator|ColumnBinding|Statistics", sym):
            return "duckdb:plan_optimize"
        if re.search(r"QueryResult|MaterializedQueryResult|ColumnDataCollection|Render|Box|ShellState|Print|CSV|Csv|Fetch", sym):
            return "duckdb:result_output"
        if re.search(r"TaskScheduler|Executor::|Pipeline|ExecuteTask|WaitForTask|PendingQuery|ClientContext::Execute", sym):
            return "duckdb:executor_wait"
    return "duckdb:other"


def classify(g, t, fr):
    leafsym, leafmod = fr[0] if fr else ("?", "?")
    lm = modname(leafmod)
    a = in_api(g, t)
    if a is not None:
        return f"cuda:{a}" + (":profiler" if lm.startswith(PROF_MOD) else ""), lm, leafsym
    if lm.startswith(PROF_MOD):
        return "profiler", lm, leafsym
    for sym, mod in fr[:3]:
        if WAIT_SYM.search(sym):
            if re.search(r"management_eventloop|processing_loop|worker_loop", sym):
                return "wait:sirius_loop_poll", lm, leafsym
            return "wait:os_wait_or_yield", lm, leafsym
    # find the first non-runtime frame for runtime leaves
    owner_sym, owner_mod = leafsym, lm
    if lm.startswith(RUNTIME_MOD):
        for sym, mod in fr[1:]:
            if not modname(mod).startswith(RUNTIME_MOD):
                owner_sym, owner_mod = sym, modname(mod); break
    tag = ""
    if lm.startswith(RUNTIME_MOD):
        if re.search(r"malloc|free|_int_|consolidate|calloc|realloc|operator new|operator delete|tcache|malloc_trim", leafsym):
            tag = "libc_alloc"
        elif re.search(r"mem(cpy|set|move|cmp)|str(len|cmp|chr)", leafsym):
            tag = "libc_mem_str"
        elif re.search(r"_dl_addr|_dl_|do_lookup|tls_get_addr", leafsym):
            tag = "libc_dl_lookup"
        else:
            tag = "libc_other"
    if owner_sym.startswith("libcudart_static") or re.match(r"(cuda|cu)[A-Z]\w*$", owner_sym):
        cat = "cudart_outside_traced_api"
    elif re.search(r"rmm::", owner_sym) or owner_mod.startswith("librmm"):
        cat = "rmm"
    elif owner_mod.startswith("libcudf"):
        cat = "cudf"
    elif owner_mod.startswith("libsirius"):
        cat = sirius_sub(fr)
    elif owner_mod == "duckdb":
        cat = duckdb_sub(fr)
    elif owner_mod.startswith("libcuda"):
        cat = "cuda_driver_outside_api"
    elif owner_mod.startswith(("[kernel", "[vdso")):
        cat = "kernel_or_vdso"
    elif owner_mod.startswith(PROF_MOD):
        cat = "profiler"
    elif owner_mod.startswith(RUNTIME_MOD):
        cat = "runtime_lib_unresolved_caller"
    else:
        cat = "other:" + owner_mod
    return cat + (f"[{tag}]" if tag else ""), lm, leafsym if owner_sym == leafsym else f"{leafsym} <- {owner_sym}"


# iterations
its = []
for i in range(NWARM, len(qb)):
    lo = qb[i] - 1e6
    hi = (qb[i + 1] - 1e6) if i + 1 < len(qb) else lo + 0.04e9
    A = api[bisect.bisect_left(api_starts, lo):bisect.bisect_left(api_starts, hi)]
    G = gpu[bisect.bisect_left(gstarts, lo):bisect.bisect_left(gstarts, hi)]
    if not A: continue
    es = A[0][0]; ee = max(max(a[1] for a in A), max(g[1] for g in G))
    its.append({"i": i + 1, "qb": qb[i], "es": es, "ee": ee, "qe": qe[i] if i < len(qe) else ee, "busy": union_list(G),
                "timer_ms": timer[i] if i < len(timer) else None,
                "kernels": bisect.bisect_left(kern_starts, hi) - bisect.bisect_left(kern_starts, lo)})
win_lo = [x["qb"] - 1e6 for x in its]


def where(t):
    j = bisect.bisect_right(win_lo, t) - 1
    if j < 0: return None, None
    x = its[j]
    if x["qb"] - 1e6 <= t < x["es"]: return j, "planning"
    if x["es"] <= t <= x["ee"]:
        b = x["busy"]; k = bisect.bisect_right([s for s, _ in b], t) - 1
        return j, ("engine_gpu_busy" if k >= 0 and b[k][0] <= t < b[k][1] else "engine_gpu_idle")
    if x["ee"] < t <= max(x["qe"] + 1e6, x["ee"]): return j, "post_engine"
    return None, None


# calibrate thread-CPU time per sample from on-CPU intervals of application threads inside the measured windows
tot_on = 0; tot_samp = 0
lo_all, hi_all = its[0]["qb"] - 1e6, its[-1]["ee"]
for g, iv in oncpu.items():
    tot_on += sum(max(0, min(e, hi_all) - max(s, lo_all)) for s, e in iv)
tot_samp = sum(1 for s, g, _ in samples if is_app(g) and lo_all <= s <= hi_all)
dt = tot_on / max(tot_samp, 1)

rows = collections.Counter(); wall = collections.Counter(); topf = collections.defaultdict(collections.Counter)
mod_cnt = collections.Counter(); thread_cnt = collections.Counter(); prof_thread_samples = 0
for s, g, cid in samples:
    if (g >> 24) != PID: continue
    j, w = where(s)
    if w is None: continue
    if not is_app(g):
        prof_thread_samples += 1; rows[(w, "profiler_threads")] += 1; continue
    cat, lm, leafsym = classify(g, s, frames.get(cid, []))
    rows[(w, cat)] += 1
    mod_cnt[(w, lm)] += 1
    thread_cnt[(w, re.sub(r"\d+$", "N", tname.get(g, "?")))] += 1
    topf[w][(cat, lm, leafsym[:160])] += 1
    if w == "engine_gpu_idle":
        k = max(1, k_at(s)); wall[cat] += dt / k

# exact wall accounting inside engine spans: GPU idle with zero app threads on CPU; what pipeline threads are blocked in
off_by_thread = collections.Counter(); off_iv = []
_seen_cache = {}


def last_seen_in(x):
    """application threads that were on-CPU at least once inside this engine span (i.e. alive and involved)"""
    k = id(x)
    if k not in _seen_cache:
        _seen_cache[k] = {g for g, iv in oncpu.items() if any(e > x["es"] and s < x["ee"] for s, e in iv)}
    return _seen_cache[k]


idle_total = 0; idle_none_on = 0; blocked_in = collections.Counter(); idle_on_any = 0
for x in its:
    pts = sorted({x["es"], x["ee"]} | {p for b in x["busy"] for p in b} |
                 {p for iv in oncpu.values() for s, e in iv if e > x["es"] and s < x["ee"] for p in (s, e)})
    pts = [p for p in pts if x["es"] <= p <= x["ee"]]
    b = x["busy"]; bstarts = [q for q, _ in b]
    for a, z in zip(pts, pts[1:]):
        if z <= a: continue
        m = (a + z) / 2
        k = bisect.bisect_right(bstarts, m) - 1
        if k >= 0 and b[k][0] <= m < b[k][1]: continue
        idle_total += z - a
        if k_at(m) == 0:
            idle_none_on += z - a
            off_iv.append((a, z))
            calls = sorted({osrt_at(g, m) or ("in_cuda_api" if in_api(g, m) else "unknown")
                            for g in oncpu if tname.get(g, "").startswith("gpu_pipeline")})
            blocked_in["+".join(calls)] += z - a
            for g in oncpu:
                if g in last_seen_in(x):
                    off_by_thread[(re.sub(r"\d+$", "N", tname.get(g, "?")), osrt_at(g, m) or ("in_cuda_api" if in_api(g, m) else "unknown"))] += z - a
        else:
            idle_on_any += z - a

n = len(its)
out = {"q": N, "iterations": n, "kernels_per_iter": [x["kernels"] for x in its][:3],
       "timer_ms_median": float(np.median([x["timer_ms"] for x in its if x["timer_ms"] is not None])),
       "engine_ms_median": float(np.median([(x["ee"] - x["es"]) / 1e6 for x in its])),
       "planning_ms_median": float(np.median([(x["es"] - x["qb"]) / 1e6 for x in its])),
       "gpu_busy_ms_median": float(np.median([sum(e - s for s, e in x["busy"]) / 1e6 for x in its])),
       "thread_cpu_us_per_sample": dt / 1e3, "app_samples_in_windows": tot_samp, "profiler_thread_samples": prof_thread_samples,
       "gpu_idle_engine_ms_per_iter": idle_total / n / 1e6,
       "gpu_idle_some_app_thread_on_cpu_ms_per_iter": idle_on_any / n / 1e6,
       "gpu_idle_all_app_threads_off_cpu_ms_per_iter": idle_none_on / n / 1e6,
       "all_off_cpu_pipeline_threads_blocked_in_ms_per_iter": {k: v / n / 1e6 for k, v in blocked_in.most_common(12)},
       "all_off_cpu_episodes": (lambda u: {"per_iter": len(u) / n, "median_us": float(np.median([e - s for s, e in u])) / 1e3 if u else 0,
                                          "p90_us": float(np.percentile([e - s for s, e in u], 90)) / 1e3 if u else 0})(union_list(off_iv)),
       "all_off_cpu_thread_state_ms_per_iter": {f"{k[0]}|{k[1]}": v / n / 1e6 for k, v in off_by_thread.most_common(25)},
       "gpu_idle_wall_attrib_ms_per_iter": {k: v / n / 1e6 for k, v in wall.most_common()},
       "samples_by_window_category": {f"{w}|{k}": v for (w, k), v in sorted(rows.items())},
       "samples_by_window_leafmodule": {f"{w}|{k}": v for (w, k), v in mod_cnt.most_common(60)},
       "samples_by_window_thread": {f"{w}|{k}": v for (w, k), v in thread_cnt.most_common(40)},
       "top_functions": {w: [[v, *k] for k, v in topf[w].most_common(120)] for w in topf}}
json.dump(out, open(f"{D}/cpu_attrib_q{N}.json", "w"), indent=1)
with open(f"{D}/cpu_samples_q{N}.csv", "w", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["q", "window", "category", "samples", "samples_per_iter", "thread_cpu_ms_per_iter", "gpu_idle_wall_ms_per_iter"])
    for (w, k), v in sorted(rows.items(), key=lambda kv: (kv[0][0], -kv[1])):
        wr.writerow([N, w, k, v, round(v / n, 3), round(v * dt / n / 1e6, 4),
                     round(wall.get(k, 0) / n / 1e6, 4) if w == "engine_gpu_idle" else ""])
print(json.dumps({k: v for k, v in out.items() if k not in ("top_functions", "samples_by_window_leafmodule")}, indent=1))
