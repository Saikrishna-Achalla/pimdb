#!/usr/bin/env python3
"""Generate TPC-H lineitem with DuckDB's tpch extension and export the columns Q1/Q6 use at the physical
widths cuDF/Sirius held them in the real runs (see results/column_widths in the final report):
  l_shipdate                         int16  days since 1970-01-01   (2 B: inferred from 14.0 B/row Q6, 28.0 B/row Q1)
  l_quantity, l_extendedprice,
  l_discount, l_tax                  int32  DECIMAL(15,2) raw value x100 (decimal32; gather/cast kernels name int)
  l_returnflag, l_linestatus         cuDF strings: int32 offsets (n+1) + uint8 chars
Also writes the DuckDB reference answers for Q6 and Q1 as exact scaled integers (ref.json).
Usage: python gen_data.py 0.01 0.1   (run with /home/sai/aimdb/.venv/bin/python)"""
import json, os, sys
import duckdb, numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
EXT = os.path.join(ROOT, '.cache', 'duckdb')

Q6 = dict(date_lo=8766, date_hi=9131, disc_lo=5, disc_hi=7, qty_lt=2400)   # [1994-01-01, 1995-01-01), 0.05..0.07, < 24
Q1 = dict(date_le=10471)                                                   # <= 1998-09-02 (1998-12-01 - 90 days)


def main(sfs):
    for sf in sfs:
        out = os.path.join(ROOT, 'data', f'sf{sf}')
        os.makedirs(out, exist_ok=True)
        con = duckdb.connect()
        con.execute(f"SET extension_directory='{EXT}'")
        con.execute('INSTALL tpch; LOAD tpch')
        con.execute(f'CALL dbgen(sf={sf})')
        t = con.execute("""select (l_shipdate - DATE '1970-01-01')::INTEGER as d,
                                  (l_quantity*100)::BIGINT q, (l_extendedprice*100)::BIGINT p,
                                  (l_discount*100)::BIGINT di, (l_tax*100)::BIGINT t,
                                  l_returnflag rf, l_linestatus ls
                           from lineitem order by l_orderkey, l_linenumber""").fetchnumpy()
        n = len(t['d'])
        cols = {'l_shipdate': t['d'].astype(np.int16), 'l_quantity': t['q'].astype(np.int32),
                'l_extendedprice': t['p'].astype(np.int32), 'l_discount': t['di'].astype(np.int32),
                'l_tax': t['t'].astype(np.int32)}
        assert int(t['d'].max()) < 32768 and int(t['p'].max()) < 2**31
        for k, v in cols.items():
            v.tofile(os.path.join(out, k + '.bin'))
        for k, key in (('l_returnflag', 'rf'), ('l_linestatus', 'ls')):
            s = [x.encode() for x in t[key]]
            off = np.zeros(n + 1, np.int32)
            off[1:] = np.cumsum([len(x) for x in s])
            off.tofile(os.path.join(out, k + '.off.bin'))
            np.frombuffer(b''.join(s), np.uint8).tofile(os.path.join(out, k + '.chars.bin'))
        q6 = con.execute(f"""select sum(l_extendedprice*l_discount)*10000, count(*) from lineitem
            where l_shipdate >= DATE '1994-01-01' and l_shipdate < DATE '1995-01-01'
              and l_discount between 0.05 and 0.07 and l_quantity < 24""").fetchone()
        q1 = con.execute("""select l_returnflag, l_linestatus,
              (sum(l_quantity)*100)::HUGEINT, (sum(l_extendedprice)*100)::HUGEINT,
              (sum(l_extendedprice*(1-l_discount))*10000)::HUGEINT,
              (sum(l_extendedprice*(1-l_discount)*(1+l_tax))*1000000)::HUGEINT,
              (sum(l_discount)*100)::HUGEINT, count(*)
            from lineitem where l_shipdate <= DATE '1998-12-01' - INTERVAL 90 DAY
            group by 1, 2 order by 1, 2""").fetchall()
        ref = {'sf': sf, 'rows': n, 'q6_params': Q6, 'q1_params': Q1,
               'q6': {'revenue_x1e4': int(q6[0]), 'selected': int(q6[1])},
               'q1': [{'returnflag': r[0], 'linestatus': r[1], 'sum_qty_x100': int(r[2]),
                       'sum_base_price_x100': int(r[3]), 'sum_disc_price_x1e4': int(r[4]),
                       'sum_charge_x1e6': int(r[5]), 'sum_disc_x100': int(r[6]), 'count': int(r[7])} for r in q1],
               'widths_bytes_per_row': {'l_shipdate': 2, 'l_quantity': 4, 'l_extendedprice': 4, 'l_discount': 4,
                                        'l_tax': 4, 'l_returnflag': 5, 'l_linestatus': 5}}
        json.dump(ref, open(os.path.join(out, 'ref.json'), 'w'), indent=1)
        print(sf, n, ref['q6'], len(q1))


if __name__ == '__main__':
    main(sys.argv[1:] or ['0.01', '0.1'])
