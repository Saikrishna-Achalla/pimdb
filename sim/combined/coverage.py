"""Coverage of the bank-level DB unit (sim/aim_pim/isr_spec.json) across the 21 SF1 queries Q2-Q22.

Run:  /home/sai/cs254_project/tpch_q1_analysis/venv/bin/python -I sim/combined/coverage.py
Reads (read-only): pim_exploration/kernel_fit/{launches_all,kernel_families}.csv (one row per warm-iteration launch,
nsys real-clock duration), pim_exploration/operator_chains/groupby_sort.csv (group counts reaching the sort),
tpch_q1_analysis/analysis/results/summary/summary_data.json (SF1 warm wall and GPU busy).
Writes: coverage.csv (per query + ALL), coverage_families.csv (classification of every family / kernel sub-type).

Classes: E = executable by the bank-level unit as specified; N = not executable; B = bookkeeping (tiny setup/finalize
launches; removable by software, PIM-irrelevant). Kernel time is real-clock nsys (measured); the classification and
the Amdahl bounds are modeled (speedup -> infinity on E; planning, N and B stay).
"""
import collections, csv, json, os, re

ROOT = "/home/sai/cs254_project"
OUT = os.path.join(ROOT, "sim/combined")
KF = os.path.join(ROOT, "pim_exploration/kernel_fit")
L = list(csv.DictReader(open(f"{KF}/launches_all.csv")))
FAM = {r["family"]: r for r in csv.DictReader(open(f"{KF}/kernel_families.csv"))}
SUM = {d["q"]: d for d in json.load(open(os.path.join(ROOT, "tpch_q1_analysis/analysis/results/summary/summary_data.json")))}
GBS = {int(r["q"]): r for r in csv.DictReader(open(os.path.join(ROOT, "pim_exploration/operator_chains/groupby_sort.csv"), encoding="utf-8-sig"))}

# ---- small-group decision (per query). The unit's GAGG has 8 group accumulators and needs the key mapped to 0..7 by
# compares (no hash table). A query's hash group-by launches count as executable only if (1) the query has a single
# GROUP BY and (2) its result group count (groupby_sort.csv result_rows = rows reaching ORDER BY, from DuckDB on the
# same data) is <= 8. This selects Q4 (5), Q5 (5), Q7 (4), Q8 (2), Q12 (2), Q22 (7); each of these has exactly one
# GROUP BY in the TPC-H text (Q22's sub-query is an ungrouped AVG). Q13 (inner GROUP BY c_custkey) and Q18
# (GROUP BY l_orderkey) have 42 / 57 result rows but hundreds of thousands of groups inside -> not executable.
# Caveat: in these 6 queries the group-by input is a join output produced by non-executable kernels, so running
# the aggregation in memory presumes that intermediate is written in the row-tile layout (optimistic).
MULTI_GROUPBY = set()
SMALL_GROUP_Q = {q for q, r in GBS.items() if int(r["result_rows"]) <= 8 and q not in MULTI_GROUPBY}
GROUPBY_FAMS = {"groupby: single_pass_shmem_aggs", "for_each: group-by hash aggregate",
                "groupby: mapping_indices (cuco insert+find)", "cub select: hash-table slot extract"}

BOOK = {"cub: tile-state / histogram init", "transform: fill constant / sequence", "for_each: fill / label_segments / misc",
        "cub reduce: final single-tile / assign_min_max", "copy_range (constant fill)", "for_each: cuco hash-table init (fill)",
        "thrust find (is-sorted / first-less)"}
EXEC = {"AST compute_column (no nulls)": "AST expression -> PCMP / EWALU / EWMUL (brief: AST predicates and arithmetic count as executable)",
        "for_each: binop compare": "PCMP (column vs constant/column compare)",
        "transform: cast integral widen": "EWALU widen 4->8 B",
        "for_each: binop add/sub": "EWALU add/sub",
        "cub select: boolean-mask compaction": "COMPACT, bank-local only (global order needs a host prefix)",
        "cub select: gather_mask compaction": "COMPACT, bank-local only",
        "transform: dyn-filter key convert (convert_to_rep)": "element-wise conversion (EWALU)",
        "for_each: dyn-filter membership (needle, small set)": "small-set IN-list = OR-ed PCMP (assumes <= 8 keys; key count not checked)"}
