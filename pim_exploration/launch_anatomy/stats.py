"""Aggregate launch_attribution.json into the numbers reported (writes stats.json, roundtrips.csv, prints tables).

Usage: python -I stats.py
"""
import collections, csv, json, os, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import tasks  # noqa: E402
from trace_events import events  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
A = json.load(open(f"{HERE}/launch_attribution.json"))
CAUSES = ("distinct", "multi-pass", "per-column", "per-batch", "bookkeeping")
S = {}

L = [(int(q), x) for q, r in A.items() for v in r["instances"].values() for x in v["launches"]]
N = len(L)
tot_ns = sum(x["dur_ns"] for _, x in L)
cc = collections.Counter(x["cause"] for _, x in L)
ct = collections.Counter()
for _, x in L:
    ct[x["cause"]] += x["dur_ns"]
S["n_launches"] = N
S["kernel_time_us"] = tot_ns / 1e3
S["cause_launches"] = {c: cc[c] for c in CAUSES}
S["cause_share"] = {c: round(cc[c] / N, 4) for c in CAUSES}
S["cause_time_share"] = {c: round(ct[c] / tot_ns, 4) for c in CAUSES}
S["confidence"] = dict(collections.Counter(x["confidence"] for _, x in L))
S["grid1"] = sum(1 for _, x in L if x["grid"] == 1)
S["threads_le_1024"] = sum(1 for _, x in L if x["grid"] * x["block"] <= 1024)
S["grid1_time_us"] = sum(x["dur_ns"] for _, x in L if x["grid"] == 1) / 1e3
S["lt5us"] = sum(1 for _, x in L if x["dur_ns"] < 5000)
S["distinct_short_names"] = len({x["short"] for _, x in L})
S["distinct_names_prefix120"] = len({x["name"] for _, x in L})
S["other_stream_launches"] = sum(1 for _, x in L if x["other_stream"])
# grid==1 by cause
S["grid1_by_cause"] = dict(collections.Counter(x["cause"] for _, x in L if x["grid"] == 1))

# per operator type: launches per execution block and per plan instance
blocks = collections.defaultdict(list)
for q, x in L:
    blocks[(q, x["exec_block"], x["op_type"])].append(x)
bt = collections.defaultdict(list)
for (q, b, t), xs in blocks.items():
    bt[t].append(len(xs))
inst = collections.defaultdict(list)
for q, r in A.items():
    for key, v in r["instances"].items():
        inst[v["op_type"]].append(len(v["launches"]))
typ = collections.Counter(x["op_type"] for _, x in L)
typ_t = collections.Counter()
for _, x in L:
    typ_t[x["op_type"]] += x["dur_ns"]
S["by_type"] = {}
for t, n in typ.most_common():
    b, i = bt[t], inst[t]
    tc = collections.Counter(x["cause"] for _, x in L if x["op_type"] == t)
    S["by_type"][t] = dict(launches=n, kernel_us=round(typ_t[t] / 1e3, 1), executions=len(b),
                           per_exec_min=min(b), per_exec_med=statistics.median(b), per_exec_max=max(b),
                           plan_instances=len(i), per_inst_min=min(i), per_inst_med=statistics.median(i),
                           per_inst_max=max(i), causes={c: tc[c] for c in CAUSES},
                           grid1=sum(1 for _, x in L if x["op_type"] == t and x["grid"] == 1))

# batches: tasks per pipeline whose source is GPU_SCAN (from attribution tasks)
S["scan_batches"] = {}
for q, r in A.items():
    per = collections.Counter()
    srcs = {}
    for key, v in r["instances"].items():
        if v["pipeline_ops"] and v["pipeline_ops"][0].startswith("GPU_SCAN"):
            srcs[v["pipeline"]] = set(v["tasks"]) | srcs.get(v["pipeline"], set())
    S["scan_batches"][q] = {f"P{p}": len(ts) for p, ts in sorted(srcs.items())}

