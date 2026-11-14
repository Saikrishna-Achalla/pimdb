"""Ten PIM-relevant groups of families (grouping is my choice; see GROUPS) -> top10_groups.csv.
nsys time share and ncu DRAM read/write bytes are separate columns (never combined)."""
import csv, collections, os
D = os.path.dirname(os.path.abspath(__file__))
fam = {r['family']: r for r in csv.DictReader(open(f'{D}/kernel_families.csv'))}
G = collections.OrderedDict([
 ('G1 gather fixed-width (1-16 B, index column)', lambda f: f.startswith('transform: gather')),
 ('G2 dyn-filter / semi-join membership probe', lambda f: 'membership' in f),
 ('G3 boolean-mask compaction (+ position scan)', lambda f: f.startswith('cub select') or f.startswith('cub scan: int') or f.startswith('cub scan: long')),
 ('G4 string gather (chars + offsets scan)', lambda f: f.startswith('strings: gather') or f.startswith('cub scan: string') or f.startswith('cub scan: constant')),
 ('G5 hash build / insert (join, filter, group-key map, csr, bloom)', lambda f: ('insert' in f) or f.startswith('csr join: build') or 'bloom-filter add' in f or 'mapping_indices' in f or 'hash-table init' in f),
 ('G6 hash probe (join find/contains/csr, dict encode)', lambda f: f in ('cuco: hash-join probe find','cuco: semi-join probe contains','csr join: probe count','csr join: retrieve','transform: dictionary encode (cuco set find)')),
 ('G7 group-by aggregate (atomic update)', lambda f: 'group-by hash aggregate' in f or 'single_pass_shmem' in f or 'reduce-by-key' in f or 'hyperloglog' in f or 'dense-count' in f),
 ('G8 element-wise map (compare/add/mul/cast/fill)', lambda f: f.startswith('for_each: binop') or f.startswith('transform: cast') or f.startswith('transform: fill') or f.startswith('transform: misc') or f.startswith('transform: datetime') or f.startswith('copy')),
 ('G9 AST expression (compute_column)', lambda f: f.startswith('AST compute_column')),
 ('G10 sort (merge/radix/top-k) + reduce', lambda f: f.startswith('sort:') or f.startswith('cub reduce: block')),
])
tot_t = sum(float(r['nsys_total_us']) for r in fam.values()); tot_b = sum(float(r['ncu_dram_total_B']) for r in fam.values())
rows = []; seen = collections.Counter()
for g, fn in G.items():
    m = [r for f, r in fam.items() if fn(f)]
    for r in m: seen[r['family']] += 1
    rows.append(dict(group=g, families=len(m), launches=sum(int(r['launches']) for r in m),
        nsys_total_us=sum(float(r['nsys_total_us']) for r in m), nsys_time_share=sum(float(r['nsys_total_us']) for r in m)/tot_t,
        ncu_dram_rd_MB=sum(float(r['ncu_dram_rd_total_B']) for r in m)/1e6, ncu_dram_wr_MB=sum(float(r['ncu_dram_wr_total_B']) for r in m)/1e6,
        ncu_dram_share=sum(float(r['ncu_dram_total_B']) for r in m)/tot_b, tiers=' '.join(sorted(set(r['tier'] for r in m)))))
dup = [f for f, c in seen.items() if c > 1]
print('families in >1 group:', dup, '| families in no group:', [f for f in fam if f not in seen])
w = csv.DictWriter(open(f'{D}/top10_groups.csv', 'w', newline=''), fieldnames=list(rows[0])); w.writeheader()
for r in rows:
    w.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}); print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()})
