#!/usr/bin/env python3
"""Aggregate runs/ops into results/operators.csv, results/chains.csv, results/scaling.csv and
results/rule3.csv.  All times are SIMULATED (simx cycles at the configuration's clock) unless a column
says 'modeled'.  A launch's time = its kernel cycles (RUN) + the cache write-back the runtime issues
after it (FLUSH; with the patched DRAM drain this includes the launch's DRAM writes)."""
import csv, glob, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxlog

T = vxlog.ROOT
HOST_GAP_READBACK_US = 33.6   # measured real-GPU median gap with a size read-back (note 04, gap_by_host.csv)
HOST_GAP_ALLOC_US = 7.4       # measured real-GPU median gap with only an allocation (note 04)

OPS = {  # run name -> (operator family for the table, description)
    'pred_i16': ('1 predicate', 'l_shipdate (2 B) <= c -> 1 B mask'),
    'pred_i32': ('1 predicate', 'l_quantity (4 B) < c -> 1 B mask'),
    'range_i16': ('2 range predicate', 'l_shipdate (2 B) in [a,b] -> mask (two compares)'),
    'mask_and': ('2 mask AND', 'mask & mask -> mask'),
    'filter_conj': ('1+2 conjunctive filter', '3 range terms on 2+4+4 B columns -> mask, one pass (AST-like)'),
    'compact_1': ('3 compaction', 'mask -> count -> scan -> scatter, 2.0 % selected'),
    'compact_25': ('3 compaction', 'same, 50 % selected'),
    'compact_49': ('3 compaction', 'same, 98 % selected'),
    'gather_i32_1': ('4 gather 4 B', 'int32 column at 2 % sorted indices'),
    'gather_i32_25': ('4 gather 4 B', 'int32 column at 50 % sorted indices'),
    'gather_i64_1': ('4 gather 8 B', 'int64 column at 2 % sorted indices'),
    'gather_i64_25': ('4 gather 8 B', 'int64 column at 50 % sorted indices'),
    'cast': ('5 cast/widen', 'int32 -> int64'),
    'mul': ('5 binary op', 'int64 x int64 -> int64'),
    'reduce_i32': ('6 reduce', 'SUM(int32) -> int64 (blocks + final)'),
    'reduce_i64': ('6 reduce', 'SUM(int64) (blocks + final)'),
    'minmax_i64': ('6 reduce', 'MIN/MAX(int64) (blocks + final)'),
    'groupby': ('7 small-group aggregation', '2 string keys (4 groups), 3 x SUM(int64) + COUNT: fill, fill, map, aggregate'),
    'probe_8': ('8 membership probe', 'int32 column IN 8-key sorted set -> mask'),
    'empty_3': ('launch cost', 'empty kernel'),
}


def run_info(d):
    log = open(os.path.join(d, 'run.log')).read()
    labels = [l.split() for l in log.splitlines() if l.startswith('LAUNCH ')]
    L = vxlog.launches(d)
    for lab, x in zip(labels, L):
        x['kernel'], x['tag'] = lab[2], lab[3]
        x['items'] = int(lab[4].split('=')[1])
        x['lbytes'] = int(lab[5].split('=')[1])
    m = re.search(r'TABLE rows=(\d+)', log)
    rows = int(m.group(1)) if m else 0
    host = []   # host steps in order, with the index of the launch they follow
    k = 0
    for l in log.splitlines():
        if l.startswith('LAUNCH '):
            k += 1
        elif l.startswith('HOST '):
            host.append((k, l.split()[1], int(l.split('bytes=')[1])))
    return L, rows, host, log


def empty_cost(cfg):
    """simulated cycles of an empty launch with all resident threads (run + flush), min over repeats"""
    for sf in ('0.01', '0.1'):
        d = os.path.join(T, 'runs', 'ops', cfg, f'sf{sf}', 'empty_3')
        if os.path.exists(os.path.join(d, 'launch.log')):
            L, *_ = run_info(d)
            full = [x['cycles'] for x in L if x['tag'] == 'empty_full']
            one = [x['cycles'] for x in L if x['tag'] == 'empty_1wg']
            return min(full), min(one), L
    return None, None, None


def bound(pct_bw, launch_share, ipc_frac, pct_bw_net):
    if launch_share >= 0.5:
        return 'launch-bound', f'fixed launch cost is {launch_share:.0%} of the time'
    if pct_bw >= 70:
        return 'memory-bound', f'DRAM at {pct_bw:.0f}% of configured bandwidth'
    if pct_bw_net >= 70:
        return 'memory-bound (net of launch cost)', f'{pct_bw_net:.0f}% of bandwidth outside the fixed launch cost ({launch_share:.0%})'
    if ipc_frac >= 0.5:
        return 'issue-bound', f'IPC at {ipc_frac:.0%} of the issue width'
    return 'latency-bound', f'only {pct_bw_net:.0f}% of bandwidth net of launch cost, IPC {ipc_frac:.0%} of issue width: too few requests in flight / serialization'


