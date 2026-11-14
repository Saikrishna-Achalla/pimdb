"""Fail if any profiled warm-iteration kernel touched system (host) memory through the GPU's L2/sysmem aperture.

Usage: python3 -I check_sysmem.py <results_dir>
Why: Sirius' pinned-host pools are device-mapped (cudaHostAllocMapped / cudaHostRegisterMapped in cucascade), so a
kernel can read or write host memory in place over PCIe with NO memcpy record; nsys memcpy tables cannot see that.
For every kernel in every profiles/*_warm_*.ncu-rep this requires 0 for
  syslts__t_sectors_srcunit_tex_aperture_sysmem_lookup_miss.sum   (REQUIRED; all ops; in the 1-pass light set too)
  ..._op_{read,write,atom,red}_lookup_miss.sum                     (checked when present: --set full reports)
(every SM global load/store/atomic goes through L1TEX, so these see any in-place access to mapped host memory).
Recorded but NOT checked: syslts__t_sectors_aperture_sysmem_lookup_miss.sum (all source units). On Q2/Q3 it is
265-292 sectors for every kernel, tiny or large, while the SM (tex) part is 0: it is per-launch traffic of non-SM
units (front end / ncu), not data access. Also recorded: pcie__{read,write}_bytes (ncu exposes only .sum.per_second;
bytes = rate x duration; includes driver/ncu traffic).
A missing metric is a FAIL (the report cannot prove anything). Writes ncu_sysmem_check.{json,txt}; exit 1 on failure.
Test hook: SYSMEM_RAW_CSV=<file> uses that `ncu --import ... --page raw --csv` text for every report (negative tests).
"""
import csv, glob, io, json, os, subprocess, sys

R = sys.argv[1]
NCU = "/usr/local/cuda/bin/ncu"
SECT = ["syslts__t_sectors_srcunit_tex_aperture_sysmem_lookup_miss.sum"] + \
       [f"syslts__t_sectors_srcunit_tex_aperture_sysmem_op_{o}_lookup_miss.sum" for o in ("read", "write", "atom", "red")]
ALLSRC = "syslts__t_sectors_aperture_sysmem_lookup_miss.sum"
RATE = ["pcie__read_bytes.sum.per_second", "pcie__write_bytes.sum.per_second"]


def num(v):
    try:
        return float(v.replace(",", ""))
    except (ValueError, AttributeError):
        return None


res, ok_all = [], True
reps = sorted(glob.glob(f"{R}/profiles/*_warm_*.ncu-rep"))
for rep in reps:
    out = open(os.environ["SYSMEM_RAW_CSV"]).read() if os.environ.get("SYSMEM_RAW_CSV") else \
        subprocess.run([NCU, "--import", rep, "--page", "raw", "--csv", "--print-units", "base",
                        "--metrics", ",".join(SECT + RATE + [ALLSRC, "gpu__time_duration.sum"])],
                       capture_output=True, text=True, check=True).stdout
    rows = list(csv.DictReader(io.StringIO("\n".join(l for l in out.splitlines() if l.startswith('"')))))[1:]
    missing = [m for m in SECT[:1] if not rows or m not in rows[0]]
    nz, sect_tot, pcie_r, pcie_w = [], 0.0, 0.0, 0.0
    allsrc = sorted({num(r.get(ALLSRC, "")) for r in rows} - {None})
    for r in rows:
        v = {m: num(r.get(m, "")) for m in SECT if m == SECT[0] or m in r}
        if v.get(SECT[0]) is None:
            missing = sorted(set(missing) | {SECT[0]})
        s = sum(x or 0 for x in v.values()); sect_tot += s
        if s > 0:
            nz.append({"id": r["ID"], "name": r["Kernel Name"][:120], **{m.split("aperture_sysmem_")[-1]: x for m, x in v.items() if x}})
        d = (num(r.get("gpu__time_duration.sum", "")) or 0) * 1e-9
        pcie_r += (num(r.get(RATE[0], "")) or 0) * d; pcie_w += (num(r.get(RATE[1], "")) or 0) * d
    ok = bool(rows) and not missing and not nz
    ok_all &= ok
    res.append({"report": os.path.basename(rep), "kernels": len(rows), "ok": ok, "missing_metrics": missing,
                "kernels_with_sysmem_sectors": nz[:20], "n_kernels_with_sysmem_sectors": len(nz),
                "sysmem_sectors_total": sect_tot,
                "info_all_source_sysmem_sectors_per_kernel": [allsrc[0], allsrc[-1]] if allsrc else None, "pcie_read_bytes_est": pcie_r, "pcie_write_bytes_est": pcie_w})
ok_all &= bool(reps)
json.dump({"ok": ok_all, "reports": res}, open(f"{R}/ncu_sysmem_check.json", "w"), indent=1)
txt = "\n".join(f"{r['report']}: {r['kernels']} kernels, {r['n_kernels_with_sysmem_sectors']} with SM (tex) sysmem-aperture sectors "
                f"(total {r['sysmem_sectors_total']:.0f}); all-source sysmem sectors per kernel min/max "
                f"{r['info_all_source_sysmem_sectors_per_kernel']} (info only); missing metrics {r['missing_metrics'] or 'none'}; "
                f"pcie__read/write_bytes (rate x duration, includes driver/ncu traffic) {r['pcie_read_bytes_est']:.0f} / "
                f"{r['pcie_write_bytes_est']:.0f} B -> {'PASS' if r['ok'] else 'FAIL'}" for r in res) or "no reports found -> FAIL"
open(f"{R}/ncu_sysmem_check.txt", "w").write(txt + "\n"); print(txt)
sys.exit(0 if ok_all else 1)
