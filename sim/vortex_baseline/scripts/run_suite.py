#!/usr/bin/env python3
"""Run the operator micro-suite and the Q6/Q1 chains on simx configurations, in parallel, then verify.

  python3 run_suite.py [--force] [--jobs 24] [--only SUBSTR]

Each job runs in runs/ops/<config>/sf<sf>/<op>[_<arg>]/ (own PoCL cache). A job whose run.log already
says DONE is skipped unless --force. After the runs, verify.py checks every result exactly.
"""
import argparse, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vxlog

T = vxlog.ROOT
RUN = '/home/sai/cs254_project/sim/scripts/run_vortex.sh'

MICRO = [('empty', 3), ('pred_i16', None), ('pred_i32', None), ('range_i16', None), ('mask_and', None),
         ('filter_conj', None), ('compact', 1), ('compact', 25), ('compact', 49), ('gather_i32', 1),
         ('gather_i32', 25), ('gather_i64', 1), ('gather_i64', 25), ('cast', None), ('mul', None),
         ('reduce_i32', None), ('reduce_i64', None), ('minmax_i64', None), ('groupby', None), ('probe', 8)]
CHAINS = [('chain_q6', None), ('chain_q1', None)]
# rule 3: does adding warps / cores (same DRAM) change the bound of these kernels?
RULE3_OPS = [('pred_i32', None), ('pred_i16', None), ('gather_i32', 1), ('gather_i32', 25), ('groupby', None),
             ('compact', 25), ('mul', None)]


def jobs():
    J = []
    for sf in ('0.01', '0.1'):
        for op in MICRO + CHAINS:
            J.append(('S1', sf, *op))
    for sf in ('0.01', '0.1'):
        for op in MICRO + CHAINS:
            J.append(('S4', sf, *op))
    for cfg in ('S1_w64', 'S1_c2', 'S1_w16'):
        for op in RULE3_OPS:
            J.append((cfg, '0.1', *op))
    # SF 1 (each run stays under ~10 minutes): Q6 chain on S1 and S4, a few single operators on S1
    J += [('S1', '1', 'chain_q6', None), ('S4', '1', 'chain_q6', None), ('S1', '1', 'pred_i32', None),
          ('S1', '1', 'compact', 25), ('S1', '1', 'gather_i32', 25), ('S1', '1', 'cast', None)]
    return J


def rundir(cfg, sf, op, arg):
    return os.path.join(T, 'runs', 'ops', cfg, f'sf{sf}', op + ('' if arg is None else f'_{arg}'))


def run(job, force):
    cfg, sf, op, arg = job
    d = rundir(*job)
    log = os.path.join(d, 'run.log')
    if not force and os.path.exists(log) and 'DONE' in open(log).read():
        return job, 'skip'
    os.makedirs(d, exist_ok=True)
    c = vxlog.config(cfg)
    cmd = [RUN, cfg, d, os.path.join(T, 'tests/dbops/kernel.cl'), os.path.join(T, 'bin/dbops'),
           '-d', os.path.join(T, 'data', f'sf{sf}'), '-o', d, '-c', str(c['cores']), '-w', str(c['warps']), op]
    if arg is not None:
        cmd.append(str(arg))
    r = subprocess.run(cmd, capture_output=True, text=True)
    return job, f'rc={r.returncode}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--jobs', type=int, default=24)
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    J = [j for j in jobs() if a.only in '/'.join(map(str, j))]
    # longest first (SF 0.1 chains and group-bys)
    J.sort(key=lambda j: (j[1] == '0.01', j[1] != '1', not j[2].startswith(('chain', 'groupby'))))
    with ThreadPoolExecutor(a.jobs) as ex:
        for job, st in ex.map(lambda j: run(j, a.force), J):
            print(*job, st, flush=True)


if __name__ == '__main__':
    main()
