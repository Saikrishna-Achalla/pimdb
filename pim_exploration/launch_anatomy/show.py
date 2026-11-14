"""Print the attribution of one query task by task (reads launch_attribution.json). Usage: python -I show.py <q>"""
import collections, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
AB = {'transform_kernel': 'T', 'static_kernel': 'F', 'DeviceCompactInitKernel': 'Ci', 'DeviceSelectSweepKernel': 'Cs',
      'DeviceScanInitKernel': 'Si', 'DeviceScanKernel': 'S', 'gather_chars_fn_char_parallel': 'Gc',
      'gather_chars_fn_string_parallel': 'Gs', 'insert_if_n': 'INS', 'find_if_n': 'FIND', 'contains_if_n': 'CONT',
      'DeviceReduceKernel': 'R', 'DeviceReduceSingleTileKernel': 'R1', 'single_thread_kernel': 'st',
      'compute_column_kernel': 'AST', 'fused_membership_mask_kernel': 'MEMB', 'mapping_indices_kernel': 'MAP',
      'single_pass_shmem_aggs_kernel': 'SHAGG', 'add_if_shmem': 'HLL', 'DeviceMergeSortBlockSortKernel': 'MSb',
      'DeviceMergeSortPartitionKernel': 'MSp', 'DeviceMergeSortMergeKernel': 'MSm', 'init_found_pos_pointer': 'fi',
      'find_kernel': 'FK', '_kernel_agent': 'AG', 'copy_range_kernel': 'CR', 'DeviceTopKKernel': 'TK'}
R = {'main': 'D', 'pass': 'M', 'column': 'C', 'init': 'B'}
q = sys.argv[1]
A = json.load(open(f"{HERE}/launch_attribution.json"))[q]
by = collections.defaultdict(list)
for key, v in A["instances"].items():
    for x in v["launches"]:
        by[x["task"]].append((x["t_launch"], key, x))
for t in sorted(by):
    L = sorted(by[t])
    print(f"task {t} T{L[0][2]['thread']} batch{L[0][2]['batch']} conf={L[0][2]['confidence']}")
    cur = None
    line = []
    for _, key, x in L:
        if key != cur:
            if line:
                print(f"    {cur:38s} {' '.join(line)}")
            cur, line = key, []
        line.append(f"{AB.get(x['short'], x['short'][:12])}:{x['family'][:4]}/{R[x['role']]}{'*' if x['cause']=='per-batch' else ''}")
    print(f"    {cur:38s} {' '.join(line)}")