NOTEXEC = {"sort: merge-sort block sort": "sort", "sort: merge-sort merge": "sort", "sort: merge-sort partition": "sort",
           "sort: radix sort": "sort", "sort: top-k": "sort",
           "sirius: fused membership mask (dyn filter)": "hash/bloom membership (large key set)",
           "for_each: dyn-filter membership (cuco set)": "hash membership", "for_each: dyn-filter membership (bloom)": "bloom membership",
           "cuco: bloom-filter add (dyn filter build)": "hash build", "cuco: dyn-filter key-set insert": "hash build",
           "strings: gather chars (char-parallel)": "strings", "strings: gather chars (string-parallel)": "strings",
           "strings: LIKE multi-literal": "strings/LIKE", "transform: string op (substr etc.)": "strings",
           "cub scan: string offsets (gather-strings sizes)": "strings (offsets)", "cub scan: constant-size offsets": "strings/lists offsets",
           "cub scan: long sizes -> offsets": "strings offsets", "cub scan: int exclusive sum (positions)": "global prefix scan (inter-bank carry)",
           "transform: gather fixed-width 1-4 B": "gather", "transform: gather fixed-width 8 B": "gather",
           "transform: gather index-column (indexalator)": "gather", "transform: small scatter (flags/sequence)": "scatter",
           "cuco: hash-join build insert (pair)": "hash build", "cuco: hash-join probe find": "hash probe",
           "cuco: semi-join probe contains": "hash probe", "cuco: semi-join build insert (filtered_join)": "hash build",
           "cub select: hash-join output compaction": "join retrieve", "csr join: probe count": "join", "csr join: retrieve": "join",
           "csr join: build (count)": "join", "csr join: build (fill)": "join", "join: conditional / mixed (AST) join": "join",
           "sirius: dense-count join accumulate/emit": "join", "transform: dictionary encode (cuco set find)": "hash",
           "hyperloglog add_if_shmem": "hash (HLL group-count estimate; planner pre-check)",
           "cub reduce-by-key (sort-based group-by)": "sort-based group-by (large group count)",
           "for_each: binary search (lower_bound)": "binary search (data-dependent addressing)",
           "copy / concatenate": "data movement between tables", "transform: datetime extract": "needs division (not in the ISA)",
           "copy_if_else": "select/blend not in the ISA", "validity bitmask build (valid_if)": "built from gathered/string data"}


def classify(r):
    fam, name, q = r["family"], r["name_short"], int(r["q"])
    if fam in BOOK:
        return "B", "bookkeeping (tiny setup/finalize)"
    if fam in GROUPBY_FAMS:
        if q in SMALL_GROUP_Q:
            return "E", "small-group aggregation: single GROUP BY with <= 8 result groups (Q4/5/7/8/12/22) -> GAGG"
        return "N", "hash group-by with a large group count"
    if fam == "for_each: binop mul/div":
        return ("N", "divide not in the ISA") if "Div" in name else ("E", "EWMUL")
    if fam == "cub reduce: block partial (min/max, sum)":
        if "minmax" in name or "DeviceMax" in name or "DeviceMin" in name:
            return "N", "MIN/MAX not in the ISA (Sirius SUM-widening pre-check; a small extension)"
        return "E", "SUM reduction (+RD_MAC read-out)"
    if fam == "transform: cast decimal/wide (to/from int128, fixed_point)":
        if re.search(r"fixed_point_unary_cast<int, numeric::fixed_point<long", name):
            return "E", "widen 4->8 B"
        return "N", "128-bit / floating-point cast not in the ISA (widen 4->8 B only)"
    if fam == "transform: misc elementwise (not/unique flag/other)":
        return ("E", "mask NOT") if "DeviceNot" in name else ("N", "adjacent-element / list op")
    if fam == "cub select: other":
        return ("E", "mask compaction (bank-local)") if "bool *" in name else ("N", "pair/zip select")
    if fam in EXEC:
        return "E", EXEC[fam]
    if fam in NOTEXEC:
        return "N", NOTEXEC[fam]
    raise SystemExit(f"unclassified family: {fam}")


rows = []
famtab = collections.defaultdict(lambda: {"launches": 0, "us": 0.0, "queries": set()})
per_q = collections.defaultdict(lambda: collections.Counter())
for r in L:
    c, why = classify(r)
    us = float(r["nsys_dur_ns"]) / 1e3
    q = int(r["q"])
    per_q[q][f"n_{c}"] += 1; per_q[q][f"us_{c}"] += us
    if c == "E" and r["family"] == "AST compute_column (no nulls)":
        per_q[q]["us_E_ast"] += us; per_q[q]["n_E_ast"] += 1
    k = (r["family"], c, why)
    famtab[k]["launches"] += 1; famtab[k]["us"] += us; famtab[k]["queries"].add(q)

