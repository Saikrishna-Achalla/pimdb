"""Per-thread CUDA event stream of one warm (measured) iteration from the nsys sqlite export.

Usage as module: events(q, which=-1) -> dict with
  'lo','hi'      : iteration window (ns, session-relative), same window rule as nsys_breakdown.py
  'ev'           : list of runtime events in CPU time order, each a dict:
                   {t, tid, api, corr, kind in {'K','D2H','H2D','D2D','MEMSET','SYNC','MALLOC','FREE','EVENT','OTHER'},
                    name (kernel short name), demangled, grid, block, dur_ns, gstart, gend, bytes, stream}
Usage as script: python -I trace_events.py <q> [iteration_index]  -> prints the per-thread stream.
Iteration choice: the LAST measured iteration of the nsys run (all measured iterations have identical kernel counts,
see nsys_iteration_breakdown.json).
"""
import collections, glob, json, os, re, sqlite3, sys

RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
sys.path.insert(0, "/home/sai/cs254_project/tpch_q1_analysis/scripts/tpch_sf1")
import siriuslog  # noqa: E402


def windows(q):
    R = f"{RES}/q{q}"
    c = sqlite3.connect(glob.glob(f"{R}/traces/q*_nsys.sqlite")[0])
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
    w = [(tb[i] - 1e6, qe[i] + 1e6) for i in range(len(qb)) if i >= nwarm and i < len(tb) and i < len(qe)]
    return c, w


KIND = {1: "H2D", 2: "D2H", 8: "D2D", 10: "D2D"}


def events(q, which=-1):
    c, w = windows(q)
    lo, hi = w[which]
    names = dict(c.execute("select id, value from StringIds"))
    kern = {}
    for s, e, st, corr, sn, dn, gx, gy, gz, bx, by, bz, regs in c.execute(
            "select start,end,streamId,correlationId,shortName,demangledName,gridX,gridY,gridZ,blockX,blockY,blockZ,"
            "registersPerThread from CUPTI_ACTIVITY_KIND_KERNEL"):
        kern[corr] = dict(gstart=s, gend=e, stream=st, name=names[sn], demangled=names[dn], grid=gx * gy * gz,
                          block=bx * by * bz, dur_ns=e - s, regs=regs)
    mc = {corr: dict(gstart=s, gend=e, stream=st, bytes=b, copykind=KIND.get(k, str(k)))
          for s, e, st, corr, b, k in c.execute(
              "select start,end,streamId,correlationId,bytes,copyKind from CUPTI_ACTIVITY_KIND_MEMCPY")}
    ms = {corr: dict(gstart=s, gend=e, stream=st, bytes=b)
          for s, e, st, corr, b in c.execute("select start,end,streamId,correlationId,bytes from CUPTI_ACTIVITY_KIND_MEMSET")}
    sy = {corr: dict(gstart=s, gend=e, stream=st, synctype=t)
          for s, e, st, corr, t in c.execute(
              "select start,end,streamId,correlationId,syncType from CUPTI_ACTIVITY_KIND_SYNCHRONIZATION")}
    ev = []
    for s, e, tid, corr, nid in c.execute(
            "select start,end,globalTid,correlationId,nameId from CUPTI_ACTIVITY_KIND_RUNTIME where start>=? and start<? "
            "order by start", (lo, hi)):
        api = re.sub(r"_v\d+$", "", names.get(nid, "?"))
        d = dict(t=s, tend=e, tid=tid, api=api, corr=corr)
        if corr in kern:
            d.update(kind="K", **kern[corr])
        elif corr in mc:
            d.update(kind=mc[corr]["copykind"], **mc[corr])
        elif corr in ms:
            d.update(kind="MEMSET", **ms[corr])
        elif "Synchronize" in api:
            d.update(kind="SYNC", **sy.get(corr, {}))
        elif "Malloc" in api:
            d["kind"] = "MALLOC"
        elif "Free" in api:
            d["kind"] = "FREE"
        elif "Event" in api or "WaitEvent" in api:
            d["kind"] = "EVENT"
        else:
            d["kind"] = "OTHER"
        ev.append(d)
    # kernels whose launch API fell in the window, count check against the GPU-start rule of nsys_breakdown
    nk_gpu = sum(1 for k in kern.values() if lo <= k["gstart"] < hi)
    return dict(lo=lo, hi=hi, ev=ev, nk_gpu_window=nk_gpu, n_iter=len(w))


if __name__ == "__main__":
    q = int(sys.argv[1]); which = int(sys.argv[2]) if len(sys.argv) > 2 else -1
    E = events(q, which)
    ev = E["ev"]
    tids = collections.Counter(e["tid"] for e in ev if e["kind"] == "K")
    print(f"q{q}: {sum(tids.values())} kernels by API time, {E['nk_gpu_window']} by GPU start; threads {dict(tids)}")
    t0 = ev[0]["t"]
    tmap = {t: i for i, t in enumerate(sorted({e['tid'] for e in ev}))}
    for e in ev:
        if e["kind"] in ("MALLOC", "FREE", "OTHER", "EVENT"):
            continue
        extra = ""
        if e["kind"] == "K":
            extra = f"{e['name'][:60]:60s} g={e['grid']} b={e['block']} {e['dur_ns']/1e3:.1f}us s={e['stream']}"
        elif e["kind"] in ("D2H", "H2D", "D2D", "MEMSET"):
            extra = f"{e['bytes']}B s={e['stream']} {e['api']}"
        else:
            extra = e["api"] + f" s={e.get('stream')}"
        print(f"{(e['t']-t0)/1e3:9.1f} T{tmap[e['tid']]} {e['kind']:6s} {extra}")