def op_rows():
    rows = []
    for d in sorted(glob.glob(os.path.join(T, 'runs', 'ops', '*', 'sf*', '*'))):
        cfg, sfd, name = d.split(os.sep)[-3:]
        if name.startswith('chain_') or not os.path.exists(os.path.join(d, 'launch.log')):
            continue
        c = vxlog.config(cfg)
        L, nrows, host, log = run_info(d)
        if not L:
            continue
        e_full, e_1wg, _ = empty_cost(cfg)
        if name == 'empty_3':
            for tag in ('empty_1wg', 'empty_full'):
                xs = [x for x in L if x['tag'] == tag]
                cyc = min(x['cycles'] for x in xs)
                rows.append(dict(operator='launch cost', run=f'{name}:{tag}', config=cfg, cores=c['cores'], warps=c['warps'],
                                 sf=sfd[2:], rows=nrows, out_items=0, launches=1, cycles=cyc,
                                 run_cycles=min(x['run_cycles'] for x in xs), flush_cycles=min(x['flush_cycles'] for x in xs),
                                 time_us=round(cyc / c['clock_mhz'], 3), instrs=xs[0]['run_instrs'], ipc='',
                                 dram_read_bytes=xs[0]['dram_reads'] * 64, dram_write_bytes=xs[0]['dram_writes'] * 64,
                                 dram_bytes=xs[0]['dram_bytes'], logical_bytes=0, ns_per_row='', pct_bw='',
                                 launch_cycles_modeled=cyc, net_cycles=0, pct_bw_net='', row_hit_pct='', bound='launch cost',
                                 why='empty kernel: ' + ('one work-group of 256' if tag == 'empty_1wg' else 'one work-item per resident thread'),
                                 desc='empty kernel (min of 3)'))
            continue
        cyc = sum(x['cycles'] for x in L)
        instrs = sum(x['run_instrs'] for x in L)
        run_c = sum(x['run_cycles'] for x in L)
        rd = sum(x['dram_reads'] for x in L) * 64
        wr = sum(x['dram_writes'] for x in L) * 64
        lb = sum(x['lbytes'] for x in L)
        sec = cyc / (c['clock_mhz'] * 1e6)
        peak = c['peak_gbs'] * 1e9
        pct = 100 * (rd + wr) / sec / peak
        launch_c = e_full * len(L) if e_full else 0
        net = max(cyc - launch_c, 1)
        pct_net = 100 * (rd + wr) / (net / (c['clock_mhz'] * 1e6)) / peak
        ipc_frac = instrs / run_c / (4 * c['cores'])
        b, why = bound(pct, launch_c / cyc, ipc_frac, pct_net)
        fam, desc = OPS.get(name, (name, ''))
        rows.append(dict(operator=fam, run=name, config=cfg, cores=c['cores'], warps=c['warps'], sf=sfd[2:], rows=nrows,
                         out_items=L[-1]['items'] if name.startswith('gather') else '', launches=len(L), cycles=cyc,
                         run_cycles=run_c, flush_cycles=sum(x['flush_cycles'] for x in L),
                         time_us=round(sec * 1e6, 2), instrs=instrs, ipc=round(instrs / run_c, 3),
                         dram_read_bytes=rd, dram_write_bytes=wr, dram_bytes=rd + wr, logical_bytes=lb,
                         ns_per_row=round(sec * 1e9 / nrows, 3) if nrows else '', pct_bw=round(pct, 1),
                         launch_cycles_modeled=launch_c, net_cycles=net,
                         pct_bw_net=round(pct_net, 1) if launch_c / cyc < 0.5 else '',
                         row_hit_pct=vxlog.ramulator(d).get('row_hit_pct', ''), bound=b, why=why, desc=desc))
    return rows


