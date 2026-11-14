#!/usr/bin/env python3
"""Print the order of memory ops / branches in one SASS function, and a size summary.
usage: sassops.py <sass> <function-substr> [full]"""
import re, sys
src, key = sys.argv[1], sys.argv[2]
full = len(sys.argv) > 3
fn = None; rows = {}
for l in open(src, errors="replace"):
    m = re.search(r"Function : (\S+)", l)
    if m: fn = m.group(1); rows[fn] = []; continue
    m = re.match(r"\s+/\*([0-9a-f]{4,})\*/\s+(.*?);?\s*/\*", l)
    if m and fn: rows[fn].append((int(m.group(1), 16), m.group(2).strip()))
for f, ins in rows.items():
    if key not in f: continue
    cnt = {}
    for _, t in ins:
        op = t.split()[1] if t.startswith("@") else t.split()[0]
        op = op.split("(")[0]
        cnt[op] = cnt.get(op, 0) + 1
    sel = {k: v for k, v in cnt.items() if re.match(r"(LDG|LD\.|ST\.|ATOM|LDL|STL|LDS|STS|BRA|BAR|RED)", k)}
    print(f"== {f}: {len(ins)} instructions ({len(ins)*16} B)  {sel}")
    if full:
        out = []
        for a, t in ins:
            if re.search(r"\b(LDG|LD\.E|ATOM\.|LDL|STL|BAR|RED)", t) or re.search(r"\bBRA\b", t):
                out.append(f"  {a:04x} {t}")
        print("\n".join(out))
