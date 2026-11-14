"""Check that the detailed ncu report(s) hold exactly the expected warm-iteration kernels.

Usage: python3 -I check_slice.py <results_dir>
Compares the multiset of kernel names in each profiles/q*_warm_*.ncu-rep with the slice predicted by the
list pass (warm_kernel_list.json, and the family regex for the *_families_full report). A mismatch means
the -s/-c launch skip was misaligned. Writes ncu_slice_check.json/.txt; exits 1 on mismatch.
Reports made with a -k kernel filter print simplified names (e.g. "NullType" for "cub::NullType"), so the
family report is compared on (function base name, grid, block) instead of the full demangled name.
"""
import collections, csv, glob, io, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kclass import func_base

R = sys.argv[1]
plan = json.load(open(f"{R}/ncu_plan.json")); warm = json.load(open(f"{R}/warm_kernel_list.json"))
NCU = "/usr/local/cuda/bin/ncu"


def report_kernels(rep):
    out = subprocess.run([NCU, "--import", rep, "--page", "raw", "--csv", "--print-units", "base",
                          "--metrics", "gpu__time_duration.sum,launch__grid_size,launch__block_size"],
                         capture_output=True, text=True, check=True).stdout
    rows = list(csv.DictReader(io.StringIO("\n".join(l for l in out.splitlines() if l.startswith('"')))))
    n = lambda v: int(float(v.replace(",", "")))
    return [(r["Kernel Name"], n(r["launch__grid_size"]), n(r["launch__block_size"])) for r in rows[1:]]  # row 0 = units


res = []
for rep in sorted(glob.glob(f"{R}/profiles/*_warm_*.ncu-rep")):
    got = report_kernels(rep)
    exp = warm
    if rep.endswith("_families_full.ncu-rep"):
        rx = re.compile(plan["full_regex"]); exp = [k for k in warm if rx.search(k["func"])]
        key_e = [(k["func"], int(k["grid"]), int(k["block"])) for k in exp]
        key_g = [(func_base(n), g_, b_) for n, g_, b_ in got]
    else:
        key_e = [k["name"] for k in exp]; key_g = [n for n, _, _ in got]
    e, g = collections.Counter(key_e), collections.Counter(key_g)
    # ncu can render one kernel's demangled name differently live (--csv list pass) and from a saved report
    # (seen on Q3: "__uninitialized_fill::functor<int *, int>" vs "cuda_cub::functor<int *, int>", same grid/block).
    # Reconcile only the names that differ, on (function base, grid, block); everything else must match exactly.
    shape_e = collections.Counter((func_base(k["name"]), int(k["grid"]), int(k["block"])) for k in exp if k["name"] in (e - g)) \
        if key_e and isinstance(key_e[0], str) else collections.Counter()
    shape_g = collections.Counter((func_base(n), g_, b_) for n, g_, b_ in got if n in (g - e)) \
        if key_g and isinstance(key_g[0], str) else collections.Counter()
    variants = sum((e - g).values()) if (e != g and shape_e == shape_g and sum(shape_e.values()) == sum((e - g).values())
                                         and sum(shape_g.values()) == sum((g - e).values())) else 0
    res.append({"report": os.path.basename(rep), "n_report": len(got), "n_expected": len(exp),
                "match": e == g or variants > 0, "exact_name_match": e == g, "name_variants_reconciled": variants,
                "missing": sum((e - g).values()), "unexpected": sum((g - e).values()),
                "same_order": key_e == key_g})
json.dump({"reports": res}, open(f"{R}/ncu_slice_check.json", "w"), indent=1)
txt = "\n".join(f"{r['report']}: {r['n_report']} kernels vs {r['n_expected']} expected; multiset match={r['match']} "
                f"(exact names: missing {r['missing']}, unexpected {r['unexpected']}; reconciled on function/grid/block: "
                f"{r['name_variants_reconciled']}); identical launch order={r['same_order']}" for r in res)
open(f"{R}/ncu_slice_check.txt", "w").write(txt + "\n"); print(txt)
sys.exit(0 if res and all(r["match"] for r in res) else 1)
