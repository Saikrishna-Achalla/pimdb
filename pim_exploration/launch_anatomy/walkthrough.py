"""Launch-by-launch walk-through of one task: every kernel with its attribution, plus the host round trips between.

Usage: python -I walkthrough.py <q> <task_idx> [<task_idx> ...]   (writes walkthrough_q<q>.txt)
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import tasks  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
q = int(sys.argv[1])
want = [int(x) for x in sys.argv[2:]]
A = json.load(open(f"{HERE}/launch_attribution.json"))[str(q)]
lk = {}
for key, v in A["instances"].items():
    for x in v["launches"]:
        lk[(x["task"], x["t_launch"])] = (key, x)
T, E = tasks(q)
lines = []
for t in T:
    if t["idx"] not in want:
        continue
    t0 = t["events"][0]["t"]
    lines.append(f"=== q{q} task {t['idx']} thread T{t['thread']} task stream {t['task_stream']} "
                 f"({(t['events'][-1]['tend'] - t0) / 1e3:.0f} us wall)")
    n = rb = 0
    pend = None
    for e in t["events"]:
        rel = (e["t"] - t0) / 1e3
        if e["kind"] == "K":
            n += 1
            key, x = lk[(t["idx"], e["t"])]
            lines.append(f"{rel:8.1f}us K{n:<3d} {e['name'][:34]:34s} grid={e['grid']:<6} {e['dur_ns'] / 1e3:7.1f}us "
                         f"{x['role']:6s} {x['cause']:11s} {key[:34]:34s} {x['call'][:70]}")
        elif e["kind"] in ("D2H", "H2D", "D2D", "MEMSET"):
            lines.append(f"{rel:8.1f}us      {e['kind']:6s} {e.get('bytes')} B ({e['api']})")
            if e["kind"] == "D2H":
                pend = e
        elif e["kind"] == "SYNC":
            tag = ""
            if pend is not None:
                rb += 1
                tag = f"  <- host round trip #{rb}: waits for the {pend.get('bytes')} B readback"
                pend = None
            lines.append(f"{rel:8.1f}us      {e['api']}{tag}")
    lines.append(f"--- {n} launches, {rb} D2H readback round trips")
open(f"{HERE}/walkthrough_q{q}.txt", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
