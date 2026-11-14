"""Generate a DuckDB script for TPC-H query N at SF1.

Usage: python3 -I gen_sql.py <N> <iterations> <mode> [--sleep SEC] > out.sql
       python3 -I gen_sql.py tables <N>     (list referenced tables)
  mode = pin  : views + pin_table(tier='gpu') of the query's columns + .timer on + query x iterations (Sirius)
         cpu  : views + .timer on + query x iterations (plain DuckDB, no pinning)
  --omit-pin T: (negative-control self-test only) leave table T unpinned
  --sleep SEC : insert `.shell sleep SEC` before every iteration (idle gaps that separate
                iterations in an nsys timeline; never used for timing runs)
Markers printed into the output: __PIN_BEGIN__/__PIN_END__ and `__ITER__ i`.
Views list exactly the files of the pin glob (sorted), as tpch_pin_columns.py requires.
Exits non-zero if the query references a table with no pin-map entry.
"""
import glob, importlib.util, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from siriuslog import sql_pin_problems

SIRIUS = "/home/sai/cs254_project/sirius"
PQ = os.environ.get("TPCH_PARQUET_DIR", f"{SIRIUS}/test_datasets/tpch_parquet_sf10")
QDIR = f"{SIRIUS}/test/tpch_performance/tpch_queries/orig"
PINPY = f"{SIRIUS}/test/tpch_performance/tpch_pin_columns.py"
TABLES = ["lineitem", "orders", "customer", "part", "partsupp", "supplier", "nation", "region"]


def pin_map():
    spec = importlib.util.spec_from_file_location("tpch_pin_columns", PINPY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m.QUERY_COLUMNS


def query_text(n):
    return open(f"{QDIR}/q{n}.sql").read().strip()


def referenced_tables(sql):
    s = re.sub(r"'[^']*'", "''", sql.lower())  # drop string literals
    return [t for t in TABLES if re.search(rf"\b{t}\b", s)]


def main(a):
    if a[0] == "largest":  # gen_sql.py largest <N>: referenced table with the most Parquet bytes (self-test target)
        t = referenced_tables(query_text(int(a[1])))
        print(max(t, key=lambda x: sum(os.path.getsize(f) for f in glob.glob(os.path.join(PQ, x, "*.parquet"))))); return
    if a[0] == "tables":  # gen_sql.py tables <N>: print the TPC-H tables the query references
        print(" ".join(referenced_tables(query_text(int(a[1]))))); return
    n, iters, mode = int(a[0]), int(a[1]), a[2]
    sleep = float(a[a.index("--sleep") + 1]) if "--sleep" in a else 0.0
    omit = a[a.index("--omit-pin") + 1] if "--omit-pin" in a else None
    sql = query_text(n)
    tabs = referenced_tables(sql)
    cols = pin_map().get(n, {})
    missing = [t for t in tabs if t not in cols]
    if mode == "pin" and missing:
        sys.exit(f"ERROR: q{n} references tables {missing} that have no entry in tpch_pin_columns.py")
    out = []
    for t in tabs:
        files = sorted(glob.glob(os.path.join(os.path.abspath(PQ), t, "*.parquet")))
        if not files:
            sys.exit(f"ERROR: no parquet files for {t} under {PQ}")
        out.append(f"CREATE VIEW {t} AS SELECT * FROM read_parquet([{','.join(repr(f) for f in files)}]);")
    if mode == "pin":
        # tpch_pin_columns.py honours SIRIUS_PIN_TIER / SIRIUS_PIN_TIER_<TABLE>: force 'gpu' and verify the output
        env = {k: v for k, v in os.environ.items() if not k.startswith("SIRIUS_PIN_TIER")}
        env["SIRIUS_PIN_TIER"] = "gpu"
        pin = subprocess.run(["python3", "-I", PINPY, "pin", str(n), PQ], capture_output=True, text=True, check=True, env=env).stdout
        probs = sql_pin_problems(pin, tabs)
        if probs:
            sys.exit(f"ERROR: q{n} pin statements are not all tier='gpu' for the referenced tables: {probs}")
        if omit:  # negative-control self-test only: drop one table's pin so the PCIe checks must fail
            pin = "\n".join(l for l in pin.splitlines() if f"name='{omit}'" not in l)
        out += [".print __PIN_BEGIN__", pin.strip(), ".print __PIN_END__"]
    out += [".mode csv", ".timer on"]
    for i in range(1, iters + 1):
        if sleep:
            out.append(f".shell sleep {sleep}")
        out += [f".print __ITER__ {i}", sql if sql.endswith(";") else sql + ";"]
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
