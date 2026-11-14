"""How much of the same-thread round-trip intermediate traffic comes from producers that write more than the 48 MB L2
(only those can be forced to DRAM in a warm run; smaller ones may be served from L2). Reads dataflow_q*.json."""
import glob, json, os, collections
H = os.path.dirname(os.path.abspath(__file__))
L2 = 48e6
tot = big = n = nb = 0; per = collections.Counter()
for f in sorted(glob.glob(f"{H}/dataflow_q*.json")):
    d = json.load(open(f))
    for e in d["edges_subop_level"]:
        if e["kind"] != "same-thread":
            continue
        tot += e["roundtrip"]; n += 1
        if e["wr_src"] > L2:
            big += e["roundtrip"]; nb += 1; per[d["q"]] += e["roundtrip"]
print(f"same-thread edges {n}; producer writes > 48 MB: {nb} edges, {big/1e6:.1f} MB of {tot/1e6:.1f} MB round-trip ({100*big/tot:.1f}%); by query {dict((q, round(v/1e6,1)) for q, v in per.items())}")
