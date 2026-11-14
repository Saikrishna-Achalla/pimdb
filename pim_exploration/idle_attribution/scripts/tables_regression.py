"""Tables + regression over the 21 queries from idle_buckets.json (run idle_buckets.py first).

Usage: <venv>/bin/python -I tables_regression.py
Writes idle_buckets_table.txt and regression.json next to idle_buckets.json.
Regression: OLS of per-query median engine time (nsys ns span) on launches / GPU ops / CUDA API calls / plan operators /
pinned MB, single-variable and two-variable; slope with standard error, intercept, R^2, leave-one-out slope range.
"""
import json, os, sys
import numpy as np

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = {r["q"]: r for r in json.load(open("/home/sai/cs254_project/tpch_q1_analysis/analysis/results/summary/summary_data.json"))}
B = json.load(open(f"{D}/idle_buckets.json"))
Q = sorted(int(q) for q in B)
out = []
P = lambda *a: out.append(" ".join(str(x) for x in a))

P("Per-query wall decomposition of one warm iteration (median of the 5 measured nsys iterations; ms)")
P("timer = DuckDB .timer real (1 ms res); pre = qb(log) -> first CUDA call; engine = CUDA-trace span; post = remainder of timer")
hdr = f"{'q':>3} {'timer':>6} {'pre':>5} {'engine':>6} {'post':>5} | {'gpuact':>6} {'launch':>6} {'alloc':>6} {'memcpy':>6} {'sync':>6} {'event':>6} {'other':>6} {'hostonly':>8} | {'idle%eng':>8} {'host%idle':>9} {'eng_untraced':>12}"
P(hdr)
tot = {}
rows = []
for q in Q:
    m = B[str(q)]["median"]; b = m["buckets_ms"]
    idle = m["engine_ms"] - b["gpu_active"]
    post = m["timer_ms"] - m["pre_engine_ms"] - m["engine_ms"]
    r = dict(q=q, timer=m["timer_ms"], pre=m["pre_engine_ms"], engine=m["engine_ms"], post=post, **{k.replace("api:", ""): v for k, v in b.items()},
             idle=idle, untraced=S[q]["engine_ms"], log_planning_untraced=S[q]["planning_ms"], warm_untraced=S[q]["warm_ms"])
    rows.append(r)
    P(f"{q:>3} {r['timer']:6.1f} {r['pre']:5.2f} {r['engine']:6.2f} {post:5.2f} | {b['gpu_active']:6.2f} {b['api:launch']:6.2f} {b['api:alloc']:6.2f} "
      f"{b['api:memcpy']:6.2f} {b['api:sync']:6.2f} {b['api:event']:6.2f} {b['api:other']:6.2f} {b['host_only']:8.2f} | "
      f"{100*idle/m['engine_ms']:7.1f}% {100*b['host_only']/idle:8.1f}% {S[q]['engine_ms']:12.1f}")
keys = ["timer", "pre", "engine", "post", "gpu_active", "launch", "alloc", "memcpy", "sync", "event", "other", "host_only", "idle"]
sm = {k: sum(r[k] for r in rows) for k in keys}
P(f"SUM {sm['timer']:6.1f} {sm['pre']:5.2f} {sm['engine']:6.2f} {sm['post']:5.2f} | {sm['gpu_active']:6.2f} {sm['launch']:6.2f} {sm['alloc']:6.2f} "
  f"{sm['memcpy']:6.2f} {sm['sync']:6.2f} {sm['event']:6.2f} {sm['other']:6.2f} {sm['host_only']:8.2f} | {100*sm['idle']/sm['engine']:7.1f}% {100*sm['host_only']/sm['idle']:8.1f}%")
P("Shares of the 21-query summed GPU-idle engine time:", ", ".join(f"{k} {100*sm[k]/sm['idle']:.1f}%" for k in
  ["launch", "alloc", "memcpy", "sync", "event", "other", "host_only"]))
P("Shares of summed .timer wall:", ", ".join(f"{k} {100*sm[k]/sm['timer']:.1f}%" for k in ["pre", "gpu_active", "idle", "post"]))
P(f"nsys CUDA-trace inflation of the engine window: sum nsys engine {sm['engine']:.1f} ms vs untraced timing-run engine (log, 1 ms) "
  f"{sum(r['untraced'] for r in rows):.1f} ms -> x{sm['engine']/sum(r['untraced'] for r in rows):.2f}; summed .timer under nsys "
  f"{sm['timer']:.1f} vs untraced warm {sum(r['warm_untraced'] for r in rows):.1f} ms")
napi = sum(B[str(q)]["median"]["api_calls"] for q in Q)
P(f"  CUDA API calls per iteration summed over queries: {napi:.0f}; (nsys engine - untraced engine)/API call = "
  f"{1e3*(sm['engine']-sum(r['untraced'] for r in rows))/napi:.2f} us (inferred tracing cost per call, includes 1 ms log rounding)")

