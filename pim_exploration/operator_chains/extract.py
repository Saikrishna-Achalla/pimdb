"""Shared extraction: one measured warm iteration of the nsys trace, per-thread kernel/API sequence, joined with ncu.

load(q) -> dict with
  kernels: list of nsys kernels in the iteration window, each {i, start, end, dur, tid, stream, name (demangled),
           mangled, grid, block, corr, launch_start, launch_end, ncu (matched ncu record or None)}
  api: per-tid sorted list of (start, end, name, corr) runtime calls in the window
  copies: memcpy records (start, end, bytes, dir, stream, tid)
Window = Sirius log `QueryBegin: transparent_execution` .. `QueryEnd` (+-1 ms) of nsys iteration ITER (default 5,
the same ordinal as the ncu warm iteration, which is iteration 5 of the ncu list/detail runs).
ncu matching: by mangled name, then grid and block; within one (name, grid, block) group the k-th nsys launch (time
order) is paired with the k-th ncu launch (ncu serialized order). Leftovers of one name are paired in order.
"""
import collections, glob, json, os, re, sqlite3, sys

RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
sys.path.insert(0, "/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1")
import siriuslog  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ITER = 5


def windows(q):
    R = f"{RES}/q{q}"
    c = sqlite3.connect(glob.glob(f"{R}/traces/q*_nsys.sqlite")[0])
    t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
    ts = lambda l: siriuslog.ts_ms(l) * 1e6 - t0
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
    return c, list(zip(tb, qe))


def load(q, it=ITER):
    c, W = windows(q)
    lo, hi = W[it - 1][0] - 1e6, W[it - 1][1] + 1e6
    S = dict(c.execute("select id, value from StringIds"))
    rt = {}
    api = collections.defaultdict(list)
    for s, e, n, corr, tid in c.execute(
            "select start, end, nameId, correlationId, globalTid from CUPTI_ACTIVITY_KIND_RUNTIME where start >= ? and start < ?",
            (lo - 5e6, hi)):
        name = re.sub(r"_v\d+$", "", S.get(n, "?"))
        rt[corr] = (tid, s, e, name)
        if s >= lo:
            api[tid].append((s, e, name, corr))
    for v in api.values():
        v.sort()
    K = []
    for (s, e, dn, mn, gx, gy, gz, bx, by, bz, st, corr) in c.execute(
            "select start, end, demangledName, mangledName, gridX, gridY, gridZ, blockX, blockY, blockZ, streamId, correlationId "
            "from CUPTI_ACTIVITY_KIND_KERNEL where start >= ? and start < ? order by start", (lo, hi)):
        tid, ls, le, _ = rt.get(corr, (None, None, None, None))
        K.append({"start": s, "end": e, "dur": e - s, "tid": tid, "stream": st, "name": S[dn], "mangled": S.get(mn, ""),
                  "grid": gx * gy * gz, "block": bx * by * bz, "corr": corr, "launch_start": ls, "launch_end": le})
    for i, k in enumerate(K):
        k["i"] = i
    MK = dict(c.execute("select id, label from ENUM_CUDA_MEM_KIND"))
    cps = []
    for s, e, b, sk, dk, st, corr in c.execute(
            "select start, end, bytes, srcKind, dstKind, streamId, correlationId from CUPTI_ACTIVITY_KIND_MEMCPY where start>=? and start<?",
            (lo, hi)):
        sd, dd = MK.get(sk, "?"), MK.get(dk, "?")
        dev = lambda x: x in ("Device", "Device Static", "Array")
        d = "D2D" if dev(sd) and dev(dd) else ("H2D" if dev(dd) else ("D2H" if dev(sd) else "H2H"))
        cps.append({"start": s, "end": e, "bytes": b, "dir": d, "stream": st, "tid": rt.get(corr, (None,))[0], "corr": corr})
    sets = [{"start": s, "end": e, "bytes": b, "stream": st, "tid": rt.get(corr, (None,))[0]} for s, e, b, st, corr in c.execute(
        "select start, end, bytes, streamId, correlationId from CUPTI_ACTIVITY_KIND_MEMSET where start>=? and start<?", (lo, hi))]
    # ncu match
    N = json.load(open(f"{RES}/q{q}/ncu_warm_metrics.json"))["kernels"]
    byname = collections.defaultdict(list)
    for n in N:
        byname[n["mangled"]].append(n)
    nk = collections.defaultdict(list)
    for k in K:
        nk[k["mangled"]].append(k)
    exact = 0
    for m, ks in nk.items():
        ns = list(byname.get(m, []))
        used = set()
        rest = []
        for k in ks:
            j = next((j for j, n in enumerate(ns) if j not in used and n["grid"] == k["grid"] and n["block"] == k["block"]), None)
            if j is None:
                rest.append(k)
            else:
                used.add(j); k["ncu"] = ns[j]; exact += 1
        left = [n for j, n in enumerate(ns) if j not in used]
        for k, n in zip(rest, left):
            k["ncu"] = n
        for k in rest[len(left):]:
            k["ncu"] = None
    meta = {"q": q, "iter": it, "window_ns": (lo, hi), "n_kernels": len(K), "n_ncu": len(N),
            "ncu_matched": sum(k.get("ncu") is not None for k in K), "ncu_matched_exact_grid": exact}
    return {"kernels": K, "api": dict(api), "copies": cps, "memsets": sets, "meta": meta}


if __name__ == "__main__":
    q = int(sys.argv[1])
    D = load(q)
    print(D["meta"])
    from classify import sub_op, refine
    bytid = collections.defaultdict(list)
    for k in D["kernels"]:
        k["sub"] = sub_op(k["name"])
        bytid[k["tid"]].append(k)
    t0 = D["kernels"][0]["start"]
    for tid, ks in bytid.items():
        refine(ks)
        api = D["api"].get(tid, [])
        print(f"=== tid {tid % 10**6}  {len(ks)} kernels")
        prev = None
        for k in ks:
            n = k.get("ncu") or {}
            if prev:
                between = [a for a in api if prev["launch_end"] <= a[0] < k["launch_start"]]
                c = collections.Counter(a[2] for a in between)
                if c:
                    print("            host:", dict(c), f"{sum(a[1]-a[0] for a in between)/1e3:.1f}us")
            gap = (k["start"] - prev["end"]) / 1e3 if prev else 0
            print(f"{(k['start']-t0)/1e3:9.1f} +{gap:7.1f} s{k['stream']:<3} {k['op'][:16]:16s} {k['sub']:20s} g{k['grid']:<6} "
                  f"{k['dur']/1e3:6.1f}us rd{n.get('dram_rd',0)/1e3:8.1f}K wr{n.get('dram_wr',0)/1e3:8.1f}K  {k['name'][:70]}")
            prev = k
