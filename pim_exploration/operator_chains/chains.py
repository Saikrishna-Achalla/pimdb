"""Operator-chain analysis of the warm iteration of TPC-H Q2-Q22 at SF1 (Sirius on RTX 5070).

Inputs (read-only): results/q<N>/traces/q<N>_nsys.sqlite (kernel order, host thread, real-clock times, CUDA API
calls), ncu_warm_metrics.json (cold-L2 dram_rd), ncu_raw/q<N>.json (SM global store/load/atomic bytes, from
ncu_raw.py), query_plan.txt, sort_input_rows.json.
Outputs: dataflow_q<N>.json, chain_ngrams.csv, chain_candidates.csv, roundtrip_bytes.csv, groupby_sort.csv,
         placement.csv, upper_bound.csv  (all in this directory)

Definitions
  kernel  : one launch in nsys iteration 5 (same ordinal as the ncu warm iteration), matched 1:1 to its ncu record.
  step    : maximal run of consecutive kernels on ONE host thread with the same sub-operator label (classify.py).
  segment : maximal run of consecutive steps on one thread with the same level-1 operator label.
  task    : maximal run of consecutive segments on one thread in which each consecutive pair is allowed by the
            query plan (plan.allowed_pairs) AND the gap between them is < TASK_GAP_US. Inside a task, data flow from
            one step to the next on the same thread (a Sirius pipeline task runs one batch through its operators
            on one thread).
  wr(step)   = SM global store bytes + global atomic/reduction bytes of its kernels (ncu, l1tex sectors x 32 B).
               dram_wr is NOT used: with the L2 flushed before each kernel, written data stays in the 48 MB L2
               and dram_wr is ~0 (91 MB summed over all 21 queries vs 1,094 MB of SM stores).
  rd(step)   = dram_rd of its kernels (ncu, cold L2 => upper bound of what a warm L2 would fetch from DRAM).
  round-trip intermediate of an edge P->C = min(wr(P), rd(C)): bytes written by the producer to memory and read back
               by the consumer (bounded both ways). Upper-bound flavoured: rd is cold-L2.
  gap(P->C)  = nsys real-clock time from the end of P's last kernel to the start of C's first kernel.
  host(P->C) = CUDA API calls on that thread between P's last launch returning and C's first launch.
"""
import collections, csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import classify, extract, plan  # noqa: E402

TASK_GAP_US = float(os.environ.get("TASK_GAP_US", 300))
BW = 672e9  # B/s, DRAM peak (for the modeled data-movement time only)
SYNC = {"cudaStreamSynchronize", "cuStreamSynchronize", "cudaEventSynchronize", "cudaDeviceSynchronize", "cuCtxSynchronize"}
ROWS = {int(k): v for k, v in json.load(open(f"{HERE}/sort_input_rows.json")).items()}
PRED = {"pred_ast", "pred_binop", "pred_string"}
GATHER = {"gather"}
PREP = {"ht_init", "fill"}


def union_ns(iv):
    tot, ce = 0, None
    for s0, e0 in sorted(i for i in iv if i[1] > i[0]):
        if ce is None or s0 > ce:
            tot += e0 - s0; ce = e0
        elif e0 > ce:
            tot += e0 - ce; ce = e0
    return tot


def host_between(api, corr_dir, t0, t1):
    c = collections.Counter()
    d2h = 0
    for s, e, n, corr in api:
        if t0 <= s < t1:
            c[n] += 1
            if corr_dir.get(corr, (None, 0))[0] == "D2H":
                c["_d2h"] += 1; d2h += corr_dir[corr][1]
    sync = sum(v for k, v in c.items() if k in SYNC)
    alloc = c.get("cudaMallocFromPoolAsync", 0) + c.get("cudaMallocAsync", 0) + c.get("cudaMalloc", 0)
    kind = "readback+sync" if c.get("_d2h") and sync else ("sync" if sync else ("alloc" if alloc else ("launch-only" if not c else "async-api")))
    return {"kind": kind, "syncs": sync, "d2h_copies": c.get("_d2h", 0), "d2h_bytes": d2h, "allocs": alloc,
            "frees": c.get("cudaFreeAsync", 0), "event_waits": c.get("cudaStreamWaitEvent", 0), "api_calls": sum(c.values()) - c.get("_d2h", 0)}