# per query: per-batch launches, tasks
S["per_query"] = {}
for q, r in A.items():
    xs = [x for v in r["instances"].values() for x in v["launches"]]
    S["per_query"][q] = dict(kernels=len(xs), tasks=r["n_tasks"], kernel_tasks=r["n_kernel_tasks"],
                             empty_tasks=r["n_tasks"] - r["n_kernel_tasks"],
                             causes={c: sum(1 for x in xs if x["cause"] == c) for c in CAUSES},
                             grid1=sum(1 for x in xs if x["grid"] == 1))

# host round trips
rows = []
rt_type = collections.Counter()
for q in sorted(A, key=int):
    lk = {}
    for v in A[q]["instances"].values():
        for x in v["launches"]:
            lk[(x["task"], x["t_launch"])] = x["op_type"]
    T, E = tasks(int(q))
    d2h_sync = h2d_sync = syncs = d2h_small = launches = 0
    sync_kinds = collections.Counter()
    for t in T:
        ev = t["events"]
        prev_type = None
        for i, e in enumerate(ev):
            if e["kind"] == "K":
                prev_type = lk.get((t["idx"], e["t"]), prev_type)
                launches += 1
            if e["kind"] == "SYNC":
                syncs += 1
                sync_kinds[e["api"]] += 1
            if e["kind"] == "D2H" and e.get("bytes", 0) <= 64:
                d2h_small += 1
            if e["kind"] in ("D2H", "H2D") and e.get("bytes", 0) <= 4096:
                nxt_type = None
                synced = False
                for f in ev[i + 1:]:
                    if f["kind"] == "SYNC":
                        synced = True
                    if f["kind"] == "K":
                        nxt_type = lk.get((t["idx"], f["t"]))
                        break
                if synced:
                    if e["kind"] == "D2H":
                        d2h_sync += 1
                        rt_type[prev_type or nxt_type or "task prologue (no kernel yet)"] += 1
                    else:
                        h2d_sync += 1
    task_syncs = 2 * len(T)
    rows.append(dict(q=int(q), kernels=launches, tasks=len(T), d2h_readbacks_then_sync=d2h_sync,
                     h2d_then_sync=h2d_sync, d2h_le64B=d2h_small, sync_calls=syncs,
                     task_boundary_syncs=task_syncs, readbacks_per_kernel=round(d2h_sync / launches, 3),
                     **{f"sync_{k}": v for k, v in sync_kinds.items()}))
with open(f"{HERE}/roundtrips.csv", "w", newline="") as f:
    keys = sorted({k for r in rows for k in r}, key=lambda k: (k != "q", k))
    w = csv.DictWriter(f, fieldnames=keys)
    w.writeheader()
    w.writerows(rows)
S["roundtrips"] = rows
S["readbacks_by_preceding_op_type"] = dict(rt_type.most_common())
json.dump(S, open(f"{HERE}/stats.json", "w"), indent=1)

print(f"launches {N}, kernel time {tot_ns/1e6:.2f} ms; confidence {S['confidence']}")
print("cause shares (launches / time):")
for c in CAUSES:
    print(f"  {c:12s} {cc[c]:5d} {100*cc[c]/N:5.1f}%  {100*ct[c]/tot_ns:5.1f}% of kernel time")
print(f"grid==1: {S['grid1']} ({100*S['grid1']/N:.1f}%), {S['grid1_time_us']:.0f} us; grid*block<=1024: {S['threads_le_1024']}; "
      f"<5us: {S['lt5us']}; distinct short names {S['distinct_short_names']}, distinct (120-char) names {S['distinct_names_prefix120']}")
