"""Shared Sirius-log parsing and the per-run "data stayed on the GPU" log checks.

Used by pcie_verify.py (timing + nsys runs) and check_ncu_logs.py (ncu list/detail runs).

read_run(log_dir)  -> lines of the LAST Sirius process in that directory. All *.log files are read in name order
                      (a run that crosses midnight writes two daily files) and split at each process start
                      ("Loaded Sirius configuration"), so a directory that accumulated several runs is handled.
parse(lines)       -> pin statements, pin-end gpu_pool line, query iterations (one per non-DDL statement).
check_log(tag, lines, tables, expected_iterations) -> (checks, info); checks = {name: {"ok", "detail"}}.

Sirius facts these checks rely on (sirius source, src/scan_manager/sirius_scan_manager.cpp):
 - `assigned pinned entry '<t>' to operator '<id>'` is logged once per GPU_SCAN operator served from a pin (:4173).
   A missing column is a SILENT cache miss (:4016 `can_serve_with_columns(...).empty() -> continue`), so the check is
   "number of assigned lines per iteration == number of GPU_SCAN operators in that iteration's plan".
 - `cache summary: fs_cache: ... last_cycle[...]` is printed in prepare_for_query (:1553), i.e. at the START of a query,
   and once more at shutdown (:1434). Summary k (k >= 2) therefore describes query iteration k-1, and the shutdown summary
   describes the last iteration: a complete run has iterations + 1 summaries.
 - The tier is not logged; it is visible only in the `CALL pin_table(..., tier='gpu', ...)` SQL echoed by QueryBegin.
"""
import datetime, glob, os, re

DDL = ("create", "call", "set", "pragma", "load", "attach", "drop", "insert", "copy")
DOWNGRADE_RE = re.compile(r"(?i:\[downgrade\]|\[spill\](?!.*registered)|out of memory)|\bOOM\b")  # OOM case-sensitive ("Bloom")
POOL_RE = re.compile(r"\[(gpu_pool|host_pool)\] \S+ (QueryBegin|QueryEnd) .*? query=(\d+) allocated=(\d+) bytes peak=(\d+)")


def ts_ms(l):
    return datetime.datetime.strptime(l[1:24], "%Y-%m-%d %H:%M:%S.%f").timestamp() * 1e3


def log_files(log_dir):
    return sorted(glob.glob(os.path.join(log_dir, "*.log")))


def read_run(log_dir):
    """Lines of the last Sirius process in log_dir, plus the number of processes found."""
    lines = []
    for f in log_files(log_dir):
        lines += open(f, errors="replace").read().splitlines()
    starts = [i for i, l in enumerate(lines) if "Loaded Sirius configuration" in l] or [0]
    return lines[starts[-1]:], len(starts) if lines else 0


def sql_of(l):
    return l.split(" SQL: ", 1)[1].strip() if "QueryBegin: instance=" in l and " SQL: " in l else None


def parse(lines):
    pins, pin_end, its, cur = [], None, [], None
    for l in lines:
        sql = sql_of(l)
        if sql is not None:
            if sql.lower().startswith(DDL):
                cur = None
                if sql.lower().startswith("call pin_table"):
                    pins.append(sql)
            else:
                cur = {"begin_ms": ts_ms(l), "query_id": re.search(r" query=(\d+)", l).group(1), "lines": []}
                its.append(cur)
                continue
        if cur is not None:
            cur["lines"].append(l)
        elif "[gpu_pool]" in l and "QueryEnd" in l and not its:
            pin_end = l
    return pins, pin_end, its


def gpu_scans(it_lines):
    ids, on = set(), False
    for l in it_lines:
        if "=== Pipeline Overview ===" in l:
            on = True
        elif "=== Query Plan DAG ===" in l and on:
            break
        elif on:
            ids.update(re.findall(r"GPU_SCAN \(id=(\d+)\)", l))
    return len(ids)