P("\nCounts per warm iteration (median)")
P(f"{'q':>3} {'kern':>5} {'ops':>5} {'apicalls':>8} {'syncs':>6} {'memset':>6} {'H2D<=16B':>8} {'H2D>16B':>8} {'D2H<=16B':>8} {'D2H>16B':>8} {'D2D':>5} {'H2D_B':>8} {'D2H_B':>8} {'LAR':>5} {'LARmed_us':>9} {'LARp90_us':>9} {'plan_ops':>8} {'pipes':>5}")
for q in Q:
    d = B[str(q)]; m = d["median"]; mc = m["memcpy_by_dir_size"]
    h_small = mc.get("H2D:le16B", 0); h_big = sum(v for k, v in mc.items() if k.startswith("H2D") and k != "H2D:le16B")
    d_small = mc.get("D2H:le16B", 0); d_big = sum(v for k, v in mc.items() if k.startswith("D2H") and k != "D2H:le16B")
    dd = sum(v for k, v in mc.items() if k.startswith("D2D"))
    P(f"{q:>3} {m['kernels']:5.0f} {m['gpu_ops']:5.0f} {m['api_calls']:8.0f} {m['blocking_sync_calls']:6.0f} {m['memset']:6.0f} {h_small:8.0f} {h_big:8.0f} "
      f"{d_small:8.0f} {d_big:8.0f} {dd:5.0f} {m['memcpy_bytes'].get('H2D',0):8.0f} {m['memcpy_bytes'].get('D2H',0):8.0f} {m['lar']['count']:5.0f} "
      f"{m['lar']['host_gap_us_median']:9.1f} {m['lar']['host_gap_us_p90']:9.1f} {d['plan_ops']:8d} {d['pipelines']:5d}")

P("\nPer-thread time inside the engine span (all 21 queries summed, median iteration; ms)")
agg = {}
for q in Q:
    it = B[str(q)]["iterations"][len(B[str(q)]["iterations"]) // 2]
    # threads ordered by API calls -> rank labels
    for name, v in it["per_thread"].items():
        lab = name.split("#")[0]
        a = agg.setdefault(lab, {"api": 0, "not_in_api": 0, "not_in_api_gpu_idle": 0, "in_api_gpu_idle": 0, "launches": 0, "calls": 0, "n": 0})
        a["api"] += sum(v["api_ms"].values()); a["not_in_api"] += v["not_in_api_ms"]; a["not_in_api_gpu_idle"] += v["not_in_api_gpu_idle_ms"]
        a["in_api_gpu_idle"] += v["in_api_gpu_idle_ms"]; a["launches"] += v["launches"]; a["calls"] += v["api_calls"]; a["n"] += 1
for lab, a in sorted(agg.items()):
    P(f"  {lab:16s} queries={a['n']:2d} in_api={a['api']:7.2f} (of which GPU idle {a['in_api_gpu_idle']:6.2f}) not_in_api={a['not_in_api']:7.2f} "
      f"(GPU idle {a['not_in_api_gpu_idle']:6.2f}) launches={a['launches']} api_calls={a['calls']}")

# ---- regression
y = np.array([B[str(q)]["median"]["engine_ms"] for q in Q]) * 1e3  # us
yidle = np.array([B[str(q)]["median"]["engine_ms"] - B[str(q)]["median"]["buckets_ms"]["gpu_active"] for q in Q]) * 1e3
yun = np.array([S[q]["engine_ms"] for q in Q]) * 1e3
X = {"launches": [B[str(q)]["median"]["kernels"] for q in Q], "gpu_ops": [B[str(q)]["median"]["gpu_ops"] for q in Q],
     "api_calls": [B[str(q)]["median"]["api_calls"] for q in Q], "sync_calls": [B[str(q)]["median"]["blocking_sync_calls"] for q in Q],
     "plan_ops": [B[str(q)]["plan_ops"] for q in Q], "pipelines": [B[str(q)]["pipelines"] for q in Q],
     "pinned_mb": [B[str(q)]["pinned_mb"] for q in Q], "kernel_sum_us": [1e3 * B[str(q)]["median"]["kernel_sum_ms"] for q in Q]}
X = {k: np.array(v, float) for k, v in X.items()}


def ols(cols, yy):
    A = np.column_stack([X[c] for c in cols] + [np.ones(len(yy))])
    coef, *_ = np.linalg.lstsq(A, yy, rcond=None)
    res = yy - A @ coef; n, p = A.shape
    s2 = res @ res / (n - p); cov = s2 * np.linalg.inv(A.T @ A)
    r2 = 1 - res @ res / ((yy - yy.mean()) @ (yy - yy.mean()))
    loo = []
    for i in range(n):
        m = np.ones(n, bool); m[i] = False
        c2, *_ = np.linalg.lstsq(A[m], yy[m], rcond=None); loo.append(c2[0])
    return {"vars": cols, "coef": dict(zip(cols + ["intercept"], coef.round(3).tolist())),
            "se": dict(zip(cols + ["intercept"], np.sqrt(np.diag(cov)).round(3).tolist())), "r2": round(float(r2), 3),
            "loo_first_slope_range": [round(min(loo), 3), round(max(loo), 3)]}


reg = {}
for tgt, yy in [("engine_us_nsys", y), ("engine_idle_us_nsys", yidle), ("engine_us_untraced_log1ms", yun)]:
    reg[tgt] = [ols([c], yy) for c in X] + [ols(["launches", "kernel_sum_us"], yy), ols(["api_calls", "kernel_sum_us"], yy),
                                            ols(["launches", "plan_ops"], yy), ols(["launches", "pinned_mb"], yy)]
json.dump(reg, open(f"{D}/regression.json", "w"), indent=1)
P("\nRegression over 21 queries (per-query medians). slope +- SE, intercept, R^2, leave-one-out range of the first slope")
for tgt, L in reg.items():
    P(f" target {tgt}:")
    for r in L:
        P("   " + " + ".join(f"{r['coef'][v]:.3f}({r['se'][v]:.3f})*{v}" for v in r["vars"]) +
          f" + {r['coef']['intercept']:.0f}   R2={r['r2']:.3f}  LOO={r['loo_first_slope_range']}")
open(f"{D}/idle_buckets_table.txt", "w").write("\n".join(out) + "\n")
print("\n".join(out))
