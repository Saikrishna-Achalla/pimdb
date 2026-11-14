#!/usr/bin/env python3
"""Build the markdown tables of UNROLL_STUDY.md from unroll_study_results.txt, ncu_study/*_table.txt and the SASS dump."""
import re,collections
res=collections.OrderedDict(); spec=None
for l in open('unroll_study_results.txt'):
    m=re.search(r"cols=(\S+)",l)
    if m: spec=m.group(1); res[spec]=collections.OrderedDict(); continue
    m=re.match(r"(.{26}) +(\d+) +([\d.]+) +([\d.]+) +([\d.]+) +([\d.]+)x +([\d.]+)% (\w+)",l)
    if m: res[spec][m.group(1).strip()]=dict(regs=int(m.group(2)),us=float(m.group(3)),gbs=float(m.group(5)),sp=float(m.group(6)),fl=float(m.group(7)))
def ncu(spec):
    d={}
    for l in open(f'ncu_study/{spec}_all_table.txt').read().splitlines()[1:]:
        n=l[:26].strip(); f=l[26:].split()
        d[n]=dict(us=float(f[1]),gbs=float(f[2]),occ=float(f[4]),waves=float(f[5]),inst=int(f[6]),lsb=float(f[7]),ssb=float(f[8]),bar=float(f[9]))
    return d
size={}; fn=None
for l in open('sass_study/unroll_study.sass',errors='replace'):
    m=re.search(r"Function : (\S+)",l)
    if m: fn=m.group(1); size[fn]=0; continue
    if fn and re.match(r"\s+/\*[0-9a-f]{4,}\*/",l): size[fn]+=16
def mang(U,MAP,CU,TAIL,SLOT,MINB,SUB,P): return f"_Z9us_kernelILi{U}ELi{MAP}ELi{CU}ELi{TAIL}ELi{SLOT}ELi{MINB}ELi{SUB}ELi{P}EEviPKi4ColsPKS2_Px"
cs={"baseline":"_Z11us_baselineILi0EEviPKi4ColsPKS2_Px","gdesc baseline":"_Z11us_baselineILi1EEviPKi4ColsPKS2_Px",
    "naive pragma rows U=4":"_Z13us_naive_rowsILi4ELi0EEviPKi4ColsPKS2_Px","naive pragma cols N=4":"_Z13us_naive_colsILi4ELi0EEviPKi4ColsPKS2_Px","naive pragma grid U=4":"_Z13us_naive_gridILi4ELi0EEviPKi4ColsPKS2_Px"}
for U in (1,2,3,4,6,8,12,16,24,32):
    cs[f"rows U={U} warp"]=mang(U,0,1,0,0,0,0,0)
    if U<=16: cs[f"gdesc rows U={U} warp"]=mang(U,0,1,0,0,0,0,1)
for U in (2,4,8,16):
    cs[f"rows U={U} thread"]=mang(U,1,1,0,0,0,0,0); cs[f"rows U={U} threadvec rem"]=mang(U,3,1,1,0,0,0,0)
