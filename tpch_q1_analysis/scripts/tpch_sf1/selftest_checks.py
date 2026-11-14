"""CPU-only negative tests for the hardened checks: each case edits a COPY of real pipeline outputs and asserts that
the check FAILS for the intended reason (and the unedited copy passes). No GPU is used.

Usage: python3 -I selftest_checks.py <results_dir of a completed query, e.g. results/q2> <scratch_dir>
Prints `OK|BAD <case> -- detail` per case; exit 1 if any case did not behave as expected.
"""
import csv, glob, io, json, os, re, shutil, sqlite3, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import siriuslog

SRC, SCR = sys.argv[1], sys.argv[2]
N = int(re.search(r"q(\d+)", os.path.basename(SRC.rstrip("/"))).group(1))
TABLES = subprocess.run(["python3", "-I", f"{HERE}/gen_sql.py", "tables", str(N)], capture_output=True, text=True).stdout.split()
PY = "/home/sai/cs254_project/tpch_q1_analysis/venv/bin/python"
bad = 0


def report(case, ok, detail):
    global bad
    bad += not ok
    print(f"{'OK ' if ok else 'BAD'} {case} -- {detail}")


def logcheck(lines, name, n=None):
    c, _ = siriuslog.check_log("t", lines, TABLES, n)
    return c[f"t:{name}"]["ok"], c[f"t:{name}"]["detail"][:140], all(v["ok"] for v in c.values())


# ---------------- Sirius log checks ----------------
L, _ = siriuslog.read_run(f"{SRC}/traces/sirius_log_timing")
n = len(siriuslog.parse(L)[2])
ok, d, allok = logcheck(L, "pin_tier_gpu", n)
report("log:baseline_passes", allok, "unedited timing log passes every log check")


def edited(fn):
    return [fn(l) for l in L]


def drop_first(pred):
    out, done = [], False
    for l in L:
        if not done and pred(l):
            done = True; continue
        out.append(l)
    return out


