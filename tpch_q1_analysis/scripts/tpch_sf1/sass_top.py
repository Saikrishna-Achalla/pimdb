"""Per-instruction SASS hotspots for the top kernel families (by warm GPU time) that have --set full data.

Usage: python3 -I sass_top.py <results_dir> [n_families=2]
For each family, takes its longest launch and exports `ncu --page source --print-source sass --csv` for exactly that
launch from the report it came from (src_report in ncu_warm_metrics.json). The launch is selected on import by its
exact mangled name (--kernel-name-base mangled -k regex:^<mangled>$) and its index among same-name kernels in THAT
report (-s idx -c 1); the selection is verified by re-exporting gpu__time_duration and comparing with the metrics JSON
(launch order differs between ncu runs, so a position in the light report must never be used to address the families report).
Writes sass/<func>_pos<P>_source.csv, then sass_hotspots.py -> sass/<func>_hotspots.txt + sass/<func>_inst_inventory.csv.
"""
import collections, csv, io, json, os, re, subprocess, sys

R = sys.argv[1]; NF = int(sys.argv[2]) if len(sys.argv) > 2 else 2
HERE = os.path.dirname(os.path.abspath(__file__))
NCU = "/usr/local/cuda/bin/ncu"
M = json.load(open(f"{R}/ncu_warm_metrics.json")); K = M["kernels"]
fam = collections.defaultdict(float)
for k in K:
    if k["has_full"]:
        fam[k["func"]] += k["dur_ns"]
tot = sum(k["dur_ns"] for k in K)
for func, t in sorted(fam.items(), key=lambda kv: -kv[1])[:NF]:
    ks = [k for k in K if k["func"] == func]
    top = max((k for k in ks if k["has_full"]), key=lambda k: k["dur_ns"])
    rep = f"{R}/profiles/{top['src_report']}"
    idx = sum(1 for k in K if k.get("src_report") == top["src_report"] and k["mangled"] == top["mangled"]
              and k["src_index"] < top["src_index"])
    sel = ["--kernel-name-base", "mangled", "-k", f"regex:^{re.escape(top['mangled'])}$", "-s", str(idx), "-c", "1"]
    chk = subprocess.run([NCU, "--import", rep, "--page", "raw", "--csv", "--print-units", "base",
                          "--metrics", "gpu__time_duration.sum"] + sel, capture_output=True, text=True, check=True).stdout
    got = list(csv.DictReader(io.StringIO("\n".join(l for l in chk.splitlines() if l.startswith('"')))))[1:]
    if len(got) != 1 or abs(float(got[0]["gpu__time_duration.sum"].replace(",", "")) - top["dur_ns"]) > 0.5:
        sys.exit(f"ERROR: SASS export selection for {func} pos {top['pos']} picked {len(got)} kernel(s) "
                 f"{[g['gpu__time_duration.sum'] for g in got]} instead of the {top['dur_ns']} ns launch")
    src = f"{R}/sass/{func}_pos{top['pos']}_source.csv"
    with open(src, "w") as fo:
        subprocess.run([NCU, "--import", rep, "--page", "source", "--print-source", "sass", "--csv"] + sel, stdout=fo, check=True)
    out = subprocess.run([sys.executable, "-I", f"{HERE}/sass_hotspots.py", src, f"{R}/sass/{func}"],
                         capture_output=True, text=True, check=True).stdout
    hdr = (f"# {func}: family {t/1e3:.1f} us ({100*t/tot:.1f}% of warm GPU time, {len(ks)} launches); "
           f"hotspots for its longest launch pos {top['pos']} ({top['dur_ns']/1e3:.1f} us, grid {top['grid']}, block {top['block']}; "
           f"{top['src_report']} row {top['src_index']}, selection verified by duration)\n"
           f"# {top['name'][:300]}\n")
    open(f"{R}/sass/{func}_hotspots.txt", "w").write(hdr + out)
    print(hdr + out)