def analyse(q):
    D = extract.load(q)
    raw = json.load(open(f"{HERE}/ncu_raw/q{q}.json"))
    P = plan.parse(q)
    ok = plan.allowed_pairs(P)
    corr_dir = {c["corr"]: (c["dir"], c["bytes"]) for c in D["copies"]}
    K = D["kernels"]
    for k in K:
        k["sub"] = classify.sub_op(k["name"])
        n = k["ncu"]
        r = raw[n["src_index"]]
        k["wr"] = r["st_bytes"] + r["atom_bytes"]
        k["st"] = r["st_bytes"]
        k["rd"] = n["dram_rd"] or 0
        k["dram_wr"] = n["dram_wr"] or 0
        k["ld"] = r["ld_bytes"]
        k["ncu_dur"] = n["dur_ns"]
    by_t = collections.defaultdict(list)
    for k in K:
        by_t[k["tid"]].append(k)
    steps, segs = [], []
    for tid, ks in by_t.items():
        ks.sort(key=lambda k: k["start"])
        classify.refine(ks)
        cur = None
        for k in ks:
            if cur and cur["sub"] == k["sub"] and cur["op"] == k["op"]:
                cur["k"].append(k)
            else:
                cur = {"tid": tid, "sub": k["sub"], "op": k["op"], "k": [k]}
                steps.append(cur)
    # preparation steps (hash-table init, sequence/constant fill) read no producer data: fold them into the step
    # they prepare (next step on the same thread, if it starts within TASK_GAP_US), keeping its label
    merged, by_t2 = [], collections.defaultdict(list)
    for s in steps:
        by_t2[s["tid"]].append(s)
    for tid, ss in by_t2.items():
        pend = []
        for s in ss:
            if s["sub"] in PREP:
                pend.append(s); continue
            if pend and (s["k"][0]["start"] - pend[-1]["k"][-1]["end"]) / 1e3 < TASK_GAP_US:
                s["k"] = [k for p in pend for k in p["k"]] + s["k"]; s["prep_launches"] = sum(len(p["k"]) for p in pend)
            else:
                merged.extend(pend)
            pend = []
            merged.append(s)
        merged.extend(pend)
    steps = sorted(merged, key=lambda s: (s["tid"], s["k"][0]["start"]))
    for i, s in enumerate(steps):
        ks = s["k"]
        s.setdefault("prep_launches", 0)
        s.update(id=i, start=ks[0]["start"], end=max(k["end"] for k in ks), launches=len(ks),
                 ktime=sum(k["dur"] for k in ks), wr=sum(k["wr"] for k in ks), rd=sum(k["rd"] for k in ks),
                 dram_wr=sum(k["dram_wr"] for k in ks), ld=sum(k["ld"] for k in ks), grid=max(k["grid"] for k in ks),
                 placed=collections.Counter(k["placed"] for k in ks))
        s["inner_gap"] = sum(max(0, b["start"] - a["end"]) for a, b in zip(ks, ks[1:]))
        s["inner_host"] = [host_between(D["api"].get(s["tid"], []), corr_dir, a["launch_end"], b["launch_start"]) for a, b in zip(ks, ks[1:])]
    # segments and tasks per thread
    by_ts = collections.defaultdict(list)
    for s in steps:
        by_ts[s["tid"]].append(s)
    for tid, ss in by_ts.items():
        cur = None
        for s in ss:
            if cur and cur["op"] == s["op"]:
                cur["steps"].append(s)
            else:
                cur = {"tid": tid, "op": s["op"], "steps": [s]}
                segs.append(cur)
    for i, g in enumerate(segs):
        g["id"] = i
        g["start"], g["end"] = g["steps"][0]["start"], g["steps"][-1]["end"]
        for s in g["steps"]:
            s["seg"] = i
        cands = [o["id"] for o in P["ops"].values() if g["op"] in plan.CAT.get(o["type"], ())]
        g["plan_candidates"] = cands
        g["plan_id"] = cands[0] if len(cands) == 1 else None
    by_tg = collections.defaultdict(list)
    for g in segs:
        by_tg[g["tid"]].append(g)
    task = 0
    seg_edges = []
    for tid, gs in by_tg.items():
        for j, g in enumerate(gs):
            if j == 0:
                g["task"] = task; task += 1; continue
            p = gs[j - 1]
            gap_us = (g["start"] - p["end"]) / 1e3
            if (p["op"], g["op"]) in ok and p["op"] != "DYNF_BUILD" and gap_us < TASK_GAP_US:
                g["task"] = p["task"]
                seg_edges.append({"src": p["id"], "dst": g["id"], "kind": "same-thread", "confidence": "medium"})
            else:
                g["task"] = task; task += 1
    # cross-task edges: a task's first segment <- latest earlier task-final segment (any thread) whose label pair is
    # allowed by the plan; the dynamic-filter key set feeds the next DYNAMIC_FILTER probe that starts after it.
    finals = {}
    for g in segs:
        finals[g["task"]] = g  # last segment of each task (segs are in thread/time order)
    firsts = {}
    for g in segs:
        firsts.setdefault(g["task"], g)
    for t, g in firsts.items():
        cands = [f for tt, f in finals.items() if tt != t and f["end"] <= g["start"] and
                 ((f["op"], g["op"]) in ok or (f["op"] == "DYNF_BUILD" and g["op"] == "DYNAMIC_FILTER"))]
        if cands:
            f = max(cands, key=lambda f: f["end"])
            seg_edges.append({"src": f["id"], "dst": g["id"], "kind": "cross-thread" if f["tid"] != g["tid"] else "same-thread-new-task",
                              "confidence": "low"})
    # DYNF_BUILD segments: inputs come from the build side (latest earlier task-final segment allowed into DYNF_BUILD)
    # step edges inside tasks
    step_edges = []
    for tid, ss in by_ts.items():
        for a, b in zip(ss, ss[1:]):
            if segs[a["seg"]]["task"] == segs[b["seg"]]["task"]:
                step_edges.append((a, b, "same-thread"))
    for e in seg_edges:
        if e["kind"] != "same-thread":
            a, b = segs[e["src"]]["steps"][-1], segs[e["dst"]]["steps"][0]
            step_edges.append((a, b, e["kind"]))
    E = []
    for a, b, kind in step_edges:
        h = host_between(D["api"].get(b["tid"], []), corr_dir, a["k"][-1]["launch_end"], b["k"][0]["launch_start"]) \
            if kind == "same-thread" else {"kind": "thread-hand-off" if kind == "cross-thread" else "task-boundary"}
        E.append({"src": a["id"], "dst": b["id"], "kind": kind, "src_sub": a["sub"], "dst_sub": b["sub"], "src_op": a["op"], "dst_op": b["op"],
                  "intra_op": a["seg"] == b["seg"], "wr_src": a["wr"], "dram_wr_src": a["dram_wr"], "rd_dst": b["rd"],
                  "roundtrip": min(a["wr"], b["rd"]), "launches_src": a["launches"], "launches_dst": b["launches"],
                  "gap_ns": max(0, b["start"] - a["end"]), "host": h})
    SE = []
    for e in seg_edges:
        a, b = segs[e["src"]], segs[e["dst"]]
        sa, sb = a["steps"][-1], b["steps"][0]
        h = host_between(D["api"].get(b["tid"], []), corr_dir, sa["k"][-1]["launch_end"], sb["k"][0]["launch_start"]) \
            if e["kind"] == "same-thread" else {"kind": "thread-hand-off" if e["kind"] == "cross-thread" else "task-boundary"}
        SE.append(dict(e, src_op=a["op"], dst_op=b["op"], wr_src=sa["wr"], rd_dst=sb["rd"], roundtrip=min(sa["wr"], sb["rd"]),
                       launches_src=sum(s["launches"] for s in a["steps"]), launches_dst=sum(s["launches"] for s in b["steps"]),
                       gap_ns=max(0, b["start"] - a["end"]), host=h))
    return {"q": q, "D": D, "P": P, "steps": steps, "segs": segs, "E": E, "SE": SE, "by_ts": by_ts}