print(f"grid1 by cause {S['grid1_by_cause']}; launches on another stream {S['other_stream_launches']}")
print(f"\n{'type':28s} {'launch':>6} {'us':>7} {'execs':>5} {'per-exec min/med/max':>20} {'inst':>4} {'per-inst min/med/max':>20}  causes D/M/C/B/K  grid1")
for t, d in S["by_type"].items():
    cz = "/".join(str(d["causes"][c]) for c in CAUSES)
    print(f"{t[:28]:28s} {d['launches']:6d} {d['kernel_us']:7.0f} {d['executions']:5d} "
          f"{d['per_exec_min']:6d}/{d['per_exec_med']:5.1f}/{d['per_exec_max']:4d}  {d['plan_instances']:4d} "
          f"{d['per_inst_min']:6d}/{d['per_inst_med']:5.1f}/{d['per_inst_max']:4d}  {cz}  {d['grid1']}")
print("\nscan batches per GPU_SCAN pipeline:", {q: v for q, v in S["scan_batches"].items()})
print("\nround trips per warm iteration:")
for r in rows:
    print(f"  q{r['q']:2d} kernels {r['kernels']:3d} tasks {r['tasks']:2d} D2H-readback+sync {r['d2h_readbacks_then_sync']:3d} "
          f"H2D+sync {r['h2d_then_sync']:3d} syncs {r['sync_calls']:3d} D2H<=64B {r['d2h_le64B']:3d}")
print("readbacks by op type of preceding kernel:", S["readbacks_by_preceding_op_type"])

# ---- readbacks by the call of the preceding kernel (what value the host is waiting for)
CAT = [("select sweep", "output row count of a compaction / copy_if (allocate gathered columns)"),
       ("copy_if of matches", "join output row count (allocate join result)"),
       ("hash_join offsets", "join output row count (allocate join result)"),
       ("join post-filter", "join output row count (allocate join result)"),
       ("strings offsets", "string column total bytes (allocate chars buffer)"),
       ("strings gather chars", "string column total bytes / chars size (allocate chars buffer)"),
       ("mapping_indices", "group-by shared-memory fallback flag (choose algorithm)"),
       ("retrieve_all", "number of groups (allocate group-by result)"),
       ("internal pass: compact", "number of groups (allocate group-by result)"),
       ("keys_ascending", "keys-sorted check (choose sort vs hash group-by)"),
       ("sums_to_widen", "SUM overflow min/max check (choose result type)"),
       ("minmax", "min/max pre-check (choose type / zone map)"),
       ("approx_distinct", "HyperLogLog estimate (choose dictionary encoding)"),
       ("single_thread", "scalar extraction (get_element / minmax result)"),
       ("DeviceReduce", "reduction scalar"),
       ("dense count join", "dense count join sizes"),
       ("sort/top-k", "top-N boundary / sort result"),
       ("conditional join", "conditional join output size")]
rb_call = collections.Counter()
rb_cat = collections.Counter()
for q in sorted(A, key=int):
    lk = {}
    for v in A[q]["instances"].values():
        for x in v["launches"]:
            lk[(x["task"], x["t_launch"])] = x
    T, E = tasks(int(q))
    for t in T:
        prev = None
        ev = t["events"]
        for i, e in enumerate(ev):
            if e["kind"] == "K":
                prev = lk.get((t["idx"], e["t"]))
                continue
            if e["kind"] == "D2H" and e.get("bytes", 0) <= 4096:
                synced = False
                for f in ev[i + 1:]:
                    if f["kind"] == "K":
                        break
                    if f["kind"] == "SYNC":
                        synced = True
                        break
                if not synced:
                    continue
                call = prev["call"] if prev else "(no kernel yet in task)"
                rb_call[call[:60]] += 1
                cat = next((c for k, c in CAT if k in call), "other / not data-sizing (result copy, task prologue, cast, gather)")
                rb_cat[cat] += 1
                prev = None  # a second readback right after the same kernel counts against 'other'