def check_log(tag, lines, tables, expected_iterations=None):
    checks, info = {}, {}

    def add(name, ok, detail):
        checks[f"{tag}:{name}"] = {"ok": bool(ok), "detail": detail}

    pins, pin_end, its = parse(lines)
    n = len(its)
    add("iterations_found", n > 0 and (expected_iterations is None or n == expected_iterations),
        f"{n} query iterations" + (f" (expected {expected_iterations})" if expected_iterations is not None else ""))
    # tier
    tiers = [re.search(r"tier\s*=\s*'([^']*)'", p) for p in pins]
    names = [re.search(r"name\s*=\s*'([^']*)'", p) for p in pins]
    bad = [p[:120] for p, t in zip(pins, tiers) if not t or t.group(1) != "gpu"]
    pinned = sorted(m.group(1) for m in names if m)
    add("pin_tier_gpu", pins and not bad and sorted(tables) == pinned,
        f"{len(pins)} CALL pin_table statements, all tier='gpu', tables {pinned}" if not bad and sorted(tables) == pinned
        else f"non-gpu or missing pins: {bad[:2]}; pinned {pinned} vs referenced {sorted(tables)}")
    # pinned entry per GPU_SCAN
    miss = []
    for i, it in enumerate(its, 1):
        got = re.findall(r"assigned pinned entry '([^']+)'", "\n".join(it["lines"]))
        scans = gpu_scans(it["lines"])
        if scans == 0 or len(got) != scans or set(tables) - set(got):
            miss.append(f"iter{i}: {len(got)} assigned for {scans} GPU_SCANs, missing tables {sorted(set(tables) - set(got))}")
    add("pinned_entry_per_gpu_scan", n and not miss,
        f"every iteration: #`assigned pinned entry` == #GPU_SCAN operators ({gpu_scans(its[0]['lines']) if its else 0}), "
        f"all of {sorted(tables)} present" if not miss else "; ".join(miss[:3]))
    errs = [l for l in lines if "error while trying to assign cached entries" in l]
    add("no_cache_assign_error", not errs, f"{len(errs)} cache-assignment errors" + (": " + errs[0][-200:] if errs else ""))
    # fs_cache: summary k>=2 (in order, from iteration 1 onward, incl. the shutdown summary) describes iteration k-1
    first = lines.index(its[0]["lines"][0]) if its and its[0]["lines"] else len(lines)
    summ = [re.search(r"last_cycle\[([^\]]*)\]", l) for l in lines[first:] if "cache summary" in l and "last_cycle[" in l]
    summ = [dict(kv.split("=") for kv in m.group(1).split()) for m in summ if m]
    nz = [f"summary {k + 1} (describes iteration {k}): {s}" for k, s in enumerate(summ) if k >= 1 and any(int(v) for v in s.values())]
    add("fs_cache_zero_every_iteration", len(summ) == n + 1 and not nz,
        f"{len(summ)} cache summaries for {n} iterations (summary k describes iteration k-1, the shutdown summary the last); "
        f"iterations 1..{n} all last_cycle[reads=0 hits=0 h2d=0 miss=0 ...]" if len(summ) == n + 1 and not nz
        else (f"{len(summ)} summaries for {n} iterations (need {n + 1}; a missing shutdown summary means the last iteration "
              f"is uncovered or the process did not exit cleanly). " if len(summ) != n + 1 else "") + (f"non-zero: {nz[:2]}" if nz else ""))
    dg = [l for it in its for l in it["lines"] if DOWNGRADE_RE.search(l)]
    add("no_downgrade_or_spill", not dg, f"{len(dg)} downgrade/spill/OOM lines in query iterations" + (": " + dg[0][-200:] if dg else ""))
    # dynamic-filter (Bloom / IN-list) publication: Sirius logs the transport; "HOST staging" copies the filter through
    # pinned host blocks (src/cuda/sirius_dynamic_bloom_filter.cu: publication_transport), "peer copies" stays on device
    hs = [l for it in its for l in it["lines"] if "published through" in l and "peer copies" not in l]
    pubs = sum("published through" in l for it in its for l in it["lines"])
    pushed = sum("dynamic-filter publication: pushed" in l for it in its for l in it["lines"])
    # Sirius logs a transport line only for the accumulated-Bloom path; other filters log just "pushed N dynamic filter(s)".
    # For those this check shows nothing about transport: the evidence is the H2D byte bound and the sysmem-aperture check.
    add("no_host_staged_filter_publication", not hs,
        (f"{pushed} filter publication(s) logged in query iterations; {pubs} carry a transport line, all 'peer copies' "
         f"(device-side), 0 host-staged" + ("" if pubs or not pushed else
         "; no transport line was logged, so this check does not show how those filters move (see H2D byte bound, ncu_sysmem_check.txt)"))
        if not hs else f"{len(hs)} host-staged: {hs[0][-160:]}")
    # pool counters: within every iteration after the first, gpu allocated == pinned footprint at begin and end, host
    # allocated and host peak unchanged (a downgrade to host memory would move them)
    pinned_bytes = int(re.search(r"allocated=(\d+)", pin_end).group(1)) if pin_end else None
    info["pinned_allocated_bytes"] = pinned_bytes
    pb = []
    for i, it in enumerate(its, 1):
        pools = {}
        for l in it["lines"]:
            m = POOL_RE.search(l)
            if m and m.group(3) == it["query_id"]:
                pools[(m.group(1), m.group(2))] = (int(m.group(4)), int(m.group(5)))
        need = [(p, e) for p in ("gpu_pool", "host_pool") for e in ("QueryBegin", "QueryEnd")]
        if any(k not in pools for k in need):
            pb.append(f"iter{i}: pool lines missing"); continue
        ga, gb = pools[("gpu_pool", "QueryBegin")][0], pools[("gpu_pool", "QueryEnd")][0]
        ha, hb = pools[("host_pool", "QueryBegin")], pools[("host_pool", "QueryEnd")]
        if ga != gb or (pinned_bytes is not None and gb != pinned_bytes):
            pb.append(f"iter{i}: gpu_pool allocated {ga}->{gb} (pinned {pinned_bytes})")
        if i > 1 and ha != hb:
            pb.append(f"iter{i}: host_pool allocated/peak {ha}->{hb}")
        info.setdefault("gpu_peak_end", []).append(pools[("gpu_pool", "QueryEnd")][1])
    add("pool_counters_stable", n and not pb,
        f"every iteration: gpu_pool allocated == pinned footprint {pinned_bytes} B at QueryBegin and QueryEnd; iterations 2..{n}: "
        f"host_pool allocated and peak unchanged" if not pb else "; ".join(pb[:3]))
    info["iterations"] = its
    info["pin_end"] = pin_end
    return checks, info


def sql_pin_problems(sql_text, tables):
    """Problems with the CALL pin_table statements of a generated SQL script ([] = every referenced table is pinned
    exactly once with tier='gpu')."""
    calls = re.findall(r"CALL\s+pin_table\s*\((.*?)\)\s*;", sql_text, re.I | re.S)
    probs, seen = [], []
    for c in calls:
        t = re.search(r"tier\s*=\s*'([^']*)'", c); n = re.search(r"name\s*=\s*'([^']*)'", c)
        if not t or t.group(1) != "gpu":
            probs.append(f"pin of {n.group(1) if n else '?'} has tier={t.group(1) if t else 'missing'}")
        seen.append(n.group(1) if n else "?")
    if sorted(seen) != sorted(tables):
        probs.append(f"pinned tables {sorted(seen)} != referenced tables {sorted(tables)}")
    return probs