def chains_in_tasks(A):
    """Per task: ordered list of steps (same thread)."""
    out = collections.defaultdict(list)
    for s in A["steps"]:
        out[(s["tid"], A["segs"][s["seg"]]["task"])].append(s)
    return out


def ngram_rows(all_A):
    """Sub-op and op n-grams (n=2,3) with their measured costs."""
    G = {}

    def add(level, gram, q, launches, ktime, rt, gap, wr, rd, hosts, kind):
        key = (level, len(gram), " > ".join(gram))
        r = G.setdefault(key, {"level": level, "n": len(gram), "gram": " > ".join(gram), "queries": set(), "instances": 0,
                               "launches": 0, "kernel_us": 0.0, "roundtrip_B": 0, "producer_wr_B": 0, "consumer_rd_B": 0,
                               "host_gap_us": 0.0, "readback_syncs": 0, "cross_thread": 0, "same_thread_instances": 0,
                               "roundtrip_B_same_thread": 0, "host_gap_us_same_thread": 0.0, "kernel_us_same_thread": 0.0,
                               "launches_same_thread": 0, "handoff_gap_us": 0.0})
        r["queries"].add(q); r["instances"] += 1; r["launches"] += launches; r["kernel_us"] += ktime / 1e3
        r["roundtrip_B"] += rt; r["host_gap_us"] += gap / 1e3; r["producer_wr_B"] += wr; r["consumer_rd_B"] += rd
        r["readback_syncs"] += sum(1 for h in hosts if h.get("kind") == "readback+sync")
        r["cross_thread"] += kind
        if kind:
            r["handoff_gap_us"] += gap / 1e3
        if not kind:
            r["same_thread_instances"] += 1; r["roundtrip_B_same_thread"] += rt; r["host_gap_us_same_thread"] += gap / 1e3
            r["kernel_us_same_thread"] += ktime / 1e3; r["launches_same_thread"] += launches

    for A in all_A:
        q = A["q"]
        st = {s["id"]: s for s in A["steps"]}
        nxt = collections.defaultdict(list)
        for e in A["E"]:
            nxt[e["src"]].append(e)
            a, b = st[e["src"]], st[e["dst"]]
            add("sub_op", [a["sub"], b["sub"]], q, a["launches"] + b["launches"], a["ktime"] + b["ktime"], e["roundtrip"],
                e["gap_ns"], e["wr_src"], e["rd_dst"], [e["host"]], e["kind"] != "same-thread")
        for e1 in A["E"]:
            for e2 in nxt[e1["dst"]]:
                a, b, c = st[e1["src"]], st[e1["dst"]], st[e2["dst"]]
                add("sub_op", [a["sub"], b["sub"], c["sub"]], q, a["launches"] + b["launches"] + c["launches"],
                    a["ktime"] + b["ktime"] + c["ktime"], e1["roundtrip"] + e2["roundtrip"], e1["gap_ns"] + e2["gap_ns"],
                    e1["wr_src"], e2["rd_dst"], [e1["host"], e2["host"]], (e1["kind"] != "same-thread") + (e2["kind"] != "same-thread"))
        sg = {g["id"]: g for g in A["segs"]}
        L = lambda g: sum(s["launches"] for s in g["steps"])
        T = lambda g: sum(s["ktime"] for s in g["steps"])
        nx = collections.defaultdict(list)
        for e in A["SE"]:
            nx[e["src"]].append(e)
            a, b = sg[e["src"]], sg[e["dst"]]
            add("operator", [a["op"], b["op"]], q, L(a) + L(b), T(a) + T(b), e["roundtrip"], e["gap_ns"], e["wr_src"], e["rd_dst"],
                [e["host"]], e["kind"] != "same-thread")
        for e1 in A["SE"]:
            for e2 in nx[e1["dst"]]:
                a, b, c = sg[e1["src"]], sg[e1["dst"]], sg[e2["dst"]]
                add("operator", [a["op"], b["op"], c["op"]], q, L(a) + L(b) + L(c), T(a) + T(b) + T(c),
                    e1["roundtrip"] + e2["roundtrip"], e1["gap_ns"] + e2["gap_ns"], e1["wr_src"], e2["rd_dst"],
                    [e1["host"], e2["host"]], (e1["kind"] != "same-thread") + (e2["kind"] != "same-thread"))
    rows = []
    for r in G.values():
        r = dict(r); r["n_queries"] = len(r.pop("queries")); rows.append(r)
    rows.sort(key=lambda r: (r["level"], r["n"], -r["n_queries"], -(r["kernel_us"] + r["host_gap_us_same_thread"])))
    for i, r in enumerate(rows):
        r["rank_in_level_n"] = 1 + sum(1 for x in rows[:i] if x["level"] == r["level"] and x["n"] == r["n"])
    return rows


