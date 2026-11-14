#!/usr/bin/env python3
"""Writes results/calibration.csv from runs/membw/* and runs/lat/* (see run_calibration.sh)."""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxlog
R = os.path.join(vxlog.ROOT, 'runs')
# (attempt, run dir, config, note)
STREAM = [
    (1, 'S1_g1024', 'S1', 'option C: 4 narrow GDDR6 channels @1750; 4 MB stream, 1024 threads (32 warps), 4 loads in flight per thread'),
    (1, 'S1_g4096', 'S1', 'same, 4096 work-items (4 rounds of the resident 1024)'),
    (1, 'S1_16M_g1024', 'S1', 'same config, 16 MB stream (startup amortised) -- S1 calibration point'),
    (2, 'S1_1ch7000_16M', 'S1_1ch7000', 'alternative: 1 GDDR6 channel @7000 MT/s (same 14 GB/s, fewer banks) -- worse, rejected'),
    (3, 'S1_w16_16M', 'S1_w16', 'sensitivity: 16 warps'),
    (3, 'S1_w64_16M', 'S1_w64', 'sensitivity: 64 warps'),
    (1, 'S4_4M_g4096', 'S4', 'S4: 16 narrow channels @1750; 4 MB stream, 4096 threads'),
    (1, 'S4_16M_g4096', 'S4', 'S4: 16 MB stream -- S4 calibration point'),
]
rows = []
for att, d, cfg, note in STREAM:
    p = os.path.join(R, 'membw', d)
    if not os.path.exists(os.path.join(p, 'launch.log')):
        continue
    c = vxlog.config(cfg)
    L = vxlog.launches(p)[0]
    n = int(open(os.path.join(p, 'cmd.txt')).read().split('-n')[1].split()[0])
    req = n * 8
    sec = L['run_cycles'] / (c['clock_mhz'] * 1e6)
    gbs = req / sec / 1e9
    ram = vxlog.ramulator(p)
    rows.append(dict(attempt=att, kind='stream', run=d, config=cfg, cores=c['cores'], warps=c['warps'],
                     channels=c['channels'], data_rate=c['data_rate'], configured_gbs=c['peak_gbs'],
                     bytes_requested=req, dram_read_bytes=L['run_mem_reads'] * 64, cycles=L['run_cycles'],
                     achieved_gbs=round(gbs, 3), pct_of_configured=round(100 * gbs / c['peak_gbs'], 1),
                     row_hit_pct=ram.get('row_hit_pct', ''), latency_cycles='', latency_ns='',
                     passed=vxlog.passed(p), wall_s=vxlog.wall(p)[0], note=note))
for cfg in ('S1', 'S4'):
    a, b = os.path.join(R, 'lat', f'{cfg}_n256'), os.path.join(R, 'lat', f'{cfg}_n1280')
    if not (os.path.exists(a) and os.path.exists(b)):
        continue
    c = vxlog.config(cfg)
    lat = (vxlog.launches(b)[0]['run_cycles'] - vxlog.launches(a)[0]['run_cycles']) / 1024
    rows.append(dict(attempt=1, kind='latency', run=f'{cfg}_n256/n1280', config=cfg, cores=c['cores'], warps=c['warps'],
                     channels=c['channels'], data_rate=c['data_rate'], configured_gbs=c['peak_gbs'],
                     bytes_requested='', dram_read_bytes='', cycles='', achieved_gbs='', pct_of_configured='',
                     row_hit_pct=vxlog.ramulator(b).get('row_hit_pct', ''), latency_cycles=round(lat, 1),
                     latency_ns=round(lat / c['clock_mhz'] * 1000, 1), passed=vxlog.passed(b), wall_s=vxlog.wall(b)[0],
                     note='pointer chase over 32 MB, 4 KB apart; (cycles(1280 loads)-cycles(256 loads))/1024; target 858 cyc @2.866 GHz = 299 ns = 752 cyc @2.512 GHz; PLATFORM_MEMORY_LATENCY=503 (518 gave 767 cyc)'))
out = os.path.join(vxlog.ROOT, 'results', 'calibration.csv')
with open(out, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
for r in rows:
    print(r['run'], r['configured_gbs'], r['achieved_gbs'], r['pct_of_configured'], r['row_hit_pct'], r['latency_cycles'], r['latency_ns'])
