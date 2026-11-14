# Re-weight coverage classes with real-clock nsys per-(query, kernel function) totals (read-only review script)
import json,collections
src=open('/home/sai/cs254_project/sim/combined/coverage.py').read()
ns={}
exec(src.split('rows = []')[0], ns)
L, classify, SUM = ns['L'], ns['classify'], ns['SUM']
R='/home/sai/cs254_project/tpch_q1_analysis/analysis/results'
ncu_qf=collections.Counter(); real_qf={}
for r in L: ncu_qf[(int(r['q']),r['func'])]+=float(r['nsys_dur_ns'])
for q in range(2,23):
    it=json.load(open(f'{R}/q{q}/nsys_iteration_breakdown.json'))
    acc=collections.Counter()
    for i in it:
        for k,v in i['kernel_ns_by_name'].items(): acc[k]+=v/len(it)
    real_qf[q]=acc
cls=collections.Counter(); ast=0; tot=0; missing=0; clsn=collections.Counter()
fam=collections.Counter()
for r in L:
    q=int(r['q']); f=r['func']; c,_=classify(r)
    d=float(r['nsys_dur_ns']); clsn[c]+=d
    if f not in real_qf[q]: missing+=d; continue
    w=real_qf[q][f]*d/ncu_qf[(q,f)]
    cls[c]+=w; tot+=w; fam[r['family']]+=w
    if c=='E' and r['family'].startswith('AST'): ast+=w
T=sum(clsn.values())
print('ncu-based  E/N/B %:', {k:round(100*v/T,1) for k,v in clsn.items()}, 'total ms',round(T/1e6,2))
print('real-clock E/N/B %:', {k:round(100*v/tot,1) for k,v in cls.items()}, 'total ms',round(tot/1e6,2),'unmatched ncu ns',missing)
print('AST share of E (real):', round(ast/cls['E'],3), ' AST share of all:', round(ast/tot,3))
wall=sum(SUM[q]['warm_ms'] for q in SUM); busy=sum(SUM[q]['gpu_busy_ms'] for q in SUM)
e=cls['E']/1e6
print('wall',wall,'busy',round(busy,2),'bound real E:',round(wall/(wall-e),4),' excl AST:',round(wall/(wall-(cls['E']-ast)/1e6),4))
for k,v in fam.most_common(6): print(' ',k,round(100*v/tot,1))
sortk=sum(v for k,v in fam.items() if k.startswith('sort:'))
print('sort families real %', round(100*sortk/tot,1))