# ---- candidate chains (a)-(g): patterns over the steps of one task ---------------------------------------------
def match_candidates(A):
    """Returns {cand: [instance dict]}; each instance lists its steps (same thread unless stated)."""
    tasks = chains_in_tasks(A)
    sg = {g["id"]: g for g in A["segs"]}
    out = collections.defaultdict(list)

    def inst(ss, extra=None):
        edges_rt = sum(min(a["wr"], b["rd"]) for a, b in zip(ss, ss[1:]))
        gaps = sum(max(0, b["start"] - a["end"]) for a, b in zip(ss, ss[1:])) + sum(s["inner_gap"] for s in ss)
        d = {"steps": [s["id"] for s in ss], "subs": [s["sub"] for s in ss], "launches": sum(s["launches"] for s in ss),
             "kernel_ns": sum(s["ktime"] for s in ss), "roundtrip_B": edges_rt, "gaps_ns": gaps,
             "inner_launch_gaps": len(ss) - 1 + sum(s["launches"] - 1 for s in ss),
             "readbacks": 0, "first_wr": ss[0]["wr"], "last_wr": ss[-1]["wr"], "rd_total": sum(s["rd"] for s in ss)}
        d.update(extra or {})
        return d

    for key, ss in tasks.items():
        for i, s in enumerate(ss):
            # (a) predicate -> mask -> compaction -> gather  (FILTER), includes multi-step predicates
            if s["sub"] == "mask_compact" and s["op"] == "FILTER":
                j = i - 1
                while j >= 0 and ss[j]["sub"] in PRED | {"expr_ast", "expr_binop", "expr_cast", "offsets_scan"} and ss[j]["op"] in ("FILTER", "PROJECTION"):
                    j -= 1
                pre = ss[j + 1:i]
                post = [ss[i + 1]] if i + 1 < len(ss) and ss[i + 1]["sub"] in GATHER else []
                if pre:
                    out["a_filter_materialization"].append(inst(pre + [s] + post, {"has_gather": bool(post)}))
            # (f) dynamic filter probe: [table predicate] -> membership mask -> compaction -> gather
            if s["sub"] == "dynf_probe_mask":
                j = i - 1
                while j >= 0 and ss[j]["sub"] in PRED | {"expr_binop", "expr_ast"} and ss[j]["op"] == "DYNAMIC_FILTER":
                    j -= 1
                seq = ss[j + 1:i + 1]
                k = i + 1
                if k < len(ss) and ss[k]["sub"] == "mask_compact":
                    seq.append(ss[k]); k += 1
                    if k < len(ss) and ss[k]["sub"] in GATHER:
                        seq.append(ss[k])
                out["f_dynfilter_probe_compact_gather"].append(inst(seq))
            # (b) join probe -> retrieve -> gather
            if s["sub"] in ("join_probe", "join_probe_count", "semijoin_probe"):
                seq = [s]
                if i + 1 < len(ss) and ss[i + 1]["sub"] in ("join_retrieve", "semijoin_retrieve"):
                    seq.append(ss[i + 1])
                    if i + 2 < len(ss) and ss[i + 2]["sub"] in GATHER:
                        seq.append(ss[i + 2])
                if len(seq) > 1:
                    out["b_join_probe_retrieve_gather"].append(inst(seq))
            # (d) sort / top-N -> gather (-> limit is a zero-copy slice in cudf)
            if s["sub"] in ("sort", "topk"):
                seq = [s] + ([ss[i + 1]] if i + 1 < len(ss) and ss[i + 1]["sub"] in GATHER else [])
                if len(seq) > 1:
                    out["d_sort_gather_limit"].append(inst(seq))
            # (e) expression -> aggregate (PROJECTION/expr steps directly feeding GROUP_BY / UNGROUPED_AGG)
            if s["op"] in ("GROUP_BY", "UNGROUPED_AGG") and (i == 0 or ss[i - 1]["op"] not in ("GROUP_BY", "UNGROUPED_AGG")):
                j = i - 1
                while j >= 0 and ss[j]["op"] == "PROJECTION" and ss[j]["sub"].startswith("expr"):
                    j -= 1
                pre = ss[j + 1:i]
                k = i
                while k < len(ss) and ss[k]["op"] == s["op"]:
                    k += 1
                if pre:
                    # expression steps + the first aggregate step that reads them (minmax check or the aggregate)
                    out["e_expression_aggregate"].append(inst(pre + [ss[i]]))
                body = ss[i:k]
                if len(body) > 1 and s["op"] == "GROUP_BY":
                    out["h_groupby_internal"].append(inst(body))
    # (c) group-by -> [projection]* -> sort / top-N. Only when the plan has that edge (MERGE_GROUP_BY/HASH_GROUP_BY ->
    # [PROJECTION]* -> ORDER_BY/TOP_N). Group-by side = the last GROUP_BY segment before the first sort-side segment;
    # sort side = every ORDER/SORT, TOP_N and PROJECTION segment that starts after it (ORDER_BY + SORT_PARTITION +
    # MERGE_SORT, or TOP_N + MERGE_TOP_N, and their casts), in time order (they cross threads at the plan barriers).
    P = A["P"]
    gb_sort = [(a, b) for a, b, _, _ in plan.contracted(P, plan.ZERO | {"CONCAT", "PROJECTION"})
               if P["ops"][a]["type"] in ("MERGE_GROUP_BY", "HASH_GROUP_BY") and P["ops"][b]["type"] in ("ORDER_BY", "TOP_N")]
    if gb_sort:
        sorts = [g for g in A["segs"] if g["op"] in ("ORDER/SORT", "TOP_N")]
        gbs = [g for g in A["segs"] if g["op"] == "GROUP_BY"]
        first_sort = None
        for g in sorted(gbs, key=lambda g: -g["end"]):
            after = [s for s in sorts if s["start"] >= g["end"]]
            if after:
                gb, first_sort = g, min(after, key=lambda s: s["start"]); break
        if first_sort is not None:
            tail = sorted([g for g in A["segs"] if g["start"] >= gb["end"] and g["op"] in ("ORDER/SORT", "TOP_N", "PROJECTION")],
                          key=lambda g: g["start"])
            last_sort = max(i for i, g in enumerate(tail) if g["op"] in ("ORDER/SORT", "TOP_N"))
            tail = tail[:last_sort + 1]
            ss = [gb["steps"][-1]] + [s for g in tail for s in g["steps"]]
            srt = [g for g in tail if g["op"] in ("ORDER/SORT", "TOP_N")]
            out["c_groupby_sort"].append(inst(ss, {"segments": [gb["id"]] + [g["id"] for g in tail],
                                                  "plan_edges": [f"{P['ops'][a]['type']}({a})->{P['ops'][b]['type']}({b})" for a, b in gb_sort],
                                                  "groupby_launches": sum(s["launches"] for s in gb["steps"]),
                                                  "groupby_kernel_ns": sum(s["ktime"] for s in gb["steps"]),
                                                  "sort_launches": sum(s["launches"] for g in srt for s in g["steps"]),
                                                  "sort_kernel_ns": sum(s["ktime"] for g in srt for s in g["steps"]),
                                                  "mid_launches": sum(s["launches"] for g in tail if g["op"] == "PROJECTION" for s in g["steps"]),
                                                  "groupby_out_wr": gb["steps"][-1]["wr"],
                                                  "sort_in_rd": first_sort["steps"][0]["rd"],
                                                  "boundary_gap_ns": max(0, tail[0]["start"] - gb["end"]),
                                                  "threads": len({gb["tid"]} | {g["tid"] for g in tail}),
                                                  "handoff": ["same-thread" if tail[0]["tid"] == gb["tid"] else "cross-thread"]}))
    # (g) partition -> concat : kernels labelled CONCAT
    for g in A["segs"]:
        if g["op"] == "CONCAT":
            out["g_partition_concat"].append(inst(g["steps"]))
    # readbacks inside each instance (host calls between its steps / inside steps)
    st = {s["id"]: s for s in A["steps"]}
    ehost = {(e["src"], e["dst"]): e["host"] for e in A["E"]}
    for c, L in out.items():
        for d in L:
            hs = [ehost.get((a, b), {}) for a, b in zip(d["steps"], d["steps"][1:])] + [h for sid in d["steps"] for h in st[sid]["inner_host"]]
            d["readbacks"] = sum(1 for h in hs if h.get("kind") == "readback+sync")
            d["syncs"] = sum(h.get("syncs", 0) for h in hs)
    return out