def chain_rows():
    rows, tots = [], []
    for d in sorted(glob.glob(os.path.join(T, 'runs', 'ops', '*', 'sf*', 'chain_*'))):
        cfg, sfd, name = d.split(os.sep)[-3:]
        if not os.path.exists(os.path.join(d, 'launch.log')):
            continue
        c = vxlog.config(cfg)
        L, nrows, host, log = run_info(d)
        e_full, _, _ = empty_cost(cfg)
        mhz = c['clock_mhz']
        after = {}
        for k, what, b in host:
            after.setdefault(k, []).append(f'{what}({b} B)')
        for i, x in enumerate(L):
            sec = x['cycles'] / (mhz * 1e6)
            rows.append(dict(chain=name, config=cfg, sf=sfd[2:], rows=nrows, idx=i, kernel=x['kernel'], tag=x['tag'],
                             items=x['items'], cycles=x['cycles'], run_cycles=x['run_cycles'], flush_cycles=x['flush_cycles'],
                             time_us=round(sec * 1e6, 3), instrs=x['run_instrs'], ipc=round(x['run_instrs'] / x['run_cycles'], 3),
                             dram_bytes=x['dram_bytes'], logical_bytes=x['lbytes'],
                             pct_bw=round(100 * x['dram_bytes'] / sec / (c['peak_gbs'] * 1e9), 1),
                             host_step_after=';'.join(after.get(i + 1, []))))
        cyc = sum(x['cycles'] for x in L)
        n_rb = sum(1 for k, w, b in host if w.startswith('readback') and k < len(L))   # read-backs between launches
        gaps = len(L) - 1
        gaps_rb = len({k for k, w, b in host if k < len(L)})
        omitted = omitted_per_batch(name[-2:])
        sim_us = cyc / mhz
        tots.append(dict(chain=name, config=cfg, sf=sfd[2:], rows=nrows, launches=len(L), cycles=cyc,
                         sim_time_us=round(sim_us, 2), sim_ns_per_row=round(sim_us * 1000 / nrows, 3),
                         dram_bytes=sum(x['dram_bytes'] for x in L), logical_bytes=sum(x['lbytes'] for x in L),
                         pct_bw=round(100 * sum(x['dram_bytes'] for x in L) / (cyc / (mhz * 1e6)) / (c['peak_gbs'] * 1e9), 1),
                         launch_cost_us_in_sim=round(len(L) * e_full / mhz, 2) if e_full else '',
                         omitted_launches=omitted, omitted_launch_cost_us_modeled=round(omitted * e_full / mhz, 2) if e_full else '',
                         host_gaps_readback=gaps_rb, host_gaps_alloc=gaps - gaps_rb,
                         host_term_us_modeled=round(gaps_rb * HOST_GAP_READBACK_US + (gaps - gaps_rb) * HOST_GAP_ALLOC_US, 1),
                         total_us_modeled=round(sim_us + (omitted * e_full / mhz if e_full else 0) + gaps_rb * HOST_GAP_READBACK_US
                                                + (gaps - gaps_rb) * HOST_GAP_ALLOC_US, 1)))
    return rows, tots


def omitted_per_batch(q):
    p = os.path.join(T, 'results', f'mapping_{q}.csv')
    if not os.path.exists(p):
        return 0
    rows = list(csv.DictReader(open(p)))
    # per-batch bookkeeping launches we do not simulate (excluding once-per-query merge work)
    return round(sum(float(r['real_launches_per_batch']) for r in rows
                     if int(r['sim_launches_per_batch']) == 0 and not r['real_family'].startswith(('other', 'final merge'))))


def write(name, rows):
    if not rows:
        return
    with open(os.path.join(T, 'results', name), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def main():
    ops = op_rows()
    write('operators.csv', ops)
    lrows, tots = chain_rows()
    write('chains.csv', lrows)
    write('chains_totals.csv', tots)
    # scaling: per run, S1 SF0.01 vs SF0.1 (ns/row), S1 vs S4 at SF0.1 (throughput ratio)
    idx = {(r['config'], r['sf'], r['run']): r for r in ops}
    for t in tots:
        idx[(t['config'], t['sf'], t['chain'])] = dict(cycles=t['cycles'], ns_per_row=t['sim_ns_per_row'], time_us=t['sim_time_us'])
    sc = []
    for name in list(OPS) + ['chain_q6', 'chain_q1']:
        if name == 'empty_3':
            continue
        a, b = idx.get(('S1', '0.01', name)), idx.get(('S1', '0.1', name))
        c4, c41 = idx.get(('S4', '0.1', name)), idx.get(('S4', '0.01', name))
        a1, c4_1 = idx.get(('S1', '1', name)), idx.get(('S4', '1', name))
        if not (a and b):
            continue
        sc.append(dict(run=name, s1_ns_per_row_sf001=a['ns_per_row'], s1_ns_per_row_sf01=b['ns_per_row'],
                       s1_sf01_over_sf001=round(float(b['ns_per_row']) / float(a['ns_per_row']), 3),
                       s4_ns_per_row_sf01=c4['ns_per_row'] if c4 else '',
                       s4_speedup_over_s1_sf01=round(float(b['time_us']) / float(c4['time_us']), 2) if c4 else '',
                       s4_speedup_over_s1_sf001=round(float(a['time_us']) / float(c41['time_us']), 2) if c41 else '',
                       s1_ns_per_row_sf1=a1['ns_per_row'] if a1 else '',
                       s1_sf1_over_sf01=round(float(a1['ns_per_row']) / float(b['ns_per_row']), 3) if a1 else '',
                       s4_speedup_over_s1_sf1=round(float(a1['time_us']) / float(c4_1['time_us']), 2) if (a1 and c4_1) else ''))
    write('scaling.csv', sc)
    # rule 3: same DRAM, more warps / cores
    r3 = []
    for name in OPS:
        base = idx.get(('S1', '0.1', name))
        if not base:
            continue
        for cfg in ('S1_w16', 'S1_w64', 'S1_c2'):
            v = idx.get((cfg, '0.1', name))
            if v:
                r3.append(dict(run=name, config=cfg, base_cycles=base['cycles'], cycles=v['cycles'],
                               speedup_vs_S1=round(base['cycles'] / v['cycles'], 3), base_pct_bw=base['pct_bw'],
                               pct_bw=v['pct_bw'], base_bound=base['bound'], bound=v['bound']))
    write('rule3.csv', r3)
    print(len(ops), 'operator rows,', len(lrows), 'chain launches,', len(tots), 'chain totals,', len(sc), 'scaling,', len(r3), 'rule3')


if __name__ == '__main__':
    main()
