"""Parsers for simx run directories (launch.log from vortex_launch_log.patch, ramulator.stats.log, configs)."""
import json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
LINE_B = 64  # VX_CFG_MEM_BLOCK_SIZE: one DRAM request = one 64 B line


def config(name):
    for d in ('configs', 'configs/calib'):
        p = os.path.join(ROOT, d, name + '.json')
        if os.path.exists(p):
            c = json.load(open(p))
            m = {}
            for s in ('core', 'chip', 'platform'):
                m.update(c[s])
            return {
                'name': name,
                'cores': m['VX_CFG_NUM_CORES'] * m.get('VX_CFG_NUM_CLUSTERS', 1),
                'warps': m['VX_CFG_NUM_WARPS'], 'threads': m['VX_CFG_NUM_THREADS'],
                'clock_mhz': m['VX_CFG_PLATFORM_CLOCK_RATE'],
                'channels': m['VX_CFG_PLATFORM_MEMORY_NUM_BANKS'],
                'data_rate': m['VX_CFG_PLATFORM_MEMORY_DATA_RATE'],
                # GDDR6 x16 channel moves 2 B per transfer
                'peak_gbs': m['VX_CFG_PLATFORM_MEMORY_NUM_BANKS'] * 2 * m['VX_CFG_PLATFORM_MEMORY_DATA_RATE'] / 1000.0,
                'raw': m,
            }
    raise FileNotFoundError(name)


def launches(rundir):
    """One dict per kernel launch: run_* = the kernel itself, flush_* = the cache write-back the runtime
    issues after every launch (summed over its per-core flush calls). Counters in RUN lines are already
    per launch: cycles/instrs are differenced inside the patch, memory and L2 counters reset at each launch."""
    out = []
    for line in open(os.path.join(rundir, 'launch.log')):
        kind, *kv = line.split()
        d = {k: int(v) for k, v in (x.split('=') for x in kv)}
        if kind == 'RUN':
            out.append({'run_' + k: v for k, v in d.items()} | {'flush_cycles': 0, 'flush_mem_reads': 0, 'flush_mem_writes': 0})
        elif kind == 'FLUSH' and out:
            for k, v in d.items():
                out[-1]['flush_' + k] += v
    for L in out:
        L['cycles'] = L['run_cycles'] + L['flush_cycles']
        L['dram_reads'] = L['run_mem_reads'] + L['flush_mem_reads']
        L['dram_writes'] = L['run_mem_writes'] + L['flush_mem_writes']
        L['dram_bytes'] = (L['dram_reads'] + L['dram_writes']) * LINE_B
    return out


def ramulator(rundir):
    """Row-buffer statistics summed over channels for the whole process (Ramulator prints only at exit)."""
    p = os.path.join(rundir, 'ramulator.stats.log')
    if not os.path.exists(p):
        return {}
    s = {'row_hits': 0, 'row_misses': 0, 'row_conflicts': 0, 'read_row_hits': 0, 'read_row_misses': 0,
         'read_row_conflicts': 0}
    for line in open(p):
        m = re.match(r'\s*(row_hits|row_misses|row_conflicts|read_row_hits|read_row_misses|read_row_conflicts)_\d+:\s*(\d+)', line)
        if m:
            s[m.group(1)] += int(m.group(2))
    tot = s['row_hits'] + s['row_misses'] + s['row_conflicts']
    s['row_hit_pct'] = round(100.0 * s['row_hits'] / tot, 1) if tot else ''
    return s


def wall(rundir):
    m = re.search(r'wall_s=([\d.]+) rc=(\d+)', open(os.path.join(rundir, 'run.log')).read())
    return (float(m.group(1)), int(m.group(2))) if m else (None, None)


def passed(rundir):
    t = open(os.path.join(rundir, 'run.log')).read()
    return 'PASSED' in t and 'FAILED' not in t