CAND_INFO = {  # qualitative columns (from cuDF/Sirius source; see classify.py docstring)
    "a_filter_materialization": dict(interface="bool mask (1 B/row) -> int32 row-index list -> gathered columns",
                                     size_data_dependent="yes: copy_if returns the selected count to the host (sync + D2H) before gather allocates",
                                     streamable="mask->compaction streams; compaction->gather needs the full index list only for allocation (count)",
                                     crosses_barrier="no (one operator, one thread)",
                                     general="yes: apply_boolean_mask(table, mask) is a general operator (predicate eval + compaction + gather)"),
    "b_join_probe_retrieve_gather": dict(interface="hash table (build) -> per-probe-row match slot -> (probe idx, build idx) pairs -> gathered columns",
                                         size_data_dependent="yes: number of matches read back (copy_if count / probe_count total) before gathers allocate",
                                         streamable="probe->retrieve streams per probe row; gather needs the pair list",
                                         crosses_barrier="no inside the probe; the build side crosses a pipeline barrier (hash table hand-off)",
                                         general="yes: hash-join probe + gather is the general inner/semi join"),
    "c_groupby_sort": dict(interface="aggregated table (groups x columns) -> sort keys -> permutation -> gathered rows",
                           size_data_dependent="number of groups known only after the merge group-by (host reads it)",
                           streamable="no: sort needs all groups; group-by output is complete only after the merge barrier",
                           crosses_barrier="MERGE_GROUP_BY -> ORDER_BY/TOP_N is in one pipeline (same task); HASH_GROUP_BY -> MERGE crosses a FULL barrier",
                           general="yes as 'run group-by, then sort on its output buffer'; fusing agg+sort into one kernel would be query-specific"),
    "d_sort_gather_limit": dict(interface="permutation (int32 per row) -> gathered columns; LIMIT is a zero-copy slice",
                                size_data_dependent="no (permutation has the input size; top-N size known)",
                                streamable="gather of row i needs perm[i] only, but sort must finish first",
                                crosses_barrier="no", general="yes: sort -> gather(permutation) is general"),
    "e_expression_aggregate": dict(interface="computed column(s) (row-aligned) -> aggregation input",
                                   size_data_dependent="no (expression output = input row count)",
                                   streamable="yes, row by row (cuDF materialises it; an AST-in-aggregate would be fusion)",
                                   crosses_barrier="no (same pipeline)",
                                   general="chaining yes; evaluating the expression inside the aggregate kernel is fusion (rule)"),
    "f_dynfilter_probe_compact_gather": dict(interface="key set (cuco set / bloom) -> bool mask -> index list -> gathered columns",
                                             size_data_dependent="yes: selected count read back before gather",
                                             streamable="probe->mask->compaction streams",
                                             crosses_barrier="build->probe crosses threads (filter published by the join build); probe->compact->gather does not",
                                             general="yes: semi-join filter (membership probe) + compaction is general"),
    "h_groupby_internal": dict(interface="hash set of keys -> slot per row (mapping) -> distinct-key index list -> aggregates per slot -> gathered keys",
                               size_data_dependent="yes: number of groups (extracted keys) is read back before the key gather / output allocation",
                               streamable="insert/aggregate stream over rows; key extraction needs the finished table",
                               crosses_barrier="no (one operator, one thread)",
                               general="yes: it is cudf::groupby::aggregate itself (general sub-operators)"),
    "g_partition_concat": dict(interface="list of batches -> one table", size_data_dependent="no (sizes known on host)",
                               streamable="yes (copies)", crosses_barrier="yes (PARTIAL barrier between PARTITION and CONCAT pipelines)",
                               general="yes, but PARTITION launches no kernels on 1 GPU; CONCAT only when >1 batch"),
}


