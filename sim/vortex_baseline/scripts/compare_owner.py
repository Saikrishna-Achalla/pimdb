#!/usr/bin/env python3
"""Compare the S1 stream and Q6 numbers with the owner's earlier 'rtx5070q' runs (read-only logs in
/home/sai/pim/q6_vortex/). Writes results/owner_comparison.csv.
rtx5070q (owner, /home/sai/pim/vortex/profiles/rtx5070q.json): 1 core, 16 warps x 8 threads, 16 KB L1,
256 KB L2, 1 GDDR6 x16 channel @ 1750 MT/s = 3.5 GB/s (1/192 of the 5070), 2512 MHz, +518 cycles DRAM
latency, D$/L2 MSHR 16 (defaults); Q6 as ONE fused kernel over 9 B/row narrowed columns."""
import csv, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxlog

T = vxlog.ROOT
O = '/home/sai/pim/q6_vortex'
MHZ = 2512


def blocks(path):
    out, cur = [], None
    for line in open(path):
        if line.startswith('==='):
            cur = {'title': line.strip('= \n')}
            out.append(cur)
        elif cur is not None:
            m = re.search(r'PERF: instrs=(\d+), cycles=(\d+)', line)
            if m:
                cur['instrs'], cur['cycles'] = int(m.group(1)), int(m.group(2))
            m = re.search(r'PERF: memory: reqs=(\d+) \(r=(\d+), w=(\d+)\)', line)
            if m:
                cur['reqs'], cur['r'], cur['w'] = map(int, m.groups())
    return out


def main():
    rows = []
    lat = blocks(os.path.join(O, 'q6_latency_sf0.1.log'))
    for b in lat:
        if 'cycles' not in b:
            continue
        if b['title'].startswith('DRAM probe'):
            n = int(re.search(r'n=(\d+)', b['title']).group(1)); it = int(re.search(r'iters=(\d+)', b['title']).group(1))
            gbs = n * 8 * it / (b['cycles'] / (MHZ * 1e6)) / 1e9
            rows.append(dict(source='owner rtx5070q (measured in simulation, q6_latency_sf0.1.log)', what=f'stream read {b["title"]}',
                             configured_gbs=3.5, cycles=b['cycles'], time_us=round(b['cycles'] / MHZ, 1), achieved_gbs=round(gbs, 3),
                             pct_of_configured=round(100 * gbs / 3.5, 1), dram_bytes=b.get('reqs', 0) * 64,
                             full_5070_equivalent_us='', note='16 D$ MSHRs and 64 resident lanes cap requests in flight'))
        elif b['title'].startswith('q6 sf0.1') and 'reqs' in b:
            rows.append(dict(source='owner rtx5070q (q6_latency_sf0.1.log)', what='Q6 SF0.1, one fused kernel, 9 B/row',
                             configured_gbs=3.5, cycles=b['cycles'], time_us=round(b['cycles'] / MHZ, 1),
                             achieved_gbs=round(b['reqs'] * 64 / (b['cycles'] / (MHZ * 1e6)) / 1e9, 3),
                             pct_of_configured=round(100 * b['reqs'] * 64 / (b['cycles'] / (MHZ * 1e6)) / 1e9 / 3.5, 1),
                             dram_bytes=b['reqs'] * 64, full_5070_equivalent_us=round(b['cycles'] / MHZ / 192, 2),
                             note='modeled projection to the full GPU: time x 1/192 (bandwidth share), assumes linear scaling'))
            break
    for b in blocks(os.path.join(O, 'q6_l2_sf0.1.log')):
        if 'reqs' in b:
            rows.append(dict(source='owner rtx5070q, MEMORY_LATENCY=0 (q6_l2_sf0.1.log)', what='Q6 SF0.1, fused kernel',
                             configured_gbs=3.5, cycles=b['cycles'], time_us=round(b['cycles'] / MHZ, 1),
                             achieved_gbs=round(b['reqs'] * 64 / (b['cycles'] / (MHZ * 1e6)) / 1e9, 3),
                             pct_of_configured=round(100 * b['reqs'] * 64 / (b['cycles'] / (MHZ * 1e6)) / 1e9 / 3.5, 1),
                             dram_bytes=b['reqs'] * 64, full_5070_equivalent_us=round(b['cycles'] / MHZ / 192, 2),
                             note='no added DRAM latency'))
            break
    cal = {r['run']: r for r in csv.DictReader(open(os.path.join(T, 'results', 'calibration.csv')))}
    s = cal.get('S1_16M_g1024')
    if s:
        rows.append(dict(source='this work S1 (simulated, results/calibration.csv)', what='stream read 16 MB, 1024 threads',
                         configured_gbs=14.0, cycles=s['cycles'], time_us=round(int(s['cycles']) / MHZ, 1),
                         achieved_gbs=s['achieved_gbs'], pct_of_configured=s['pct_of_configured'], dram_bytes=s['dram_read_bytes'],
                         full_5070_equivalent_us='', note='128 MSHRs, 1024 resident lanes, 4 narrow channels'))
    tot = os.path.join(T, 'results', 'chains_totals.csv')
    if os.path.exists(tot):
        for r in csv.DictReader(open(tot)):
            if r['chain'] == 'chain_q6' and r['config'] == 'S1' and r['sf'] == '0.1':
                us = float(r['sim_time_us'])
                rows.append(dict(source='this work S1 (simulated, results/chains_totals.csv)',
                                 what=f'Q6 SF0.1, {r["launches"]} general kernels, 10 B/row read (2+4+4) + intermediates',
                                 configured_gbs=14.0, cycles=r['cycles'], time_us=us,
                                 achieved_gbs=round(int(r['dram_bytes']) / (us * 1e-6) / 1e9, 3), pct_of_configured=r['pct_bw'],
                                 dram_bytes=r['dram_bytes'], full_5070_equivalent_us=round(us / 48, 2),
                                 note='simulator time only (no host gaps); projection x 1/48 is modeled'))
    with open(os.path.join(T, 'results', 'owner_comparison.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    for r in rows:
        print(r['source'][:40], '|', r['what'][:45], '|', r['time_us'], 'us |', r['achieved_gbs'], 'GB/s |', r['pct_of_configured'], '% |', r['full_5070_equivalent_us'])


if __name__ == '__main__':
    main()
