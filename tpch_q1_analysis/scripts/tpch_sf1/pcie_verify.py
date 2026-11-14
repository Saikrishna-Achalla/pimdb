"""Prove that measured iterations move no table data over PCIe (timing run + nsys run).

Usage: python3 -I pcie_verify.py <N> <results_dir> <timing_log_dir> <nsys_log_dir> <nsys.sqlite> <nsys_warmup> <tables...>
Writes <results_dir>/pcie_verification.txt and pcie.json.
Exit 1 = a PCIe/residency check failed; exit 3 = only a determinism check (nsys kernels per iteration) failed.

Evidence (see siriuslog.py for the Sirius facts the log checks rely on):
 1. Generated SQL (sql/q<N>_*.sql except the CPU one): every referenced table pinned once, tier='gpu'.
 2. Sirius logs of the timing run and the nsys run (siriuslog.check_log): tier='gpu' in the echoed pin SQL; one
    `assigned pinned entry` per GPU_SCAN operator in every iteration; no cache-assignment error; fs_cache
    last_cycle all zero for every iteration (summary k describes iteration k-1, plus the shutdown summary);
    no downgrade/spill/OOM lines; gpu_pool allocated == pinned footprint and host_pool allocated/peak unchanged.
 3. nsys kernels inside the iterations: no Parquet decode / decompression kernels.
 4. nsys CUDA memcpy per measured iteration, classified by SOURCE/DESTINATION MEMORY KIND (anything that is not
    device<->device crosses PCIe), with data-relative single-copy limit (below).
 5. Unified memory: the trace must have been taken with --cuda-um-{cpu,gpu}-page-faults=true (META_DATA_CAPTURE),
    contain no UM page-fault event in a measured iteration (nsys creates CUDA_UM_*_PAGE_FAULT_EVENTS only when a fault
    occurs; verified with a cudaMallocManaged test program: 48 CPU faults recorded), and contain no managed-memory API
    call (cudaMallocManaged / cuMemAllocManaged / MemPrefetch / MemAdvise) anywhere in the trace.
In-place kernel access to device-mapped pinned host memory has no memcpy record: check_sysmem.py covers it from ncu.

Single-copy H2D limit: min(64 KiB, smallest over pinned tables with >= 8192 rows of rows/2 bytes). The narrowest
column carrier is 1 B/row, so a copy of a whole column of such a table is >= rows bytes. Tables with < 8192 rows
(e.g. nation, region) are below any useful byte limit: for them the evidence is the log checks + check_sysmem.py.
"""
import collections, json, os, re, sqlite3, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import siriuslog
from kclass import DECODE

N, R, TLOG, NLOG, DB, NWARM = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])
TABLES = sys.argv[7:]
DUCKDB = "/home/sai/cs254_project/sirius/sirius-duckdb/build/release/duckdb"
PQ = os.environ.get("TPCH_PARQUET_DIR", "/home/sai/cs254_project/sirius/test_datasets/tpch_parquet_sf1")
T = json.load(open(f"{R}/timing.json"))
checks, det = {}, {}


def add(name, ok, detail, d=checks):
    d[name] = {"ok": bool(ok), "detail": detail}


# --- row counts -> data-relative limits ---------------------------------------------------------------------------
rows = {}
for t in TABLES:
    out = subprocess.run([DUCKDB, "-csv", "-noheader", "-c", f"SELECT count(*) FROM read_parquet('{PQ}/{t}/*.parquet')"],
                         capture_output=True, text=True)
    rows[t] = int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip().isdigit() else None
