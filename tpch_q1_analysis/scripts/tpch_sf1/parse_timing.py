"""Parse a Sirius timing run + DuckDB-CPU run (output of gen_sql.py scripts, .mode csv, .timer on).

Usage: python3 -I parse_timing.py <gpu_run.txt> <cpu_run.txt> <sirius_log_dir> <warmup> <out_dir>
Writes <out_dir>/timing.json, timing_summary.txt, result.csv, query_plan.txt.
Exit 2 (after writing everything) if the GPU result differs from DuckDB-CPU or between GPU iterations.
Iterations 1..warmup are warmup (iteration 1 = first/cold query); the rest are timed.

Result comparison (compare()): rows are parsed as CSV; numeric fields are compared with relative tolerance REL_TOL
(DOUBLE outputs such as averages and ratios may differ in the last bits between engines / thread interleavings).
First in order; if that fails, as multisets (ORDER BY ties may be emitted in either order). Reported: mode used
(exact / ordered-with-tolerance / multiset-with-tolerance / MISMATCH) and the max relative numeric difference.
Known limit: ties at a LIMIT boundary can legitimately select different rows; that shows up as MISMATCH and must be
inspected by hand (the rows involved are printed).

Sirius-log split (1 ms stamps): planning = SQL QueryBegin -> `QueryBegin: transparent_execution`; engine = that ->
`QueryEnd`; gap_to_next_statement = `QueryEnd` -> next statement's QueryBegin (result hand-off to the CLI, printing,
parsing the next statement; there are n-1 such gaps, none after the last iteration). Whether Sirius's QueryEnd (DuckDB
ClientContextState::QueryEnd hook) precedes the CLI's result fetch is not verified.
"""
import csv, io, json, math, os, re, statistics, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog

gpu_txt, cpu_txt, logdir, WARM, OUT = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
RT = re.compile(r"^Run Time \(s\): real ([\d.]+)")
REL_TOL = float(os.environ.get("RESULT_REL_TOL", "1e-9"))


def parse(path):
    its, cur = [], None
    for line in open(path, errors="replace").read().splitlines():
        if line.startswith("__ITER__"):
            cur = {"rows": [], "ms": None}; its.append(cur); continue
        if cur is None:
            continue
        m = RT.match(line)
        if m:
            cur["ms"] = float(m.group(1)) * 1e3
        elif cur["ms"] is None:
            cur["rows"].append(line)
    return its


def stats(ms):
    return dict(median_ms=round(statistics.median(ms), 3), min_ms=min(ms), max_ms=max(ms),
                mean_ms=round(statistics.mean(ms), 3), stdev_ms=round(statistics.pstdev(ms), 3))


def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except ValueError:
        return None


def row_diff(a, b):
    """max relative difference of two CSV rows, or None if a non-numeric field differs / lengths differ"""
    if len(a) != len(b):
        return None
    worst = 0.0
    for x, y in zip(a, b):
        if x == y:
            continue
        fx, fy = fnum(x), fnum(y)
        if fx is None or fy is None:
            return None
        worst = max(worst, abs(fx - fy) / max(abs(fx), abs(fy), 1e-300))
    return worst


def compare(ra, rb):
    """-> (mode, max_rel_diff, detail)"""
    if ra == rb:
        return "exact", 0.0, ""
    A, B = [list(csv.reader([r]))[0] if r else [] for r in ra], [list(csv.reader([r]))[0] if r else [] for r in rb]
    if len(A) != len(B):
        return "MISMATCH", None, f"row counts {len(A)} vs {len(B)}"
    if A[:1] != B[:1]:
        return "MISMATCH", None, f"headers differ: {A[:1]} vs {B[:1]}"
    ds = [row_diff(x, y) for x, y in zip(A, B)]
    if all(d is not None and d <= REL_TOL for d in ds):
        return "ordered-with-tolerance", max(ds), ""
    # multiset: greedy match each row to an unused row within tolerance (rows are few at TPC-H result sizes)
    used, worst, bad = set(), 0.0, []
    for x in A[1:]:
        best = None
        for j, y in enumerate(B[1:]):
            if j in used:
                continue
            d = row_diff(x, y)
            if d is not None and d <= REL_TOL and (best is None or d < best[1]):
                best = (j, d)
                if d == 0:
                    break
        if best is None:
            bad.append(",".join(x))
        else:
            used.add(best[0]); worst = max(worst, best[1])
    if not bad:
        return "multiset-with-tolerance", worst, "same rows, different order (ORDER BY ties)"
    return "MISMATCH", None, f"{len(bad)} rows without a match within rel {REL_TOL}, e.g. {bad[:3]}"


g, c = parse(gpu_txt), parse(cpu_txt)
if not g or any(i["ms"] is None for i in g):
    sys.exit(f"ERROR: GPU run incomplete ({len(g)} iterations, some without a Run Time line)")
res = [i["rows"] for i in g]
T = {"iterations": len(g), "warmup": WARM, "first_ms": g[0]["ms"],
     "warmup_ms": [i["ms"] for i in g[:WARM]], "timed_ms": [i["ms"] for i in g[WARM:]]}
