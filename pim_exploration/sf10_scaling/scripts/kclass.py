"""Query-generic kernel-name helpers shared by the tpch_sf1 scripts.

func_base(name) -> function base name (what `ncu --kernel-name-base function` matches), e.g. "transform_kernel".
phase(name)     -> coarse phase (one of PHASES).
operator(name)  -> finer operator label (prefixed by its phase).
Rules look at the FULL demangled name including template arguments, not only the function name; order matters (first
match wins). Consequence: a generic kernel is attributed to the operator that instantiated it, e.g. the 41
`DeviceScanKernel<... strings::string_offsets_fn ...>` launches of Q2 count under "gather/copy/concat" (string gather
offsets), not under "cub scan/select/reduce".
"""
import re

PHASES = ["parquet decode", "scan/filter", "hash join build", "hash join probe", "hash group-by/agg",
          "sort/top-N", "expression eval", "gather/copy/concat", "string ops", "cub scan/select/reduce", "other"]
# Parquet decode / decompression kernels (shared with pcie_verify.py). Matched on the FULL demangled name.
DECODE = re.compile(r"parquet|unsnap|snappy|nvcomp|decompress|inflate|zstd|brotli|lz4|PageInfo|decode_page|gpuDecode|DeltaBinary", re.I)


def func_base(name):
    s = re.sub(r"^void\s+", "", name.strip())
    out, depth = [], 0  # drop template args <...> and the parameter list (...)
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif ch == "(" and depth == 0:
            break
        elif depth == 0:
            out.append(ch)
    return "".join(out).split("::")[-1].strip() or s[:40]


RULES = [  # (regex on full name, phase, operator)
    (DECODE, "parquet decode", "parquet decode/decompress"),
    (r"sirius::.*(accumulate_kernel|emit_kernel)", "hash join probe", "dense count join: accumulate/emit (sirius)"),
    (r"membership|needle_lookup|set_lookup|dynamic_filter|bloom", "scan/filter", "dynamic filter: membership probe"),
    (r"insert_if_n<.*convert_to_rep", "scan/filter", "dynamic filter: build key set (cuco insert)"),
    (r"convert_to_rep", "scan/filter", "dynamic filter: key conversion"),
    (r"apply_boolean_mask|copy_if|boolean_mask","scan/filter", "filter: boolean-mask compaction"),
    (r"hash_csr_build|insert_if_n<.*rhs_index_type|insert.*build", "hash join build", "hash join: build (insert)"),
    (r"initialize_functor<.*rhs_index_type", "hash join build", "hash join: hash-table init"),
    (r"hash_csr_probe|find_if_n<.*lhs_index_type|retrieve|probe", "hash join probe", "hash join: probe (find/count/retrieve)"),
    (r"distinct_hash_join|hash_join|mixed_join|conditional_join|join::|join_indices", "hash join probe", "hash join: output/compaction"),
    (r"groupby|group_by|shmem_aggs|mapping_indices|reduce_by_key|sort::unique_keys|label_segments", "hash group-by/agg", "group-by / aggregation"),
    (r"initialize_functor", "other", "hash-table init (cuco, other)"),
    (r"merge_sort|radix_sort|RadixSort|MergeSort|segmented_sort|topk|top_k", "sort/top-N", "sort / top-N"),
    (r"compute_column_kernel|(?<![a-z_])ast::", "expression eval", "expression: AST"),
    (r"binops::|binary_op", "expression eval", "expression: binary op"),
    (r"unary_cast|device_cast|unary_op|cast_fn", "expression eval", "expression: cast/unary"),
    (r"gather_chars|string_offsets_fn|gather_fn.*string", "gather/copy/concat", "gather: strings"),
    (r"permutation_iterator|gather|scatter", "gather/copy/concat", "gather/scatter: fixed-width"),
    (r"concatenate|Memcpy|memcpy|copy_block|copy_range|BatchMemcpy", "gather/copy/concat", "copy / concatenate"),
    (r"strings::|string_view|like|regex|contains", "string ops", "string ops"),
    (r"DeviceScan|scan_kernel|inclusive_scan|exclusive_scan|sizes_to_offsets", "cub scan/select/reduce", "cub/thrust: scan"),
    (r"DeviceSelect|DeviceCompact|select_kernel|unique_copy", "cub scan/select/reduce", "cub/thrust: select/compact"),
    (r"Reduce|reduce|minmax|find_kernel|init_found_pos", "cub scan/select/reduce", "cub/thrust: reduce/find"),
    (r"fill|uninitialized|counting_iterator|sequence", "other", "fill / sequence / init"),
]
RULES = [(re.compile(r) if isinstance(r, str) else r, p, o) for r, p, o in RULES]


def _match(name):
    for rx, p, o in RULES:
        if rx.search(name):
            return p, o
    return "other", "other: " + func_base(name)


def phase(name):
    return _match(name)[0]


def operator(name):
    p, o = _match(name)
    return o
