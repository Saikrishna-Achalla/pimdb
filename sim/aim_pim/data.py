#!/usr/bin/env python3
"""TPC-H lineitem from DuckDB's tpch extension, at the physical widths cuDF/Sirius used (see isr_spec.json
"operand_widths"): decimals as scaled integers (x100), quantity int16, price/discount/tax int32 (Sirius' narrowed
carriers, inferred from the 14.0 B/row Q6 footprint and the int32 gathers in results/q6/warm_kernel_list.json),
shipdate int32 days, returnflag/linestatus as 1-byte dictionary codes (cuDF keeps them as strings: 1 B + 4 B offset).
Cached as .npz under cache/ (regenerable)."""
import datetime, os
from decimal import Decimal
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
EPOCH = datetime.date(1970, 1, 1)
RF = {"A": 0, "N": 1, "R": 2}
LS = {"F": 0, "O": 1}


def days(y, m, d):
    return (datetime.date(y, m, d) - EPOCH).days


def _con(sf):
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL tpch; LOAD tpch;")
    con.execute(f"CALL dbgen(sf={sf})")
    return con


def lineitem(sf):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"lineitem_sf{sf:g}.npz")
    if os.path.exists(p):
        return dict(np.load(p))
    con = _con(sf)
    c = con.execute("""
        SELECT CAST(round(l_quantity*100) AS SMALLINT) q, CAST(round(l_extendedprice*100) AS INTEGER) p,
               CAST(round(l_discount*100) AS INTEGER) d, CAST(round(l_tax*100) AS INTEGER) t,
               CAST(l_shipdate - DATE '1970-01-01' AS INTEGER) s,
               CASE l_returnflag WHEN 'A' THEN 0 WHEN 'N' THEN 1 WHEN 'R' THEN 2 END::TINYINT rf,
               CASE l_linestatus WHEN 'F' THEN 0 WHEN 'O' THEN 1 END::TINYINT ls
        FROM lineitem""").fetchnumpy()
    out = dict(qty=c["q"].astype(np.int16), price=c["p"].astype(np.int32), disc=c["d"].astype(np.int32),
               tax=c["t"].astype(np.int32), ship=c["s"].astype(np.int32), rf=c["rf"].astype(np.int8),
               ls=c["ls"].astype(np.int8))
    np.savez(p, **out)
    return out


def scaled(x, scale):
    """DuckDB DECIMAL (Python Decimal) -> exact scaled integer."""
    v = Decimal(x) * (10 ** scale)
    assert v == v.to_integral_value(), x
    return int(v)


def reference(sf):
    """Exact DuckDB answers for every workload (computed on DuckDB's own decimals, not on our arrays)."""
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"ref_sf{sf:g}.npz")
    if os.path.exists(p):
        return {k: v for k, v in np.load(p, allow_pickle=True).items()}
    con = _con(sf)
    q = lambda s: con.execute(s).fetchall()
    D94, D95 = "DATE '1994-01-01'", "DATE '1995-01-01'"
    r = {}
    r["n"] = q("SELECT count(*) FROM lineitem")[0][0]
    # 1 predicate on int32 (shipdate) and on a 64-bit decimal (extendedprice), as boolean columns
    r["pred_ship"] = con.execute(f"SELECT l_shipdate < {D94} FROM lineitem").fetchnumpy()
    r["pred_ship"] = np.asarray(list(r["pred_ship"].values())[0], bool)
    r["pred_price"] = np.asarray(list(con.execute("SELECT l_extendedprice > 50000 FROM lineitem").fetchnumpy().values())[0], bool)
    # 2 range predicate + AND (Q6 shipdate range AND discount range)
    r["pred_and"] = np.asarray(list(con.execute(
        f"SELECT l_shipdate >= {D94} AND l_shipdate < {D95} AND l_discount BETWEEN 0.05 AND 0.07 FROM lineitem"
    ).fetchnumpy().values())[0], bool)
    # 3 compaction: row ids satisfying the Q6 shipdate range (ascending row number)
    r["compact_ids"] = np.asarray(list(con.execute(
        f"SELECT rn FROM (SELECT row_number() OVER () - 1 AS rn, l_shipdate FROM lineitem) "
        f"WHERE l_shipdate >= {D94} AND l_shipdate < {D95} ORDER BY rn").fetchnumpy().values())[0], np.int64)
    # 5 element-wise: price*discount (scale 4) and widen price (scale 2), as int64 columns
    r["mul"] = np.asarray(list(con.execute(
        "SELECT CAST(l_extendedprice*l_discount*10000 AS BIGINT) FROM lineitem").fetchnumpy().values())[0], np.int64)
    # 6 reduce
    r["sum_price"] = scaled(q("SELECT sum(l_extendedprice) FROM lineitem")[0][0], 2)
    # 7 small-group aggregation (Q1 key)
    r["gagg"] = np.array(q("""SELECT CASE l_returnflag WHEN 'A' THEN 0 WHEN 'N' THEN 1 ELSE 2 END*2 +
                                     CASE l_linestatus WHEN 'F' THEN 0 ELSE 1 END AS k,
                                     sum(l_quantity)*100, count(*) FROM lineitem GROUP BY k ORDER BY k"""), dtype=object)
    # 8 membership of quantity in a small key set
    r["member"] = q("SELECT count(*) FROM lineitem WHERE l_quantity IN (1,5,10,20,30,40,45,50)")[0][0]
    # chain Q6
    r["q6"] = scaled(q(f"""SELECT sum(l_extendedprice*l_discount) FROM lineitem WHERE l_shipdate >= {D94}
        AND l_shipdate < {D95} AND l_discount BETWEEN 0.05 AND 0.07 AND l_quantity < 24""")[0][0], 4)
    # chain Q1 (sums exact; avg checked from sums/count)
    rows = q("""SELECT l_returnflag, l_linestatus, sum(l_quantity), sum(l_extendedprice),
                sum(l_extendedprice*(1-l_discount)), sum(l_extendedprice*(1-l_discount)*(1+l_tax)),
                avg(l_quantity), avg(l_extendedprice), avg(l_discount), count(*), sum(l_discount)
         FROM lineitem WHERE l_shipdate <= DATE '1998-12-01' - INTERVAL 90 DAY
         GROUP BY l_returnflag, l_linestatus ORDER BY l_returnflag, l_linestatus""")
    r["q1"] = np.array([(RF[a] * 2 + LS[b], scaled(sq, 2), scaled(sp, 2), scaled(sd, 4), scaled(sc, 6),
                         float(aq), float(ap), float(ad), n, scaled(sdisc, 2))
                        for a, b, sq, sp, sd, sc, aq, ap, ad, n, sdisc in rows], dtype=object)
    np.savez(p, **r)
    return r
