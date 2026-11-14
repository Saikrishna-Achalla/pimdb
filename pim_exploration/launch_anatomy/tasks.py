"""Split each pipeline thread's CUDA API stream of one warm iteration into Sirius pipeline TASKS.

Basis (sirius/src/pipeline/gpu_pipeline_task.cpp): every task does `stream.sync()` after prepare_for_processing (:748)
and again after publish_output (:890). `cuda::stream_ref::sync()` goes through the driver API, so both appear as
`cuStreamSynchronize` on the task's stream; libcudf's own syncs (rmm `stream.synchronize()`) appear as
`cudaStreamSynchronize`. A task boundary is therefore two consecutive `cuStreamSynchronize` calls on the thread's
task stream with no other CUDA API call between them (end of task i, start of task i+1).

tasks(q) -> list of tasks, each {thread, idx, t0, t1, events:[...]} (events = trace_events.events entries), in
start-time order.  Usage: python -I tasks.py <q> [--kernels-only]
"""
import collections, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trace_events import events  # noqa: E402

IGN = ("cudaStreamGetDevice", "cuKernelGetName", "cudaGetLastError", "cudaPeekAtLastError", "cudaGetDevice",
       "cudaSetDevice", "cuCtxGetCurrent", "cuCtxSetCurrent", "cudaDeviceGetAttribute", "cudaFuncGetAttributes",
       "cudaOccupancyMaxActiveBlocksPerMultiprocessorWithFlags", "cudaOccupancyMaxActiveBlocksPerMultiprocessor",
       "cudaGetDeviceProperties", "cudaFuncSetAttribute", "cudaDriverGetVersion", "cudaRuntimeGetVersion",
       "cuDevicePrimaryCtxGetState", "cudaThreadExchangeStreamCaptureMode", "cudaStreamIsCapturing",
       "cudaStreamGetCaptureInfo", "cuGetProcAddress", "cudaGetDriverEntryPoint", "cudaGetDriverEntryPointByVersion",
       "cuLibraryGetKernel", "cuKernelGetFunction", "cuFuncGetAttribute")


def tasks(q, which=-1):
    E = events(q, which)
    by = collections.defaultdict(list)
    for e in E["ev"]:
        by[e["tid"]].append(e)
    out = []
    tids = sorted(by)
    for ti, tid in enumerate(tids):
        ev = [e for e in by[tid] if e["api"] not in IGN]
        cus = collections.Counter(e.get("stream") for e in ev if e["api"] == "cuStreamSynchronize")
        if not cus:
            # a thread without task syncs (e.g. the client thread): one pseudo task
            out.append(dict(thread=ti, tid=tid, task_stream=None, t0=ev[0]["t"], t1=ev[-1]["tend"], events=ev,
                            pseudo=True))
            continue
        ts = cus.most_common(1)[0][0]
        is_cu = [e["api"] == "cuStreamSynchronize" and e.get("stream") == ts for e in ev]
        cut = [0]
        for i in range(1, len(ev)):
            if is_cu[i] and is_cu[i - 1]:
                cut.append(i)
        cut.append(len(ev))
        for a, b in zip(cut, cut[1:]):
            seg = ev[a:b]
            out.append(dict(thread=ti, tid=tid, task_stream=ts, t0=seg[0]["t"], t1=seg[-1]["tend"], events=seg,
                            pseudo=False))
    out.sort(key=lambda t: t["t0"])
    for i, t in enumerate(out):
        t["idx"] = i
    return out, E


def ksig(t):
    return [e for e in t["events"] if e["kind"] == "K"]


if __name__ == "__main__":
    q = int(sys.argv[1])
    T, E = tasks(q)
    base = E["ev"][0]["t"]
    nk = 0
    for t in T:
        ks = ksig(t)
        nk += len(ks)
        if "--kernels-only" in sys.argv and not ks:
            continue
        print(f"--- task {t['idx']} T{t['thread']} {(t['t0']-base)/1e3:.0f}-{(t['t1']-base)/1e3:.0f}us "
              f"{len(ks)} kernels{' PSEUDO' if t['pseudo'] else ''}")
        for e in t["events"]:
            if e["kind"] == "K":
                print(f"     K {e['name'][:44]:44s} g={e['grid']:<6} b={e['block']:<4} {e['dur_ns']/1e3:7.1f}us s={e['stream']}")
            elif e["kind"] in ("D2H", "H2D", "D2D", "MEMSET"):
                print(f"       {e['kind']} {e['bytes']}B")
    print("total kernels", nk, "tasks", len(T), "nonempty", sum(1 for t in T if ksig(t)))
