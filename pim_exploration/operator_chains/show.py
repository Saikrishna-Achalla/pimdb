"""Print a query's operator-level dataflow (segments, tasks, edges) from dataflow_q<N>.json."""
import json, os, sys
d = json.load(open(f"{os.path.dirname(os.path.abspath(__file__))}/dataflow_q{sys.argv[1]}.json"))
for g in d["nodes_operator_level"]:
    subs = " ".join(f"{s['sub']}x{s['launches']}" for s in g["steps"])
    wr = g["steps"][-1]["wr_B_ncu"]
    print(f"seg{g['id']:3d} t{g['thread']} task{g['task']:3d} {g['start_us']:8.1f}-{g['end_us']:8.1f} {g['op']:16s} plan={g['plan_id'] if g['plan_id'] is not None else g['plan_candidates']}  out_wr={wr/1e3:.1f}KB  {subs}")
for e in d["edges_operator_level"]:
    print(f"  seg{e['src']}->seg{e['dst']} {e['src_op']}->{e['dst_op']} {e['kind']} gap={e['gap_us']:.1f}us rt={e['roundtrip']/1e3:.1f}KB host={e['host']['kind']}")