for U in (2,4,8): cs[f"rows U={U} grid"]=mang(U,2,1,0,0,0,0,0)
for U in (4,8): cs[f"rows U={U} warp rem"]=mang(U,0,1,1,0,0,0,0); cs[f"rows U={U} warp lazyslot"]=mang(U,0,1,0,1,0,0,0); cs[f"rows U={U} warp defslot"]=mang(U,0,1,0,2,0,0,0)
cs["cols CU=2 (U=1)"]=mang(1,0,2,0,0,0,0,0); cs["cols CU=4 (U=1)"]=mang(1,0,4,0,0,0,0,0); cs["cols ALL (U=1)"]=mang(1,0,0,0,0,0,0,0)
cs["both U=2 x ALL"]=mang(2,0,0,0,0,0,0,0); cs["both U=2 x ALL defslot"]=mang(2,0,0,0,2,0,0,0); cs["both U=4 x CU=2"]=mang(4,0,2,0,0,0,0,0); cs["both U=4 x CU=4"]=mang(4,0,4,0,0,0,0,0)
cs["gdesc rows U=4 warp rem"]=mang(4,0,1,1,0,0,0,1); cs["gdesc rows U=4 threadvec"]=mang(4,3,1,1,0,0,0,1); cs["gdesc rows U=8 threadvec"]=mang(8,3,1,1,0,0,0,1)
cs["gdesc cols ALL (U=1)"]=mang(1,0,0,0,0,0,0,1); cs["gdesc cols CU=4 (U=1)"]=mang(1,0,4,0,0,0,0,1); cs["gdesc both U=4 x CU=2"]=mang(4,0,2,0,0,0,0,1)
cs["rows U=16 warp minb5"]=mang(16,0,1,0,0,5,0,0)
for k,v in cs.items(): assert v in size,(k,v)
out=[]
def main(spec, sel):
    r=res[spec]; n=ncu(spec)
    out.append(f"\n**{spec}**\n")
    out.append("| variant | regs | code KB | us | GB/s | speedup | % of 672 | ncu us | ncu DRAM GB/s | occ % | long_sb % |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for v in sel:
        a=r[v]; b=n[v]; sz=f"{size[cs[v]]/1024:.1f}" if v in cs else "-"
        out.append(f"| {v} | {a['regs']} | {sz} | {a['us']:.1f} | {a['gbs']:.1f} | {a['sp']:.2f}x | {a['fl']:.1f} | {b['us']:.1f} | {b['gbs']:.1f} | {b['occ']:.1f} | {b['lsb']:.1f} |")
selL=["baseline","naive pragma rows U=4","naive pragma grid U=4","naive pragma cols N=4","rows U=1 warp","rows U=2 warp","rows U=3 warp","rows U=4 warp","rows U=6 warp","rows U=8 warp","rows U=12 warp","rows U=16 warp","rows U=24 warp","rows U=32 warp","rows U=16 warp minb5","rows U=2 thread","rows U=4 thread","rows U=8 thread","rows U=16 thread","rows U=2 threadvec rem","rows U=4 threadvec rem","rows U=8 threadvec rem","rows U=16 threadvec rem","rows U=2 grid","rows U=4 grid","rows U=8 grid","rows U=4 warp rem","rows U=8 warp rem","rows U=4 warp lazyslot","rows U=8 warp lazyslot","rows U=4 warp defslot","cols CU=2 (U=1)","cols CU=4 (U=1)","cols ALL (U=1)","both U=4 x CU=2","both U=4 x CU=4","both U=2 x ALL","both U=2 x ALL defslot","gdesc baseline","gdesc rows U=2 warp","gdesc rows U=3 warp","gdesc rows U=4 warp","gdesc rows U=6 warp","gdesc rows U=8 warp","gdesc rows U=12 warp","gdesc rows U=16 warp","gdesc rows U=4 warp rem","gdesc rows U=4 threadvec","gdesc rows U=8 threadvec","gdesc cols CU=4 (U=1)","gdesc cols ALL (U=1)","gdesc both U=4 x CU=2"]
main("LLLLL",selL); main("IIIII",selL)
specs=["L","LL","LLLLL","LLLLLLL","I","II","IIIII","IIIIIII","IIL","LLLLLCC","LLLLICC"]
for fam,base in (("","baseline"),("gdesc ","gdesc baseline")):
    out.append(f"\nU sweep, `{fam}rows U=<U> warp`: median us (speedup vs `{base}`)\n")
    out.append("| U | regs | "+" | ".join(specs)+" |"); out.append("|---|---:|"+"---:|"*len(specs))
    out.append(f"| {base} | {res['L'][base]['regs']} | "+" | ".join(f"{res[s][base]['us']:.1f}" for s in specs)+" |")
    for U in (1,2,3,4,6,8,12,16,24,32):
        v=f"{fam}rows U={U} warp"
        if v not in res['L']: continue
        out.append(f"| {U} | {res['L'][v]['regs']} | "+" | ".join(f"{res[s][v]['us']:.1f} ({res[s][base]['us']/res[s][v]['us']:.2f}x)" for s in specs)+" |")
    out.append("| floor @672 GB/s | | "+" | ".join(f"{res[s]['baseline']['us']*res[s]['baseline']['fl']/100:.1f}" for s in specs)+" |")
out.append("\nOther knobs across column specs: median us\n")
sel2=["baseline","rows U=4 warp","rows U=8 warp","rows U=4 warp rem","rows U=8 warp rem","rows U=4 warp lazyslot","rows U=8 warp lazyslot","rows U=4 warp defslot","rows U=8 warp defslot","rows U=4 thread","rows U=8 thread","rows U=4 threadvec rem","rows U=8 threadvec rem","rows U=4 grid","rows U=8 grid","rows U=8 warp sub64=4","cols CU=2 (U=1)","cols CU=4 (U=1)","cols ALL (U=1)","cols ALL (U=1) defslot","both U=4 x CU=2","both U=2 x ALL","both U=2 x ALL defslot","gdesc baseline","gdesc rows U=4 warp","gdesc rows U=8 warp","gdesc rows U=4 warp rem","gdesc rows U=4 threadvec","gdesc rows U=8 threadvec","gdesc cols CU=4 (U=1)","gdesc cols ALL (U=1)","gdesc both U=2 x ALL","gdesc both U=4 x CU=2"]
out.append("| variant | regs | "+" | ".join(specs)+" |"); out.append("|---|---:|"+"---:|"*len(specs))
for v in sel2: out.append(f"| {v} | {res['L'][v]['regs']} | "+" | ".join(f"{res[s][v]['us']:.1f}" for s in specs)+" |")
print("\n".join(out))