S["readbacks_by_value"] = dict(rb_cat.most_common())
S["readbacks_by_preceding_call"] = dict(rb_call.most_common(40))
json.dump(S, open(f"{HERE}/stats.json", "w"), indent=1)
print("\nD2H readback round trips by the value the host waits for (all 21 queries):")
for c, n in rb_cat.most_common():
    print(f"  {n:4d}  {c}")

# ---- readbacks by size, and by position (before the first kernel of the task / between kernels)
by_size = collections.Counter()
for q in sorted(A, key=int):
    T, E = tasks(int(q))
    for t in T:
        ev = t["events"]
        for i, e in enumerate(ev):
            if e["kind"] == "D2H" and e.get("bytes", 0) <= 4096:
                synced = False
                for f in ev[i + 1:]:
                    if f["kind"] == "K":
                        break
                    if f["kind"] == "SYNC":
                        synced = True
                        break
                if synced:
                    by_size[e["bytes"]] += 1
S["readbacks_by_bytes"] = dict(sorted(by_size.items()))
json.dump(S, open(f"{HERE}/stats.json", "w"), indent=1)
print("D2H readback round trips by size (bytes: count):", dict(sorted(by_size.items())))

# ---- distinct kernel symbols (full demangled names, nsys) vs launches
syms, per_q = collections.Counter(), {}
for q in sorted(A, key=int):
    E = events(int(q))
    ks = [e["demangled"] for e in E["ev"] if e["kind"] == "K"]
    syms.update(ks)
    per_q[q] = (len(ks), len(set(ks)))
S["distinct_symbols_all"] = len(syms)
S["distinct_symbols_per_query"] = per_q
S["top_symbols"] = [(n, s[:160]) for s, n in syms.most_common(10)]
json.dump(S, open(f"{HERE}/stats.json", "w"), indent=1)
print(f"distinct demangled symbols over 21 queries: {len(syms)} for {sum(syms.values())} launches; per query "
      f"(launches, distinct): {per_q}")

# ---- "the same kernel again": launches whose short name already appeared in the same execution block / task
blk_rep = task_rep = 0
for (q, b, t), xs in blocks.items():
    seen = set()
    for x in sorted(xs, key=lambda x: x["t_launch"]):
        if x["short"] in seen:
            blk_rep += 1
        seen.add(x["short"])
tk = collections.defaultdict(list)
for q, x in L:
    tk[(q, x["task"])].append(x)
for k, xs in tk.items():
    seen = set()
    for x in sorted(xs, key=lambda x: x["t_launch"]):
        if x["short"] in seen:
            task_rep += 1
        seen.add(x["short"])
S["same_name_repeat_in_exec_block"] = blk_rep
S["same_name_repeat_in_task"] = task_rep
json.dump(S, open(f"{HERE}/stats.json", "w"), indent=1)
print(f"launches repeating a kernel name already launched in the same operator execution: {blk_rep} ({100*blk_rep/N:.1f}%); "
      f"in the same task: {task_rep} ({100*task_rep/N:.1f}%)")

# ---- per-batch split: repeated tasks of the same pipeline vs merge/concat operators
rep_task = sum(1 for _, x in L if x["cause"] == "per-batch" and x["batch"] > 1)
merge_op = sum(1 for _, x in L if x["cause"] == "per-batch" and x["batch"] == 1)
rep_t = sum(x["dur_ns"] for _, x in L if x["cause"] == "per-batch" and x["batch"] > 1) / 1e3
mer_t = sum(x["dur_ns"] for _, x in L if x["cause"] == "per-batch" and x["batch"] == 1) / 1e3
mtn = sum(1 for _, x in L if x["op_type"] == "MERGE_TOP_N")
S["per_batch_split"] = dict(repeat_task_launches=rep_task, repeat_task_us=rep_t, merge_concat_launches=merge_op,
                            merge_concat_us=mer_t, merge_top_n_launches=mtn)
json.dump(S, open(f"{HERE}/stats.json", "w"), indent=1)
print("per-batch split:", S["per_batch_split"])
