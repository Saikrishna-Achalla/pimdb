#!/usr/bin/env python3
"""Check every run under runs/ops exactly against a NumPy reference (micro-suite) or DuckDB (chains,
data/sf*/ref.json), and that the simulator logged one RUN record per kernel launch the host made.
Writes results/verification.csv.  Run with /home/sai/aimdb/.venv/bin/python (numpy)."""
import csv, glob, json, os, re, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxlog

T = vxlog.ROOT
_cache = {}


def data(sf):
    if sf not in _cache:
        d = os.path.join(T, 'data', f'sf{sf}')
        c = {k: np.fromfile(os.path.join(d, k + '.bin'), dt) for k, dt in
             (('l_shipdate', np.int16), ('l_quantity', np.int32), ('l_extendedprice', np.int32),
              ('l_discount', np.int32), ('l_tax', np.int32))}
        for k in ('l_returnflag', 'l_linestatus'):
            off = np.fromfile(os.path.join(d, k + '.off.bin'), np.int32)
            ch = np.fromfile(os.path.join(d, k + '.chars.bin'), np.uint8)
            c[k] = np.array([bytes(ch[off[i]:off[i + 1]]).decode() for i in range(len(off) - 1)])
        c['ref'] = json.load(open(os.path.join(d, 'ref.json')))
        _cache[sf] = c
    return _cache[sf]


def groups(log):
    g = {}
    for line in log.splitlines():
        if line.startswith('GROUP '):
            p = line.split()
            g[(p[1], p[2])] = [int(x) for x in p[3:]]
    return g


def check(d, sf, op, arg):
    log = open(os.path.join(d, 'run.log')).read()
    if 'DONE' not in log:
        return 'FAIL', 'run did not finish'
    nl = len(re.findall(r'^LAUNCH ', log, re.M))
    nr = len(vxlog.launches(d))
    if nl != nr:
        return 'FAIL', f'{nl} host launches vs {nr} simulator RUN records'
    D = data(sf)
    sd, q, p, di = D['l_shipdate'], D['l_quantity'], D['l_extendedprice'], D['l_discount']
    rd = lambda name, dt: np.fromfile(os.path.join(d, name), dt)
    q6m = (sd >= 8766) & (sd <= 9130) & (di >= 5) & (di <= 7) & (q < 2400)
    if op == 'empty':
        return 'PASS', f'{nl} launches'
    if op in ('pred_i16', 'pred_i32', 'range_i16', 'mask_and', 'filter_conj', 'probe'):
        ref = {'pred_i16': sd <= 10471, 'pred_i32': q < 2400, 'range_i16': (sd >= 8766) & (sd <= 9130),
               'mask_and': (sd >= 8766) & (sd <= 9130) & (di >= 5) & (di <= 7), 'filter_conj': q6m}.get(op)
        if op == 'probe':
            ref = np.isin(q, rd('keys.bin', np.int32))
        got = rd('mask.bin', np.uint8)
        ok = np.array_equal(got, ref.astype(np.uint8))
        return ('PASS' if ok else 'FAIL'), f'selected {int(ref.sum())} of {len(ref)}'
    sel = np.nonzero(q <= int(arg or 0) * 100)[0].astype(np.int32)
    if op == 'compact':
        ok = np.array_equal(rd('idx.bin', np.int32), sel)
        return ('PASS' if ok else 'FAIL'), f'{len(sel)} indices'
    if op == 'gather_i32':
        ok = np.array_equal(rd('out.bin', np.int32), p[sel])
        return ('PASS' if ok else 'FAIL'), f'{len(sel)} rows'
    if op == 'gather_i64':
        ok = np.array_equal(rd('out.bin', np.int64), p[sel].astype(np.int64))
        return ('PASS' if ok else 'FAIL'), f'{len(sel)} rows'
    if op == 'cast':
        return ('PASS' if np.array_equal(rd('out.bin', np.int64), p.astype(np.int64)) else 'FAIL'), ''
    if op == 'mul':
        return ('PASS' if np.array_equal(rd('out.bin', np.int64), p.astype(np.int64) * di) else 'FAIL'), ''
    if op in ('reduce_i32', 'reduce_i64'):
        s = int(re.search(r'RESULT sum=(-?\d+)', log).group(1))
        return ('PASS' if s == int(p.astype(np.int64).sum()) else 'FAIL'), f'sum={s}'
    if op == 'minmax_i64':
        m = re.search(r'RESULT min=(-?\d+) max=(-?\d+)', log)
        ok = int(m.group(1)) == int(p.min()) and int(m.group(2)) == int(p.max())
        return ('PASS' if ok else 'FAIL'), m.group(0)
    if op == 'groupby':
        g = groups(log)
        rf, ls = D['l_returnflag'], D['l_linestatus']
        ref = {}
        for k in sorted(set(zip(rf, ls))):
            m = (rf == k[0]) & (ls == k[1])
            ref[k] = [int(q[m].astype(np.int64).sum()), int(p[m].astype(np.int64).sum()),
                      int(di[m].astype(np.int64).sum()), int(m.sum())]
        return ('PASS' if g == ref else 'FAIL'), f'{len(g)} groups'
    if op == 'chain_q6':
        m = re.search(r'RESULT q6 revenue_x1e4=(-?\d+) selected=(\d+)', log)
        r = D['ref']['q6']
        ok = int(m.group(1)) == r['revenue_x1e4'] and int(m.group(2)) == r['selected']
        return ('PASS' if ok else 'FAIL'), f'revenue={int(m.group(1)) / 1e4:.4f} (DuckDB {r["revenue_x1e4"] / 1e4:.4f})'
    if op == 'chain_q1':
        g = groups(log)
        ref = {(r['returnflag'], r['linestatus']): [r['sum_qty_x100'], r['sum_base_price_x100'], r['sum_disc_price_x1e4'],
                                                   r['sum_charge_x1e6'], r['sum_disc_x100'], r['count']]
               for r in D['ref']['q1']}
        return ('PASS' if g == ref else 'FAIL'), f'{len(g)} groups vs DuckDB'
    return 'SKIP', 'no check'


def main():
    rows = []
    for d in sorted(glob.glob(os.path.join(T, 'runs', 'ops', '*', 'sf*', '*'))):
        cfg, sfd, name = d.split(os.sep)[-3:]
        sf = sfd[2:]
        op, arg = name, None
        for o in ('empty', 'compact', 'gather_i32', 'gather_i64', 'probe'):
            if name.startswith(o + '_'):
                op, arg = o, name[len(o) + 1:]
        try:
            st, det = check(d, sf, op, arg)
        except Exception as e:  # noqa
            st, det = 'FAIL', f'{type(e).__name__}: {e}'
        rows.append(dict(config=cfg, sf=sf, run=name, status=st, detail=det))
    out = os.path.join(T, 'results', 'verification.csv')
    with open(out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    bad = [r for r in rows if r['status'] != 'PASS']
    print(f'{len(rows)} runs, {len(rows) - len(bad)} PASS')
    for r in bad:
        print(r)


if __name__ == '__main__':
    main()