T.update(stats(T["timed_ms"]))
it_cmp = [compare(res[0], r) for r in res[1:]]
T["iteration_compare_modes"] = sorted({m for m, _, _ in it_cmp}) or ["exact"]
T["results_identical"] = all(m != "MISMATCH" for m, _, _ in it_cmp)
T["results_bitwise_identical"] = all(m == "exact" for m, _, _ in it_cmp)
T["n_iterations_with_result"] = len(res)
T["result_rows"] = max(0, len(res[0]) - 1)  # minus CSV header
T["result_bytes"] = sum(len(r) + 1 for r in res[0])
cm = [i["ms"] for i in c if i["ms"] is not None]
T["cpu"] = {"iterations": len(cm), "first_ms": cm[0] if cm else None, "timed_ms": cm[WARM:]}
if cm[WARM:]:
    T["cpu"].update(stats(cm[WARM:]))
mode, diff, detail = compare(c[-1]["rows"], res[0]) if c else ("MISMATCH", None, "no DuckDB-CPU result")
T["gpu_vs_cpu"] = {"mode": mode, "max_rel_diff": diff, "rel_tol": REL_TOL, "detail": detail}
T["gpu_equals_cpu"] = mode != "MISMATCH"

# Sirius log windows
L, nproc = siriuslog.read_run(logdir)
begins, tbeg, ends = [], [], []
for l in L:
    sql = siriuslog.sql_of(l)
    if sql is not None:
        if not sql.lower().startswith(siriuslog.DDL):
            begins.append(siriuslog.ts_ms(l))
    elif "QueryBegin: transparent_execution" in l:
        tbeg.append(siriuslog.ts_ms(l))
    elif l.endswith("QueryEnd") and "sirius_context" in l and tbeg and len(ends) < len(tbeg):
        ends.append(siriuslog.ts_ms(l))
if len(begins) == len(tbeg) == len(ends) == len(g):
    T["log_planning_ms"] = [b - a for a, b in zip(begins, tbeg)][WARM:]
    T["log_engine_ms"] = [b - a for a, b in zip(tbeg, ends)][WARM:]
    T["log_gap_to_next_statement_ms"] = [begins[i + 1] - ends[i] for i in range(len(g) - 1)][WARM:]
    T["log_gap_note"] = f"{len(T['log_gap_to_next_statement_ms'])} gaps for {len(T['timed_ms'])} timed iterations (none after the last)"
    T["log_split_median_ms"] = {k: statistics.median(T[f"log_{k}_ms"]) for k in ("planning", "engine", "gap_to_next_statement")
                                if T[f"log_{k}_ms"]}
else:
    T["log_split_note"] = f"log windows not aligned: {len(begins)} begins, {len(tbeg)} transparent, {len(ends)} ends, {len(g)} iterations"

json.dump(T, open(f"{OUT}/timing.json", "w"), indent=1)
open(f"{OUT}/result.csv", "w").write("\n".join(res[0]) + "\n")

plan, on = [], False
for l in L:
    if "Query Plan:" in l:
        on = True; plan.append(l); continue
    if on:
        if l.startswith("[20"):
            break
        plan.append(l)
open(f"{OUT}/query_plan.txt", "w").write("\n".join(plan) + "\n")

with open(f"{OUT}/timing_summary.txt", "w") as f:
    f.write(f"Sirius (pinned, GPU): {len(g)} iterations, first {T['first_ms']:.1f} ms, warmup={WARM}, timed={len(T['timed_ms'])}\n")
    f.write(f"  warm median {T['median_ms']:.1f} ms  min {T['min_ms']:.1f}  max {T['max_ms']:.1f}  stdev {T['stdev_ms']:.2f}\n")
    f.write("  timed: " + " ".join(f"{x:.0f}" for x in T["timed_ms"]) + "\n")
    if "log_split_median_ms" in T:
        f.write("  Sirius log split (median, 1 ms resolution): " + ", ".join(f"{k} {v:.0f} ms" for k, v in T["log_split_median_ms"].items())
                + f" ({T['log_gap_note']})\n")
    if T["cpu"].get("median_ms"):
        f.write(f"DuckDB CPU: first {T['cpu']['first_ms']:.1f} ms, warm median {T['cpu']['median_ms']:.1f} ms (min {T['cpu']['min_ms']:.1f}, max {T['cpu']['max_ms']:.1f})\n")
    f.write(f"result: {T['result_rows']} rows; consistent across {len(res)} GPU iterations: {T['results_identical']} "
            f"(modes {T['iteration_compare_modes']}); vs DuckDB CPU: {mode} (max rel diff {diff}, tol {REL_TOL}) {detail}\n")
print(open(f"{OUT}/timing_summary.txt").read())
if not (T["results_identical"] and T["gpu_equals_cpu"]):
    print(f"ERROR: result check failed: GPU iterations consistent={T['results_identical']}, GPU vs DuckDB-CPU {mode}: {detail}", file=sys.stderr)
    sys.exit(2)
