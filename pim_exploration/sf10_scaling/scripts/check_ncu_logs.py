"""Residency log checks for the ncu runs whose kernels/metrics are reported (list passes and detail passes).

Usage: python3 -I check_ncu_logs.py <results_dir> <list|detail> <tables...>
Runs siriuslog.check_log on every traces/sirius_log_ncu_<kind>_* directory (one directory per ncu run:
list_x3/x4/x5 with 3/4/5 iterations; detail_full / detail_light / detail_families with 5 iterations) and writes
ncu_log_checks_<kind>.{json,txt}. Exit 1 if any check fails or an expected directory is missing.
"""
import glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog

R, KIND, TABLES = sys.argv[1], sys.argv[2], sys.argv[3:]
dirs = sorted(d for d in glob.glob(f"{R}/traces/sirius_log_ncu_{KIND}_*") if os.path.isdir(d))
res, ok = {}, bool(dirs)
for d in dirs:
    tag = os.path.basename(d).replace("sirius_log_", "")
    m = re.search(r"_x(\d+)$", d)
    lines, procs = siriuslog.read_run(d)
    c, _ = siriuslog.check_log(tag, lines, TABLES, int(m.group(1)) if m else 5)
    res[tag] = {"processes_in_dir": procs, "log_files": [os.path.basename(f) for f in siriuslog.log_files(d)], "checks": c}
    ok &= all(v["ok"] for v in c.values())
json.dump({"ok": ok, "runs": res}, open(f"{R}/ncu_log_checks_{KIND}.json", "w"), indent=1)
txt = "\n".join(f"[{'PASS' if v['ok'] else 'FAIL'}] {k}: {v['detail']}" for r in res.values() for k, v in r["checks"].items())
txt = (txt or f"no traces/sirius_log_ncu_{KIND}_* directories found") + f"\nOVERALL ncu {KIND} logs: {'PASS' if ok else 'FAIL'}\n"
open(f"{R}/ncu_log_checks_{KIND}.txt", "w").write(txt); print(txt)
sys.exit(0 if ok else 1)