tot_all = collections.Counter()
for q in sorted(per_q):
    p = per_q[q]; s = SUM[q]
    n = sum(p[f"n_{c}"] for c in "ENB"); t = sum(p[f"us_{c}"] for c in "ENB")
    assert n == s["kernels"], (q, n, s["kernels"])
    tot_all.update(p); tot_all["wall"] += s["warm_ms"]; tot_all["busy"] += s["gpu_busy_ms"]
    rows.append((q, p, s["warm_ms"], s["gpu_busy_ms"], s["planning_ms"]))


def mk(label, p, wall, busy, plan):
    n = sum(p[f"n_{c}"] for c in "ENB"); t = sum(p[f"us_{c}"] for c in "ENB")
    e_ms, e_noast_ms = p["us_E"] / 1e3, (p["us_E"] - p["us_E_ast"]) / 1e3
    busy_red = min(e_ms, busy)  # upper bound: summed E kernel time cannot remove more than the busy time
    return {"query": label, "launches": n, "launches_E": p["n_E"], "launches_N": p["n_N"], "launches_B": p["n_B"],
            "share_launches_E": p["n_E"] / n, "kernel_ms": t / 1e3, "kernel_ms_E": e_ms, "kernel_ms_N": p["us_N"] / 1e3,
            "kernel_ms_B": p["us_B"] / 1e3, "share_time_E": p["us_E"] / t, "share_time_N": p["us_N"] / t, "share_time_B": p["us_B"] / t,
            "kernel_ms_E_AST": p["us_E_ast"] / 1e3, "AST_share_of_E": (p["us_E_ast"] / p["us_E"]) if p["us_E"] else 0.0,
            "warm_wall_ms": wall, "planning_ms": plan, "gpu_busy_ms": busy,
            "busy_reduction_upper_ms": busy_red, "busy_reduction_upper_frac": busy_red / busy if busy else 0.0,
            "wall_speedup_upper": wall / (wall - busy_red), "wall_speedup_upper_excl_AST": wall / (wall - min(e_noast_ms, busy)),
            "small_group_query": (int(label[1:]) in SMALL_GROUP_Q) if label.startswith("Q") else "",
            "label": "kernel ms measured (nsys, launches_all.csv); classes and bounds modeled (s -> inf on E)"}


out = [mk(f"Q{q}", p, w, b, pl) for q, p, w, b, pl in rows]
out.append(mk("ALL", tot_all, tot_all["wall"], tot_all["busy"], sum(SUM[q]["planning_ms"] for q in SUM)))
cols = list(out[0].keys())
with open(os.path.join(OUT, "coverage.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
    for r in out:
        w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
with open(os.path.join(OUT, "coverage_families.csv"), "w", newline="") as fh:
    w = csv.writer(fh); w.writerow(["family", "class", "reason", "launches", "nsys_ms", "queries", "tier_note02"])
    for (fam, c, why), v in sorted(famtab.items(), key=lambda kv: -kv[1]["us"]):
        w.writerow([fam, c, why, v["launches"], round(v["us"] / 1e3, 4), " ".join(f"Q{q}" for q in sorted(v["queries"])), FAM.get(fam, {}).get("tier", "")])
a = out[-1]
print(f"small-group queries: {sorted(SMALL_GROUP_Q)}")
print(f"ALL: launches E {a['share_launches_E']:.3f}; time E {a['share_time_E']:.3f} N {a['share_time_N']:.3f} B {a['share_time_B']:.3f}; "
      f"AST share of E {a['AST_share_of_E']:.3f}; busy reduction <= {a['busy_reduction_upper_frac']:.3f}; wall x{a['wall_speedup_upper']:.3f} "
      f"(excl. AST x{a['wall_speedup_upper_excl_AST']:.3f})")
for r in out:
    print(f"{r['query']:>4} n={r['launches']:4d} E%n={100*r['share_launches_E']:5.1f} E%t={100*r['share_time_E']:5.1f} "
          f"N%t={100*r['share_time_N']:5.1f} B%t={100*r['share_time_B']:5.1f} AST/E={100*r['AST_share_of_E']:5.1f} "
          f"busy-red<={100*r['busy_reduction_upper_frac']:5.1f}% wall x{r['wall_speedup_upper']:.3f} (noAST x{r['wall_speedup_upper_excl_AST']:.3f})")
