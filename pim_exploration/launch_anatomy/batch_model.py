"""Model the number of scan batches Sirius creates per pinned table (modeled, checked against the traces).

Rule (sirius source): scan batches are row groups coalesced greedily up to operator_params.scan_task_batch_size
(parquet_scan_core.cpp:415-460 parquet_batch_coalescer). The default batch size is
min(derived_default_batch_size(), gpu_capacity/40) when the YAML sets a GPU usage limit (sirius_config.cpp:774-791,
990), derived_default_batch_size() = clamp(totalGlobalMem/40, 512 MiB, 5 GiB) (sirius_config.cpp:46-66).
hash_partition_bytes and concat_batch_bytes default to the same value (sirius_config.hpp:56-58).
Decoded bytes per row group are approximated by parquet total_uncompressed_size of the pinned columns
(plain-encoded strings ~ chars + 4-byte lengths, like cuDF chars + offsets).

Usage: <pixi python with pyarrow> -I batch_model.py   -> batch_model.json
"""
import glob, json, os, re
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
RES = "/home/sai/cs254_project/tpch_q1_analysis/analysis/results"
DATA = "/home/sai/cs254_project/sirius/test_datasets"
TOTAL = 12344164352  # TARGET_INFO_GPU.totalMemory, RTX 5070
CAPS = {"sf1_config_usage0.25": min(max(TOTAL // 40, 512 << 20), int(0.25 * TOTAL) // 40),
        "q1_config_usage0.85": min(max(TOTAL // 40, 512 << 20), int(0.85 * TOTAL) // 40),
        "no_usage_limit": max(TOTAL // 40, 512 << 20)}


WIDTH = {"INT32": 4, "INT64": 8, "FLOAT": 4, "DOUBLE": 8, "BOOLEAN": 1}


def rg_bytes(path, cols):
    """Decoded (cuDF) bytes per row group: fixed width = physical width x rows; strings = chars + 4 B offsets."""
    f = pq.ParquetFile(path)
    m = f.metadata
    names = [m.schema.column(i).name for i in range(m.num_columns)]
    out = []
    for r in range(m.num_row_groups):
        rg = m.row_group(r)
        b = 0
        strs = []
        for i, n in enumerate(names):
            if n in cols:
                pt = m.schema.column(i).physical_type
                if pt in WIDTH:
                    b += WIDTH[pt] * rg.num_rows
                else:
                    strs.append(n)
        if strs:
            t = f.read_row_group(r, columns=strs)
            import pyarrow.compute as pc
            for n in strs:
                b += int(pc.sum(pc.binary_length(t.column(n))).as_py() or 0) + 4 * rg.num_rows
        out.append((rg.num_rows, b))
    return out


def pack(rgs, cap):
    n, acc = 0, 0
    for rows, b in rgs:
        if acc and acc + b > cap:
            n += 1
            acc = 0
        acc += b
    return n + (1 if acc else 0)


res = {"caps_bytes": CAPS, "queries": {}}
for q in range(2, 23):
    sql = open(glob.glob(f"{RES}/q{q}/sql/q{q}_nsys.sql")[0]).read()
    tabs = {}
    for path, name, cols in re.findall(r"pin_table\('([^']+)', tier='gpu', name='(\w+)', cols=\[([^\]]*)\]", sql):
        cl = re.findall(r"'(\w+)'", cols)
        files = glob.glob(path)
        rgs = []
        for f in files:
            rgs += rg_bytes(f, set(cl))
        tabs[name] = {"cols": cl, "rows": sum(r for r, _ in rgs), "row_groups": len(rgs),
                      "decoded_MB": round(sum(b for _, b in rgs) / 1e6, 1),
                      **{f"batches_{k}": pack(rgs, v) for k, v in CAPS.items()}}
    res["queries"][q] = tabs
# Q1 at SF10 (columns of the Q1 study)
q1cols = ["l_returnflag", "l_linestatus", "l_quantity", "l_extendedprice", "l_discount", "l_tax", "l_shipdate"]
rgs = []
for f in glob.glob(f"{DATA}/tpch_parquet_sf10/lineitem/*.parquet") or glob.glob(f"{DATA}/tpch_parquet_sf10/lineitem.parquet"):
    rgs += rg_bytes(f, set(q1cols))
res["q1_sf10_lineitem"] = {"row_groups": len(rgs), "decoded_MB": round(sum(b for _, b in rgs) / 1e6, 1),
                           **{f"batches_{k}": pack(rgs, v) for k, v in CAPS.items()}}
json.dump(res, open(f"{HERE}/batch_model.json", "w"), indent=1)
print("caps:", {k: round(v / 2**20, 1) for k, v in CAPS.items()}, "MiB")
for q, tabs in res["queries"].items():
    print(q, {t: (d["decoded_MB"], d["row_groups"], d["batches_sf1_config_usage0.25"], d["batches_no_usage_limit"])
              for t, d in tabs.items() if d["batches_sf1_config_usage0.25"] > 1 or d["row_groups"] > 1})
print("q1 sf10:", res["q1_sf10_lineitem"])