cases = [
    ("pin_tier_gpu", "host tier in one echoed pin", edited(lambda l: l.replace("tier='gpu'", "tier='host'", 1) if "CALL pin_table" in l and TABLES[0] in l else l)),
    ("pinned_entry_per_gpu_scan", "one `assigned pinned entry` line removed (one scan not served from the pin)",
     drop_first(lambda l: "assigned pinned entry" in l and l > L[len(L) // 2])),
    ("fs_cache_zero_every_iteration", "shutdown cache summary removed (last iteration uncovered)",
     L[:max(i for i, l in enumerate(L) if "cache summary" in l)] + L[max(i for i, l in enumerate(L) if "cache summary" in l) + 1:]),
    ("fs_cache_zero_every_iteration", "non-zero last_cycle reads in a mid-run summary",
     [l.replace("last_cycle[reads=0", "last_cycle[reads=3") if i == [j for j, x in enumerate(L) if "cache summary" in x][5] else l for i, l in enumerate(L)]),
    ("no_downgrade_or_spill", "a [downgrade] line inside an iteration",
     L[:len(L) - 40] + ["[2026-11-13 13:00:00.000] [info] [downgrade_executor.cpp:557] [downgrade] moved 4 MB GPU->HOST"] + L[len(L) - 40:]),
    ("no_cache_assign_error", "cache-assignment error line",
     L[:len(L) - 40] + ["[2026-11-13 13:00:00.000] [error] [sirius_scan_manager.cpp:4186] [sirius_scan_manager] error while trying to assign cached entries to operator '3': x"] + L[len(L) - 40:]),
    ("pool_counters_stable", "host_pool peak grows inside a late iteration",
     [l.replace(" peak=", " peak=9", 1) if i == [j for j, x in enumerate(L) if "[host_pool]" in x and "QueryEnd" in x][-2] else l for i, l in enumerate(L)]),
    ("iterations_found", "one iteration missing vs expected count", L),
]
for name, what, lines in cases:
    ok, d, _ = logcheck(lines, name, n + 1 if name == "iterations_found" else n)
    report(f"log:{name}", not ok, f"{what} -> FAIL: {d}")
bloom = L[:len(L) - 40] + ["[2026-11-13 13:00:00.000] [info] [x.cpp:1] accumulated Bloom started/published through peer copies (115200-byte transfer chunks)"] + L[len(L) - 40:]
ok, d, _ = logcheck(bloom, "no_downgrade_or_spill", n)
report("log:bloom_line_is_not_a_downgrade", ok, "a Bloom-filter line must not trip the downgrade/OOM check")
staged = L[:len(L) - 40] + ["[2026-11-13 13:00:00.000] [info] [dynamic_filter_publisher.cpp:426] [dynamic_filter_publication_session] accumulated Bloom published through HOST staging: 1 filter(s) pushed to 1 target(s)"] + L[len(L) - 40:]
ok, d, _ = logcheck(staged, "no_host_staged_filter_publication", n)
report("log:host_staged_bloom_publication", not ok, f"-> FAIL: {d}")

# multiple processes in one dir, and a run split across two daily files: the last process must be the one checked
dd = f"{SCR}/logs_multi"; shutil.rmtree(dd, ignore_errors=True); os.makedirs(dd)
other = [l.replace("assigned pinned entry", "assigned XX entry") for l in L]  # an earlier, broken process
half = len(L) // 2
open(f"{dd}/sirius_2026-11-12.log", "w").write("\n".join(other + L[:half]) + "\n")
open(f"{dd}/sirius_2026-11-13.log", "w").write("\n".join(L[half:]) + "\n")
lines, procs = siriuslog.read_run(dd)
c, _ = siriuslog.check_log("t", lines, TABLES, n)
report("log:last_process_across_daily_files", procs == 2 and all(v["ok"] for v in c.values()),
       f"{procs} processes found, last one reassembled across 2 daily files and passes")

# ---------------- SQL tier ----------------
sql = open(f"{SRC}/sql/q{N}_timing.sql").read()
report("sql:baseline", not siriuslog.sql_pin_problems(sql, TABLES), "generated SQL passes")
p = siriuslog.sql_pin_problems(sql.replace("tier='gpu'", "tier='host'", 1), TABLES)
report("sql:host_tier", bool(p), f"-> {p}")
p = siriuslog.sql_pin_problems("\n".join(l for l in sql.splitlines() if f"name='{TABLES[-1]}'" not in l), TABLES)
report("sql:missing_pin", bool(p), f"-> {p}")

# ---------------- pcie_verify.py memcpy classification / UM / limits ----------------
def pcie_case(tag, mutate_db):
    R = f"{SCR}/pcie_{tag}"; shutil.rmtree(R, ignore_errors=True); os.makedirs(f"{R}/traces")
    shutil.copytree(f"{SRC}/sql", f"{R}/sql"); shutil.copy(f"{SRC}/timing.json", R)
    db = f"{R}/traces/q.sqlite"; shutil.copy(glob.glob(f"{SRC}/traces/q*_nsys.sqlite")[0], db)
    c = sqlite3.connect(db); mutate_db(c); c.commit(); c.close()
    out = subprocess.run(["python3", "-I", f"{HERE}/pcie_verify.py", str(N), R, f"{SRC}/traces/sirius_log_timing",
                          f"{SRC}/traces/sirius_log_nsys", db, "3"] + TABLES, capture_output=True, text=True)
    P = json.load(open(f"{R}/pcie.json"))
    return out.returncode, {k for k, v in P["checks"].items() if not v["ok"]}, P


def add_um(c, fault_in_measured):
    c.execute("delete from META_DATA_CAPTURE where name like '%UVM%PAGE_FAULTS'")
    for k in ("PROCESS_0:COLLECT_UVM_CPU_PAGE_FAULTS", "PROCESS_0:COLLECT_UVM_GPU_PAGE_FAULTS"):
        c.execute("insert into META_DATA_CAPTURE (name, value) values (?, 'true')", (k,))
    for t in ("CUDA_UM_CPU_PAGE_FAULT_EVENTS", "CUDA_UM_GPU_PAGE_FAULT_EVENTS"):
        c.execute(f"create table if not exists {t} (start INTEGER, end INTEGER)")
    if fault_in_measured:
        s = c.execute("select max(start) from CUPTI_ACTIVITY_KIND_KERNEL").fetchone()[0]
        c.execute("insert into CUDA_UM_GPU_PAGE_FAULT_EVENTS values (?, ?)", (s, s + 10))


def no_um(c):
    c.execute("delete from META_DATA_CAPTURE where name like '%UVM%PAGE_FAULTS'")


def managed_alloc(c):
    add_um(c, False)
    i = c.execute("select max(id) from StringIds").fetchone()[0] + 1
    c.execute("insert into StringIds values (?, 'cudaMallocManaged_v6000')", (i,))
    c.execute("update CUPTI_ACTIVITY_KIND_RUNTIME set nameId=? where correlationId=(select min(correlationId) from CUPTI_ACTIVITY_KIND_RUNTIME)", (i,))


rc, fails, P = pcie_case("um_ok", lambda c: add_um(c, False))
report("pcie:baseline_with_empty_um_tables", rc == 0, f"exit {rc}, failing {sorted(fails) or 'none'}")
rc, fails, _ = pcie_case("um_fault", lambda c: add_um(c, True))
report("pcie:um_fault_in_measured_iteration", rc == 1 and fails == {"unified_memory"}, f"exit {rc}, failing {sorted(fails)}")
rc, fails, _ = pcie_case("no_um", no_um)
report("pcie:no_um_tracing", rc == 1 and fails == {"unified_memory"}, f"exit {rc}, failing {sorted(fails)}")
rc, fails, _ = pcie_case("managed_api", managed_alloc)
report("pcie:managed_memory_api_call", rc == 1 and fails == {"unified_memory"}, f"exit {rc}, failing {sorted(fails)}")


def d2d_becomes_h2d(c):  # copyKind still says D2D; only the memory kinds say host->device
    add_um(c, False)
    pinned = c.execute("select id from ENUM_CUDA_MEM_KIND where label='Pinned'").fetchone()[0]
    s = c.execute("select max(start) from CUPTI_ACTIVITY_KIND_MEMCPY where copyKind=8").fetchone()[0]
    c.execute("update CUPTI_ACTIVITY_KIND_MEMCPY set srcKind=?, bytes=? where start=? and copyKind=8", (pinned, P["limits"]["h2d_max_single"] + 1, s))


rc, fails, _ = pcie_case("kind", d2d_becomes_h2d)
report("pcie:copy_classified_by_memory_kind", rc == 1 and fails == {"h2d_measured_iterations"},
       f"a copyKind=D2D record with a Pinned source of limit+1 bytes -> exit {rc}, failing {sorted(fails)}")


def managed(c):
    add_um(c, False)
    m = c.execute("select id from ENUM_CUDA_MEM_KIND where label='Managed'").fetchone()[0]
    s = c.execute("select max(start) from CUPTI_ACTIVITY_KIND_MEMCPY").fetchone()[0]
    c.execute("update CUPTI_ACTIVITY_KIND_MEMCPY set srcKind=?, dstKind=? where start=?", (m, m, s))


rc, fails, _ = pcie_case("managed", managed)
report("pcie:managed_to_managed_copy", rc == 1 and fails == {"no_other_host_copies"}, f"exit {rc}, failing {sorted(fails)}")

# ---------------- check_sysmem.py ----------------
rep = glob.glob(f"{SRC}/profiles/*_warm_full.ncu-rep") + glob.glob(f"{SRC}/profiles/*_warm_families_full.ncu-rep")
raw = subprocess.run(["/usr/local/cuda/bin/ncu", "--import", rep[0], "--page", "raw", "--csv", "--print-units", "base", "--metrics",
                      "syslts__t_sectors_srcunit_tex_aperture_sysmem_lookup_miss.sum,syslts__t_sectors_srcunit_tex_aperture_sysmem_op_read_lookup_miss.sum,"
                      "syslts__t_sectors_srcunit_tex_aperture_sysmem_op_write_lookup_miss.sum,syslts__t_sectors_srcunit_tex_aperture_sysmem_op_atom_lookup_miss.sum,"
                      "syslts__t_sectors_srcunit_tex_aperture_sysmem_op_red_lookup_miss.sum,gpu__time_duration.sum"],
                     capture_output=True, text=True, check=True).stdout
rows = list(csv.reader(io.StringIO("\n".join(l for l in raw.splitlines() if l.startswith('"')))))
col = rows[0].index("syslts__t_sectors_srcunit_tex_aperture_sysmem_op_read_lookup_miss.sum")
rows[5][col] = "32"
buf = io.StringIO(); csv.writer(buf, quoting=csv.QUOTE_ALL).writerows(rows)
R = f"{SCR}/sysmem"; shutil.rmtree(R, ignore_errors=True); os.makedirs(f"{R}/profiles")
os.symlink(rep[0], f"{R}/profiles/{os.path.basename(rep[0])}")
open(f"{SCR}/sysmem_raw.csv", "w").write(buf.getvalue())
out = subprocess.run(["python3", "-I", f"{HERE}/check_sysmem.py", R], capture_output=True, text=True, env=dict(os.environ, SYSMEM_RAW_CSV=f"{SCR}/sysmem_raw.csv"))
report("sysmem:one_kernel_reads_host_memory", out.returncode == 1, out.stdout.strip()[:160])
rows[5][col] = "0"  # undo the injected access; now drop the required aggregate counter
hdr = rows[0].index("syslts__t_sectors_srcunit_tex_aperture_sysmem_lookup_miss.sum")
rows2 = [[v for i, v in enumerate(r) if i != hdr] for r in rows]
buf = io.StringIO(); csv.writer(buf, quoting=csv.QUOTE_ALL).writerows(rows2); open(f"{SCR}/sysmem_raw2.csv", "w").write(buf.getvalue())
out = subprocess.run(["python3", "-I", f"{HERE}/check_sysmem.py", R], capture_output=True, text=True, env=dict(os.environ, SYSMEM_RAW_CSV=f"{SCR}/sysmem_raw2.csv"))
report("sysmem:metric_missing", out.returncode == 1 and "missing metrics ['syslts" in out.stdout and " 0 with SM" in out.stdout, out.stdout.strip()[:200])

# ---------------- kernel_list.py stability ----------------
R = f"{SCR}/klist"; shutil.rmtree(R, ignore_errors=True); os.makedirs(R)
x5 = open(f"{SRC}/traces/ncu_list_x5.csv").read().splitlines()
last_id = max(int(r[0]) for r in csv.reader([l for l in x5 if l.startswith('"') and l[1].isdigit()]))
open(f"{R}/x5.csv", "w").write("\n".join(l for l in x5 if not l.startswith(f'"{last_id}"')) + "\n")
out = subprocess.run([PY, "-I", f"{HERE}/kernel_list.py", f"{SRC}/traces/ncu_list_x3.csv", f"{SRC}/traces/ncu_list_x4.csv",
                      f"{R}/x5.csv", R, "1000", "0.9"], capture_output=True, text=True)
plan = json.load(open(f"{R}/ncu_plan.json"))
report("klist:one_launch_missing_in_last_iteration", out.returncode == 1 and plan["stable"] is False and os.path.exists(f"{R}/ERROR.txt"),
       f"exit {out.returncode}, stable={plan['stable']}, reasons={plan['unstable_reasons']}")

# ---------------- validate_query.py: overridden limits, staleness ----------------
R = f"{SCR}/q{N}"; shutil.rmtree(R, ignore_errors=True)
shutil.copytree(SRC, R, symlinks=True, ignore=shutil.ignore_patterns("*.ncu-rep", "*.nsys-rep"))
for f in glob.glob(f"{SRC}/profiles/*.ncu-rep"):
    os.symlink(f, f"{R}/profiles/{os.path.basename(f)}")
base = subprocess.run(["python3", "-I", f"{HERE}/validate_query.py", str(N)], capture_output=True, text=True, env=dict(os.environ, RESULTS_DIR=R)).stdout
P = json.load(open(f"{R}/pcie.json")); P["limits"]["h2d_max_single"] *= 4; json.dump(P, open(f"{R}/pcie.json", "w"))
v = subprocess.run(["python3", "-I", f"{HERE}/validate_query.py", str(N)], capture_output=True, text=True, env=dict(os.environ, RESULTS_DIR=R)).stdout
report("validate:overridden_limits", "FAIL    pcie:byte_limits_are_defaults" in v and "PASS    pcie:byte_limits_are_defaults" in base,
       [l for l in v.splitlines() if "byte_limits" in l][0][:150])
os.utime(f"{R}/sql/q{N}_timing.sql")  # an input changed after its output was produced
v = subprocess.run(["python3", "-I", f"{HERE}/validate_query.py", str(N)], capture_output=True, text=True, env=dict(os.environ, RESULTS_DIR=R)).stdout
report("validate:stale_outputs", "FAIL    outputs_newer_than_inputs" in v, [l for l in v.splitlines() if "outputs_newer" in l][0][:150])

print(f"selftest_checks: {'ALL CASES BEHAVED AS EXPECTED' if not bad else f'{bad} case(s) did not behave as expected'}")
sys.exit(1 if bad else 0)
