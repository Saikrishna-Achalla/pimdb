#!/usr/bin/env python3
"""Remove the captured process environment from Nsight Systems SQLite exports.

nsys stores the full environment of the profiled process (TARGET_INFO_SYSTEM_ENV, META_DATA_CAPTURE, some
StringIds rows). That includes account identifiers and session tokens of whatever launched the run, so the
exports must be scrubbed before they are committed or shared. Kernel/API/memcpy tables are untouched.

usage: scrub_nsys_env.py [--check] file.sqlite [...]     (--check: report only, exit 1 if anything is found)
"""
import re, sqlite3, sys

RISKY = re.compile(r"TOKEN|KEY|SECRET|PASS|AUTH|COOKIE|CRED|SOCKET|EMAIL|UUID|SESSION|SSH_|MAIL|HOSTNAME|USER|LOGNAME")
MARK = ("CLAUDE_CODE_", "CLAUDE_SSH_", "ANTHROPIC_")

def sensitive_values(con):
    vals = set()
    try:
        rows = con.execute("select value from TARGET_INFO_SYSTEM_ENV").fetchall()
    except sqlite3.Error:
        rows = []
    for (v,) in rows:
        for name, val in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\n\x00;]*)", str(v)):
            if RISKY.search(name) and len(val) >= 8:
                vals.add(val)
    return vals

def text_cells(con):
    for (t,) in con.execute("select name from sqlite_master where type='table'").fetchall():
        cols = [r[1] for r in con.execute(f'pragma table_info("{t}")')]
        for col in cols:
            yield t, col

def scrub(path, check):
    con = sqlite3.connect(path)
    vals = sensitive_values(con)
    found = 0
    for t, col in text_cells(con):
        cond = " or ".join([f'instr("{col}", ?)'] * (len(MARK) + len(vals)))
        args = list(MARK) + sorted(vals)
        try:
            n = con.execute(f'select count(*) from "{t}" where typeof("{col}")=\'text\' and ({cond})', args).fetchone()[0]
        except sqlite3.Error:
            continue
        if n:
            found += n
            if not check:
                con.execute(f'update "{t}" set "{col}"=\'[scrubbed]\' where typeof("{col}")=\'text\' and ({cond})', args)
    if not check:
        try: con.execute("delete from TARGET_INFO_SYSTEM_ENV")
        except sqlite3.Error: pass
        con.commit(); con.execute("vacuum"); con.close()
        raw = open(path, "rb").read()                      # verify on the raw bytes, not through SQL
        left = [m for m in MARK if m.encode() in raw] + [f"value#{i}" for i, v in enumerate(sorted(vals)) if v.encode() in raw]
        return found, left
    con.close()
    return found, []

if __name__ == "__main__":
    args = sys.argv[1:]; check = "--check" in args; files = [a for a in args if a != "--check"]
    bad = 0
    for f in files:
        found, left = scrub(f, check)
        if check and found: bad += 1; print(f"FOUND {found:4d} cells  {f}")
        if not check: print(f"scrubbed {found:4d} cells, residue={left or 'none'}  {f}"); bad += bool(left)
    sys.exit(1 if bad else 0)
