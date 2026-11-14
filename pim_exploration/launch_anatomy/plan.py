"""Parse the Sirius 'Pipeline Overview' of query_plan.txt.

plan(q) -> list of pipelines {pid, ops:[(type,id)], inputs:[(pid, op_type, op_id, port, barrier)], deps:[pid],
                              out:(type, port, barrier) or None}
"""
import re

RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"


def plan(q):
    P, cur = [], None
    on = False
    for l in open(f"{RES}/q{q}/query_plan.txt", errors="replace"):
        if "=== Pipeline Overview ===" in l:
            on = True
            continue
        if "=== Query Plan DAG ===" in l:
            break
        if not on:
            continue
        m = re.match(r"\s*Pipeline #(\d+): (.*)$", l)
        if m:
            ops = [(t, int(i)) for t, i in re.findall(r"([A-Z_]+) \(id=(\d+)\)", m.group(2))]
            cur = dict(pid=int(m.group(1)), ops=ops, inputs=[], deps=[], out=None)
            P.append(cur)
            continue
        m = re.match(r"\s*Input: <- Pipeline #(\d+) \[on: ([A-Z_]+) \(id=(\d+)\), port: (\w+), barrier: (\w+)\]", l)
        if m and cur:
            cur["inputs"].append((int(m.group(1)), m.group(2), int(m.group(3)), m.group(4), m.group(5)))
            continue
        m = re.match(r"\s*Dependencies: (.*)$", l)
        if m and cur:
            cur["deps"] = [int(x) for x in re.findall(r"#(\d+)", m.group(1))]
            continue
        m = re.match(r"\s*Output: -> ([A-Z_]+) \[port: (\w+), barrier: (\w+)\]", l)
        if m and cur:
            cur["out"] = (m.group(1), m.group(2), m.group(3))
    return P


if __name__ == "__main__":
    import sys
    for q in map(int, sys.argv[1:]):
        print(f"== q{q}")
        for p in plan(q):
            print(f"  #{p['pid']:2d} {' -> '.join(f'{t}({i})' for t, i in p['ops'])}"
                  f"{'  => ' + p['out'][0] + ':' + p['out'][1] if p['out'] else ''}")