big = [r for r in rows.values() if r and r >= 8192]
DEF = {"h2d_max_single": min(64 << 10, min(big) // 2) if big else 64 << 10, "h2d_max_iter": 1 << 20,
       "d2h_max_iter": max(256 << 10, 4 * T.get("result_bytes", 0))}
LIM = {"h2d_max_single": int(os.environ.get("PCIE_H2D_MAX_SINGLE", DEF["h2d_max_single"])),
       "h2d_max_iter": int(os.environ.get("PCIE_H2D_MAX_ITER", DEF["h2d_max_iter"])),
       "d2h_max_iter": int(os.environ.get("PCIE_D2H_MAX_ITER", DEF["d2h_max_iter"]))}
small = sorted(t for t, r in rows.items() if r is None or r < 8192)

# --- 1. SQL -------------------------------------------------------------------------------------------------------
probs = {}
for f in sorted(os.listdir(f"{R}/sql")):
    if f.endswith(".sql") and not f.endswith("_cpu.sql"):
        p = siriuslog.sql_pin_problems(open(f"{R}/sql/{f}").read(), TABLES)
        if p:
            probs[f] = p
add("sql:pin_tier_gpu", not probs, "every pinned SQL script pins each referenced table once with tier='gpu'" if not probs else str(probs)[:300])

# --- 2. logs ------------------------------------------------------------------------------------------------------
n_iter = lambda f: open(f"{R}/sql/{f}").read().count(".print __ITER__")
tl, truns = siriuslog.read_run(TLOG)
c1, tinfo = siriuslog.check_log("timing_log", tl, TABLES, T["iterations"])
nl, nruns = siriuslog.read_run(NLOG)
c2, ninfo = siriuslog.check_log("nsys_log", nl, TABLES, n_iter(f"q{N}_nsys.sql"))
checks.update(c1); checks.update(c2)

mem = {"pinned_allocated_bytes": tinfo["pinned_allocated_bytes"]}
peaks = [int(m.group(1)) for l in tl if "[gpu_pool]" in l and "QueryEnd" in l for m in [re.search(r"peak=(\d+)", l)] if m]
if peaks:
    mem["peak_bytes_high_water"] = max(peaks)
mem["note"] = "gpu_pool peak is a process-lifetime high-water mark (it includes the pin phase)"

# --- nsys ---------------------------------------------------------------------------------------------------------
c = sqlite3.connect(DB)
tabs = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
t0 = c.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
names = dict(c.execute("select id, value from StringIds"))
rt = {cid: names.get(nid, "?") for cid, nid in c.execute("select correlationId, nameId from CUPTI_ACTIVITY_KIND_RUNTIME")}
rel = lambda ms: ms * 1e6 - t0  # log ms (epoch) -> nsys ns
PAD = 20e6
nits = ninfo["iterations"]
wins = [(rel(it["begin_ms"]) - PAD, rel(nits[i + 1]["begin_ms"]) - PAD if i + 1 < len(nits) else float("inf"))
        for i, it in enumerate(nits)]
kern = c.execute("select k.start, k.end, s.value from CUPTI_ACTIVITY_KIND_KERNEL k join StringIds s on k.demangledName = s.id").fetchall()
cp = c.execute("select start, bytes, srcKind, dstKind, correlationId from CUPTI_ACTIVITY_KIND_MEMCPY").fetchall()
MEMK = dict(c.execute("select id, label from ENUM_CUDA_MEM_KIND"))
DEVICE = {"Device", "Device Static", "Array"}  # everything else (Pageable, Pinned, Managed, Unknown, ...) is host-side


def direction(sk, dk):
    s, d = MEMK.get(sk, str(sk)), MEMK.get(dk, str(dk))
    if s in DEVICE and d in DEVICE:
        return "D2D (on device)"
    if d in DEVICE:
        return "H2D"
    if s in DEVICE:
        return "D2H"
    return "host-host/other"


def copies(lo, hi):
    out = collections.defaultdict(lambda: {"count": 0, "bytes": 0, "max": 0, "max_api": "", "mem": collections.Counter()})
    for s, b, sk, dk, cid in cp:
        if lo <= s < hi:
            d = out[direction(sk, dk)]; d["count"] += 1; d["bytes"] += b
            d["mem"][f"{MEMK.get(sk, sk)}->{MEMK.get(dk, dk)}"] += 1
            if b > d["max"]:
                d["max"], d["max_api"] = b, rt.get(cid, "?")
    return {k: dict(v, mem=dict(v["mem"])) for k, v in out.items()}


UM = [t for t in ("CUDA_UM_CPU_PAGE_FAULT_EVENTS", "CUDA_UM_GPU_PAGE_FAULT_EVENTS") if t in tabs]
um = {t: [s for (s,) in c.execute(f"select start from {t}")] for t in UM}
per_iter = []
for i, (lo, hi) in enumerate(wins, 1):
    ks = [n for s, e, n in kern if lo <= s < hi]
    per_iter.append({"iter": i, "measured": i > NWARM, "kernels": len(ks), "kernel_ns": sum(e - s for s, e, n in kern if lo <= s < hi),
                     "decode_kernels": sorted({n[:80] for n in ks if DECODE.search(n)}), "copies": copies(lo, hi),
                     "um_faults": sum(lo <= s < hi for v in um.values() for s in v)})
meas = [p for p in per_iter if p["measured"]]
add("nsys:windows", len(wins) == len(nits) and meas and all(p["kernels"] > 0 for p in per_iter),
    f"{len(wins)} iteration windows from the nsys-run Sirius log ({len(meas)} measured, {NWARM} warmup); kernels per iteration {[p['kernels'] for p in per_iter]}")
dec = sorted({n for p in per_iter for n in p["decode_kernels"]})
add("no_parquet_decode_kernels", not dec, f"0 decode/decompress kernels among {sum(p['kernels'] for p in per_iter)} kernels of all {len(per_iter)} iterations" if not dec else f"found: {dec[:3]}")
g = lambda p, k, f: p["copies"].get(k, {}).get(f, 0)
mx = lambda k, f: max([g(p, k, f) for p in meas] or [0])
add("h2d_measured_iterations", mx("H2D", "max") <= LIM["h2d_max_single"] and mx("H2D", "bytes") <= LIM["h2d_max_iter"],
    f"per measured iteration: up to {mx('H2D', 'count')} copies, {mx('H2D', 'bytes')} B total, largest single {mx('H2D', 'max')} B "
    f"(limits: single <= {LIM['h2d_max_single']} B, total <= {LIM['h2d_max_iter']} B)")
add("d2h_measured_iterations", mx("D2H", "bytes") <= LIM["d2h_max_iter"],
    f"per measured iteration: up to {mx('D2H', 'count')} copies, {mx('D2H', 'bytes')} B total, largest single {mx('D2H', 'max')} B "
    f"(result CSV is {T.get('result_bytes')} B; limit {LIM['d2h_max_iter']} B)")
oth = mx("host-host/other", "count")
add("no_other_host_copies", oth == 0, f"{oth} copies with a non-device source and destination (managed/unknown kinds) per measured iteration")
meta = dict(c.execute("select name, value from META_DATA_CAPTURE where name like '%UVM%PAGE_FAULTS'")) if "META_DATA_CAPTURE" in tabs else {}
um_on = len(meta) == 2 and all(v == "true" for v in meta.values())
managed_api = sorted({n for n in rt.values() if re.search(r"Managed|MemPrefetch|MemAdvise", n)})
add("unified_memory", um_on and not managed_api and all(p["um_faults"] == 0 for p in meas),
    (f"UM CPU+GPU page-fault collection on ({meta}); nsys writes the fault tables only when a fault occurs "
     f"(present: {UM or 'none'}); faults per measured iteration {[p['um_faults'] for p in meas]}; managed-memory API calls in "
     f"the whole trace: {managed_api or 'none'}") if um_on else
    f"UM page-fault collection not enabled in this trace ({meta or 'no META_DATA_CAPTURE entry'}): run nsys with "
    f"--cuda-um-cpu-page-faults=true --cuda-um-gpu-page-faults=true")
add("nsys:kernels_per_iteration_stable", len({p["kernels"] for p in meas}) == 1, f"measured iterations: {[p['kernels'] for p in meas]}", det)

pin_end_ns = rel(siriuslog.ts_ms(ninfo["pin_end"])) if ninfo["pin_end"] else wins[0][0]
after = copies(pin_end_ns, float("inf")); pin_c = copies(float("-inf"), pin_end_ns)
overall = all(v["ok"] for v in checks.values())
res = {"query": int(N), "overall": "PASS" if overall else "FAIL", "checks": checks, "determinism": det, "memory": mem,
       "table_rows": rows, "tables_below_byte_limit": small, "per_iteration": per_iter, "after_pin": after, "pin_phase": pin_c,
       "limits": LIM, "default_limits": DEF, "log_processes": {"timing": truns, "nsys": nruns}}
json.dump(res, open(f"{R}/pcie.json", "w"), indent=1)


def fmt(cs):
    return "; ".join(f"{k}: {v['count']} copies, {v['bytes']} B, largest {v['max']} B ({v['max_api']}) {v['mem']}" for k, v in sorted(cs.items())) or "none"


with open(f"{R}/pcie_verification.txt", "w") as f:
    f.write(f"PCIe verification, TPC-H Q{N} SF1 (tables: {' '.join(TABLES)}; rows {rows})\n")
    f.write(f"Sirius logs: {TLOG} ({truns} process(es); last used)\n             {NLOG} ({nruns})\nnsys trace: {DB}\n\n")
    f.write("\n".join(f"[{'PASS' if v['ok'] else 'FAIL'}] {k}: {v['detail']}" for k, v in checks.items()) + "\n")
    f.write("\nDeterminism (not a PCIe criterion):\n" + "\n".join(f"[{'PASS' if v['ok'] else 'FAIL'}] {k}: {v['detail']}" for k, v in det.items()) + "\n\n")
    f.write(f"Byte limits {LIM} (defaults {DEF}{'' if LIM == DEF else ' -- OVERRIDDEN by environment'}).\n")
    f.write(f"Tables below the single-copy byte limit (< 8192 rows): {small or 'none'} -- for these the evidence is the log checks "
            f"(pinned entry per scan, fs_cache, pool counters) and the ncu sysmem-aperture check (ncu_sysmem_check.txt), not byte counts.\n")
    f.write("Copies are classified by source/destination memory kind: only Device/Device Static/Array on both ends is on-device.\n")
    f.write("Not covered here: kernels reading device-mapped pinned host memory in place (no memcpy) -> ncu_sysmem_check.txt.\n\n")
    f.write(f"GPU memory: pinned footprint after pin_table = {mem.get('pinned_allocated_bytes')} B; gpu_pool high-water = "
            f"{mem.get('peak_bytes_high_water')} B ({mem['note']})\n\n")
    f.write(f"Pin phase copies : {fmt(pin_c)}\nAfter pin (all iterations + gaps): {fmt(after)}\n\nPer iteration (nsys run):\n")
    for p in per_iter:
        f.write(f"  iter {p['iter']:2d} {'measured' if p['measured'] else 'warmup  '} kernels={p['kernels']:5d} "
                f"kernel_time={p['kernel_ns']/1e3:8.1f} us um_faults={p['um_faults']} | {fmt(p['copies'])}\n")
    f.write(f"\nOVERALL: {'PASS' if overall else 'FAIL'}\n")
print(open(f"{R}/pcie_verification.txt").read())
if not overall:
    print(f"ERROR: PCIe verification FAILED for q{N}: " + ", ".join(k for k, v in checks.items() if not v["ok"]), file=sys.stderr)
    sys.exit(1)
if not all(v["ok"] for v in det.values()):
    print(f"ERROR: q{N}: kernel launches per measured iteration differ in the nsys run (determinism, not PCIe): "
          f"{[p['kernels'] for p in meas]}", file=sys.stderr)
    sys.exit(3)