def main():
    qs = list(range(2, 23))
    all_A = []
    place_rows, rt_rows, cand_rows, ub_rows, gs_rows = [], [], [], [], []
    summary = json.load(open(f"{extract.RES}/summary/summary_data.json"))
    S = {r["q"]: r for r in summary}
    cand_tot = collections.defaultdict(lambda: collections.defaultdict(float))
    cand_q = collections.defaultdict(set)
    for q in qs:
        A = analyse(q)
        all_A.append(A)
        K = A["D"]["kernels"]
        pc = collections.Counter(k["placed"] for k in K)
        nsk = sum(k["dur"] for k in K)
        place_rows.append({"q": q, "kernels": len(K), "by_name": pc["name"], "by_context": pc["context"], "unplaced": pc["unplaced"],
                           "steps": len(A["steps"]), "segments": len(A["segs"]), "tasks": len({g["task"] for g in A["segs"]}),
                           "threads": len(A["by_ts"]),
                           "seg_edges_same_thread": sum(e["kind"] == "same-thread" for e in A["SE"]),
                           "seg_edges_cross_thread": sum(e["kind"] == "cross-thread" for e in A["SE"]),
                           "seg_edges_new_task_same_thread": sum(e["kind"] == "same-thread-new-task" for e in A["SE"]),
                           "segments_without_in_or_out_edge": sum(1 for g in A["segs"] if not any(e["src"] == g["id"] or e["dst"] == g["id"] for e in A["SE"])),
                           "ncu_matched": A["D"]["meta"]["ncu_matched"], "ncu_exact_grid": A["D"]["meta"]["ncu_matched_exact_grid"]})
        # round-trip bytes per query
        same = [e for e in A["E"] if e["kind"] == "same-thread"]
        rt_rows.append({"q": q, "kernels": len(K), "nsys_kernel_us": nsk / 1e3, "engine_ms": None, "gpu_busy_ms": S[q]["gpu_busy_ms"],
                        "warm_ms": S[q]["warm_ms"], "base_table_pinned_B": int(S[q]["pinned_mb"] * 1e6),
                        "all_kernels_dram_rd_B": sum(k["rd"] for k in K), "all_kernels_sm_store_B": sum(k["st"] for k in K),
                        "all_kernels_atomic_B": sum(k["wr"] - k["st"] for k in K), "all_kernels_dram_wr_B": sum(k["dram_wr"] for k in K),
                        "step_edges_same_thread": len(same),
                        "roundtrip_B_same_thread": sum(e["roundtrip"] for e in same),
                        "roundtrip_B_intra_operator": sum(e["roundtrip"] for e in same if e["intra_op"]),
                        "roundtrip_B_inter_operator": sum(e["roundtrip"] for e in same if not e["intra_op"]),
                        "roundtrip_B_cross_thread": sum(e["roundtrip"] for e in A["E"] if e["kind"] != "same-thread"),
                        "host_gap_us_same_thread_edges": sum(e["gap_ns"] for e in same) / 1e3,
                        "readback_edges": sum(e["host"].get("kind") == "readback+sync" for e in same)})
        r = rt_rows[-1]
        r["roundtrip_over_base"] = r["roundtrip_B_same_thread"] / r["base_table_pinned_B"]
        it = json.load(open(f"{extract.RES}/q{q}/nsys_iteration_breakdown.json"))
        r["engine_ms"] = [x for x in it if x["iter"] == extract.ITER][0]["engine_ms"]
        r["nsys_iter5_gpu_busy_ms"] = [x for x in it if x["iter"] == extract.ITER][0]["gpu_busy_ms"]
        # candidates
        C = match_candidates(A)
        ub = {"q": q}
        for c, L in C.items():
            cand_q[c].add(q)
            t = cand_tot[c]
            t["instances"] += len(L); t["launches"] += sum(d["launches"] for d in L); t["kernel_us"] += sum(d["kernel_ns"] for d in L) / 1e3
            t["roundtrip_B"] += sum(d["roundtrip_B"] for d in L); t["gaps_us"] += sum(d["gaps_ns"] for d in L) / 1e3
            t["readbacks"] += sum(d["readbacks"] for d in L); t["syncs"] += sum(d["syncs"] for d in L)
            t["inner_launch_gaps"] += sum(d["inner_launch_gaps"] for d in L)
            t["max_instance_rt_B"] = max(t["max_instance_rt_B"], max((d["roundtrip_B"] for d in L), default=0))
        # modeled upper bound per query over the top general chains
        TOP = ["a_filter_materialization", "b_join_probe_retrieve_gather", "f_dynfilter_probe_compact_gather",
               "d_sort_gather_limit", "c_groupby_sort", "e_expression_aggregate", "h_groupby_internal"]
        seen_steps = set()
        rtb = gaps = launches_saved = reader_kt = 0
        ivs = []
        st = {s["id"]: s for s in A["steps"]}
        for c in TOP:
            for d in C.get(c, []):
                ss = d["steps"]
                pairs = [(x, y) for x, y in zip(ss, ss[1:]) if (x, y) not in seen_steps and st[x]["tid"] == st[y]["tid"]]
                for x, y in pairs:  # same-thread producer -> consumer pairs inside the chain
                    seen_steps.add((x, y))
                    rtb += min(st[x]["wr"], st[y]["rd"])
                    gaps += max(0, st[y]["start"] - st[x]["end"]); ivs.append((st[x]["end"], st[y]["start"]))
                    reader_kt += st[y]["ktime"]
                for sid in ss:
                    if ("inner", sid) not in seen_steps:
                        seen_steps.add(("inner", sid)); gaps += st[sid]["inner_gap"]; launches_saved += st[sid]["launches"] - 1
                        ks = st[sid]["k"]
                        ivs += [(k1["end"], k2["start"]) for k1, k2 in zip(ks, ks[1:])]
                launches_saved += len(pairs)
        ub.update({"chains_roundtrip_B_ncu": rtb, "chains_sm_traffic_avoided_B_ncu": 2 * rtb,
                   "modeled_dm_time_us_at_672GBs": 2 * rtb / BW * 1e6,
                   "dm_time_upper_us_nsys_reader_kernels": reader_kt / 1e3,
                   "chains_inner_gaps_us_nsys_sum_over_threads": gaps / 1e3,
                   "chains_inner_gaps_us_nsys_wallclock_union": union_ns(ivs) / 1e3,
                   "launches_inside_chains": launches_saved,
                   "modeled_dm_plus_gaps_us_wallclock": 2 * rtb / BW * 1e6 + union_ns(ivs) / 1e3,
                   "engine_ms_nsys_iter5": r["engine_ms"], "gpu_busy_ms_nsys_iter5": r["nsys_iter5_gpu_busy_ms"],
                   "nsys_kernel_us": nsk / 1e3, "all_kernels_dram_rd_B_ncu": r["all_kernels_dram_rd_B"],
                   "base_table_pinned_B": r["base_table_pinned_B"]})
        ub["dm_share_of_engine_pct"] = 100 * ub["modeled_dm_time_us_at_672GBs"] / (ub["engine_ms_nsys_iter5"] * 1e3)
        ub["dm_plus_gaps_share_of_engine_pct"] = 100 * ub["modeled_dm_plus_gaps_us_wallclock"] / (ub["engine_ms_nsys_iter5"] * 1e3)
        ub["traffic_share_of_all_dram_rd_pct"] = 100 * rtb / max(1, r["all_kernels_dram_rd_B"])
        ub_rows.append(ub)
        # group-by -> sort detail
        for d in C.get("c_groupby_sort", []):
            gs_rows.append({"q": q, "rows_into_sort_duckdb": ROWS[q]["rows_into_final_sort"], "result_rows": ROWS[q]["result_rows"],
                            "subs": " > ".join(d["subs"]), "groupby_launches": d["groupby_launches"],
                            "groupby_kernel_us_nsys": d["groupby_kernel_ns"] / 1e3, "mid_projection_launches": d["mid_launches"],
                            "sort_launches": d["sort_launches"], "sort_kernel_us_nsys": d["sort_kernel_ns"] / 1e3,
                            "groupby_output_wr_B_ncu": d["groupby_out_wr"], "sort_first_step_dram_rd_B_ncu": d["sort_in_rd"],
                            "chain_roundtrip_B_ncu": d["roundtrip_B"], "chain_launches": d["launches"],
                            "chain_kernel_us_nsys": d["kernel_ns"] / 1e3, "chain_gaps_us_nsys": d["gaps_ns"] / 1e3,
                            "groupby_to_next_gap_us": d["boundary_gap_ns"] / 1e3, "handoff": ",".join(d["handoff"]),
                            "readbacks_in_chain": d["readbacks"], "syncs_in_chain": d["syncs"], "threads": d["threads"],
                            "plan_edges": " ".join(d["plan_edges"])})
        # dataflow json
        segs = [{"id": g["id"], "thread": g["tid"] % 10**6, "op": g["op"], "task": g["task"], "plan_candidates": g["plan_candidates"],
                 "plan_id": g["plan_id"], "start_us": (g["start"] - K[0]["start"]) / 1e3, "end_us": (g["end"] - K[0]["start"]) / 1e3,
                 "steps": [{"id": s["id"], "sub": s["sub"], "launches": s["launches"], "kernel_us_nsys": s["ktime"] / 1e3,
                            "wr_B_ncu": s["wr"], "dram_rd_B_ncu": s["rd"], "dram_wr_B_ncu": s["dram_wr"], "sm_ld_B_ncu": s["ld"],
                            "max_grid": s["grid"], "placed_by": dict(s["placed"]), "inner_gap_us": s["inner_gap"] / 1e3,
                            "inner_host": [h["kind"] for h in s["inner_host"]],
                            "kernels": [k["i"] for k in s["k"]]} for s in g["steps"]]} for g in A["segs"]]
        json.dump({"q": q, "meta": A["D"]["meta"], "task_gap_us": TASK_GAP_US,
                   "plan_ops": {i: o["type"] for i, o in A["P"]["ops"].items()},
                   "plan_edges_contracted": [list(e) for e in plan.contracted(A["P"])],
                   "nodes_operator_level": segs,
                   "edges_operator_level": [dict(e, gap_us=e["gap_ns"] / 1e3) for e in A["SE"]],
                   "edges_subop_level": [dict(e, gap_us=e["gap_ns"] / 1e3) for e in A["E"]],
                   "notes": "nodes = segments (one operator's kernels on one host thread within one task); steps = sub-operators. "
                            "wr = SM global store+atomic bytes (ncu); dram_rd cold-L2 (ncu); times real-clock (nsys iter 5). "
                            "same-thread edges: medium confidence; cross-thread edges: low confidence (latest plan-compatible producer)."},
                  open(f"{HERE}/dataflow_q{q}.json", "w"), indent=1, default=str)
    # write tables
    W = lambda name, rows: (lambda f: (csv.DictWriter(f, fieldnames=list(rows[0].keys())).writeheader(),
                                       csv.DictWriter(f, fieldnames=list(rows[0].keys())).writerows(rows)))(open(f"{HERE}/{name}", "w", newline=""))
    W("placement.csv", place_rows)
    W("roundtrip_bytes.csv", rt_rows)
    W("upper_bound.csv", ub_rows)
    W("groupby_sort.csv", gs_rows)
    ng = ngram_rows(all_A)
    W("chain_ngrams.csv", ng)
    for c, t in sorted(cand_tot.items()):
        cand_rows.append(dict({"candidate": c, "n_queries": len(cand_q[c]), **{k: round(v, 1) for k, v in t.items()}}, **CAND_INFO.get(c, {})))
    for c in CAND_INFO:
        if c not in cand_tot:
            cand_rows.append(dict({"candidate": c, "n_queries": 0}, **CAND_INFO[c]))
    keys = []
    for r in cand_rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(f"{HERE}/chain_candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(cand_rows)
    return all_A


if __name__ == "__main__":
    main()
