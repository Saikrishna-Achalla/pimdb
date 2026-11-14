"""Rows that reach the final ORDER BY / TOP-N of each query (CPU DuckDB on the same SF1 Parquet; no GPU).

For each query, the first statement of sql/q<N>_cpu.sql is re-run with its trailing LIMIT removed, and the rows are
counted: that is the number of groups (or joined rows) the GPU sort / top-N receives. Also counts the result rows.
Writes sort_input_rows.json.
"""
import json, re, duckdb, os

RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
out = {}
for q in range(2, 23):
    txt = open(f"{RES}/q{q}/sql/q{q}_cpu.sql").read()
    views = [l for l in txt.splitlines() if l.startswith("CREATE VIEW")]
    body = txt.split(".print __ITER__ 1", 1)[1].split(".print __ITER__")[0]
    stmts = [s.strip() for s in body.split(";") if s.strip() and not s.strip().startswith(".")]
    sql = stmts[-1] if len(stmts) == 1 else stmts[0]
    sql = "\n".join(l for l in sql.splitlines() if not l.startswith("."))
    con = duckdb.connect()
    for v in views:
        con.execute(v)
    for s in stmts[:-1] if len(stmts) > 1 else []:  # Q15 view creation etc.
        try:
            con.execute(s)
        except Exception:
            pass
    sql = stmts[-1] if len(stmts) > 1 else sql
    nolimit = re.sub(r"\blimit\s+\d+\s*$", "", sql.strip(), flags=re.I)
    has_order = bool(re.search(r"\border\s+by\b", sql, re.I))
    has_limit = nolimit != sql.strip()
    res = con.execute(f"select count(*) from ({nolimit})").fetchone()[0]
    full = con.execute(f"select count(*) from ({sql})").fetchone()[0]
    out[q] = {"order_by": has_order, "limit": has_limit, "rows_into_final_sort": res, "result_rows": full}
    print(q, out[q])
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "sort_input_rows.json"), "w"), indent=1)
