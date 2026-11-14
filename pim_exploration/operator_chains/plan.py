"""Parse the Sirius pipeline plan (query_plan.txt) into operator instances and dataflow edges.

parse(q) -> {"ops": {id: {"id", "type", "pipeline"}}, "edges": [(src_id, dst_id, kind, port, barrier)],
            "pipelines": {k: [ids]}}
kind = "in_pipeline" (consecutive operators of one pipeline) or "pipeline_out" (the last operator of a pipeline
feeding the operator of a downstream pipeline, through a barrier).
contracted(q) -> edges between operators that can launch kernels, after removing zero-kernel operators
(GPU_SCAN, PARTITION, CTE, RESULT_COLLECTOR, SORT_SAMPLE) by path contraction. CONCAT is kept: it launches
kernels only when it has more than one batch to concatenate.
CAT maps a plan operator type to the level-1 labels of classify.py that its kernels can carry.
"""
import re

RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
CAT = {
    "FILTER": {"FILTER"}, "DYNAMIC_FILTER": {"DYNAMIC_FILTER", "FILTER"}, "PROJECTION": {"PROJECTION"},
    "HASH_JOIN": {"HASH_JOIN_BUILD", "HASH_JOIN_PROBE"}, "NESTED_LOOP_JOIN": {"HASH_JOIN_PROBE"},
    "DENSE_COUNT_JOIN": {"DENSE_COUNT_JOIN"},
    "HASH_GROUP_BY": {"GROUP_BY"}, "MERGE_GROUP_BY": {"GROUP_BY"},
    "UNGROUPED_AGGREGATE": {"UNGROUPED_AGG"}, "MERGE_AGGREGATE": {"UNGROUPED_AGG"},
    "TOP_N": {"TOP_N", "ORDER/SORT"}, "MERGE_TOP_N": {"TOP_N", "ORDER/SORT"},
    "ORDER_BY": {"ORDER/SORT"}, "SORT_PARTITION": {"ORDER/SORT"}, "MERGE_SORT": {"ORDER/SORT"},
    "BUILD_FILTER": {"DYNF_BUILD"}, "CONCAT": {"CONCAT"},
    "GPU_SCAN": {"FILTER"},  # scan-level table filters evaluated right after the scan
}
ZERO = {"PARTITION", "CTE", "RESULT_COLLECTOR", "SORT_SAMPLE"}


def parse(q, path=None):
    txt = open(path or f"{RES}/q{q}/query_plan.txt").read()
    txt = txt.split("=== Query Plan DAG ===")[0]
    ops, edges, pipes, cur = {}, [], {}, None
    for l in txt.splitlines():
        m = re.match(r"Pipeline #(\d+): (.*)", l)
        if m:
            cur = int(m.group(1))
            ids = []
            for t, i in re.findall(r"([A-Z_]+) \(id=(\d+)\)", m.group(2)):
                ops[int(i)] = {"id": int(i), "type": t, "pipeline": cur}
                ids.append(int(i))
            pipes[cur] = ids
            for a, b in zip(ids, ids[1:]):
                edges.append((a, b, "in_pipeline", None, None))
            continue
        m = re.match(r"\s+Input: <- Pipeline #(\d+) \[on: ([A-Z_]+) \(id=(\d+)\), port: (\w+), barrier: (\w+)\]", l)
        if m and cur is not None:
            src_pipe, dst = int(m.group(1)), int(m.group(3))
            edges.append((pipes[src_pipe][-1], dst, "pipeline_out", m.group(4), m.group(5)))
    return {"ops": ops, "edges": edges, "pipelines": pipes}


def contracted(P, zero=None):
    zero = ZERO if zero is None else zero
    ops = P["ops"]
    succ = {}
    for a, b, kind, port, bar in P["edges"]:
        succ.setdefault(a, []).append((b, kind, port, bar))
    out = set()

    def walk(a, b, crossed, port, seen):
        if ops[b]["type"] in zero or ops[b]["type"] == "GPU_SCAN":
            for c, kind, p2, bar in succ.get(b, []):
                if c not in seen:
                    walk(a, c, crossed or kind == "pipeline_out", p2 or port, seen | {c})
        else:
            out.add((a, b, crossed, port))

    for a in ops:
        if ops[a]["type"] in zero:
            continue
        for b, kind, port, bar in succ.get(a, []):
            walk(a, b, kind == "pipeline_out", port, {a, b})
    return sorted(out)


def allowed_pairs(P):
    """Level-1 label pairs (x, y) that a contracted plan edge or a single operator can produce."""
    ok = set()
    for t in {o["type"] for o in P["ops"].values()}:
        for x in CAT.get(t, ()):
            for y in CAT.get(t, ()):
                ok.add((x, y))
    # CONCAT launches kernels only with >1 batch and a PROJECTION that only selects columns launches none: also
    # allow the pairs that skip them
    for a, b, crossed, port in contracted(P) + contracted(P, ZERO | {"CONCAT"}) + contracted(P, ZERO | {"CONCAT", "PROJECTION"}):
        ta, tb = P["ops"][a]["type"], P["ops"][b]["type"]
        for x in CAT.get(ta, ()):
            for y in CAT.get(tb, ()):
                ok.add((x, y))
        # the join's build input also feeds the dynamic-filter key set; build precedes probe inside one join
        if tb == "HASH_JOIN" and port == "build":
            for x in CAT.get(ta, ()):
                ok.add((x, "DYNF_BUILD"))
    return ok


if __name__ == "__main__":
    import sys
    P = parse(int(sys.argv[1]))
    for e in contracted(P):
        print(P["ops"][e[0]]["type"], e[0], "->", P["ops"][e[1]]["type"], e[1], "crossed" if e[2] else "", e[3] or "")
