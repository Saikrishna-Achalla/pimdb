"""Kernel name -> libcudf/Sirius sub-operator (level 2) and the Sirius operator type it belongs to (level 1).

Rules use the full demangled name (template arguments carry the calling cudf function / functor), after norm()
reduces the fully-qualified nsys name. Kernels whose role depends on context are labelled by refine() from the
neighbouring kernels of the SAME host thread (a Sirius pipeline task runs on one thread, so same-thread order is
execution order within a task).
Source references (cuDF v26.10.02, cudf_u4/cudf/cpp):
  stream_compaction/apply_mask.cu + include/cudf/detail/copy_if.cuh : apply_boolean_mask = thrust::copy_if over a
      counting iterator with retention_mask_filter (cub DeviceCompactInit + DeviceSelectSweep) -> the host reads the
      selected count (copy_if returns an iterator => stream sync + D2H) -> cudf::detail::gather (one transform_kernel
      per fixed-width column; offsets scan + chars kernel per string column).
  join/distinct_hash_join.cu : build = cuco initialize + insert_if_n<rhs_index_type>; probe = find_if_n<lhs_index_type>
      -> copy_if over the probe result (DeviceSelectSweep<distinct_hash_join::inner_join>) -> host count -> gathers.
  join/hash_join (CSR): hash_csr_build_count/fill, hash_csr_probe_count -> host total -> hash_csr_retrieve -> gathers.
  join/filtered_join/* : semi/anti: initialize + insert_if_n<key_pair_fn<lhs>>, contains_if_n, DeviceSelectSweep<gather_mask>.
  groupby/hash/* : (cuco set init) mapping_indices_kernel / insert_if_n -> DeviceSelectSweep over get_slot (extract the
      populated slots = distinct keys) -> single_pass_shmem_aggs_kernel / compute_single_pass_aggs -> gathers of keys.
Sirius (sirius/src): op/aggregate/aggregate_op_util.hpp: cudf::minmax passes before a SUM decide widening/narrowing
  (one D2H + sync per batch); op/merge/gpu_merge_impl.cpp: approx_distinct_count (hyperloglog) before dict-encoding
  string keys of MERGE_GROUP_BY; fused_membership_mask_kernel / membership_probe_functor = DYNAMIC_FILTER probe;
  insert_if_n<convert_to_rep> / bloom add_if_n = dynamic-filter key-set build (published from the join build side).
"""
import re

R = [  # (regex on norm(name), sub_op) first match wins
    (r"sirius::.*accumulate_kernel", "densejoin_accumulate"),
    (r"sirius::.*emit_kernel", "densejoin_emit"),
    (r"presence_positive", "densejoin_count"),
    (r"fused_membership_mask_kernel|membership_probe_functor", "dynf_probe_mask"),
    (r"bloom_filter_ns::add_if_n", "dynf_build"),
    (r"convert_to_rep", "dynf_build"),
    (r"retention_mask_filter|deletion_mask_filter", "mask_compact"),
    (r"DeviceSelectSweepKernel.*distinct_hash_join", "join_retrieve"),
    (r"DeviceSelectSweepKernel.*gather_mask", "semijoin_retrieve"),
    (r"count_if.*filter_join_indices|filter_join_indices|mixed_join_semi|conditional_join|compute_conditional_join_output_size",
     "join_conditional"),
    (r"hash_csr_build_count_kernel|hash_csr_build_fill_kernel", "join_build"),
    (r"hash_csr_probe_count_kernel", "join_probe_count"),
    (r"hash_csr_retrieve_kernel", "join_retrieve"),
    (r"initialize_functor<.*rhs_index_type", "ht_init"),
    (r"insert_if_n<.*rhs_index_type", "join_build"),
    (r"find_if_n<.*lhs_index_type", "join_probe"),
    (r"insert_if_n<.*filtered_join", "semijoin_build"),
    (r"contains_if_n<.*filtered_join", "semijoin_probe"),
    (r"hyperloglog", "gb_card_estimate"),
    (r"mapping_indices_kernel|insert_if_n<1, 128, cuda::counting_iterator<int, long>.*static_set_ref", "gb_insert"),
    (r"DeviceSelectSweepKernel.*get_slot", "gb_extract_keys"),
    (r"shmem_aggs|compute_single_pass_aggs|compute_groupby|reduce_by_key|ReduceByKey|label_segments", "gb_aggregate"),
    (r"unique_copy_fn|permuted_row_equality|cudf::groupby::", "gb_aggregate"),
    (r"initialize_functor", "ht_init"),
    (r"DeviceTopK", "topk"),
    (r"merge_sort|MergeSort|radix_sort|RadixSort|segmented_sort", "sort"),
    (r"binary_search_functor", "sort_merge_search"),
    (r"compute_column_kernel", "expr_ast"),
    (r"binary_op_device_dispatcher<[\w:]*?(?:Equal|NotEqual|Less|Greater|LessEqual|GreaterEqual|NullEquals|LogicalAnd|LogicalOr)>",
     "pred_binop"),
    (r"binary_op_device_dispatcher|binops::", "expr_binop"),
    (r"DeviceNot", "pred_binop"),
    (r"like_multiliteral_kernel|contains_fn|starts_with|ends_with", "pred_string"),
    (r"unary_cast|device_cast|fixed_point_unary_cast|cast_fn<.*value_accessor<[^>]*>>, *cuda::counting|time_point", "expr_cast"),
    (r"cast_functor_fn<.*Device(Sum|Max|Min)", "reduce_agg"),
    (r"minmax|single_thread_kernel", "minmax_reduce"),
    (r"string_offsets_fn|gather_chars|strings::gather", "gather"),
    (r"gather_bitmask|cudf::gather|permutation_iterator|input_indexalator", "gather"),
    (r"cudf::scatter", "scatter"),
    (r"fused_concatenate|BatchMemcpy|batch_memcpy|InitTileStateKernel", "concat"),
    (r"copy_range_kernel|copy_if_else", "copy_range"),
    (r"substring|make_strings_column|chars_size_transform|strings::", "string_op"),
    (r"encode_fn", "encode"),
    (r"find_kernel|init_found_pos", "search"),
    (r"make_offsets_child_column|sizes_to_offsets|DeviceScan", "offsets_scan"),
    (r"DeviceCompactInitKernel", "compact_init"),
    (r"DeviceSelectSweepKernel", "select_other"),
    (r"uninitialized_fill|__return_constant|tabulator|counting_iterator<long, __int128>|sequence|fill", "fill"),
    (r"DeviceReduce", "reduce_count"),
    (r"list_size_functor|lists_column_view|lists::", "list_op"),
]
R = [(re.compile(a), b) for a, b in R]

# level-1 operator type of each sub-op; None = decided by context in refine()
OP_OF = {
    "densejoin_accumulate": "DENSE_COUNT_JOIN", "densejoin_emit": "DENSE_COUNT_JOIN", "densejoin_count": "DENSE_COUNT_JOIN",
    "dynf_probe_mask": "DYNAMIC_FILTER", "dynf_build": "DYNF_BUILD",
    "join_retrieve": "HASH_JOIN_PROBE", "semijoin_retrieve": "HASH_JOIN_PROBE", "join_conditional": "HASH_JOIN_PROBE",
    "join_build": "HASH_JOIN_BUILD", "join_probe": "HASH_JOIN_PROBE", "join_probe_count": "HASH_JOIN_PROBE",
    "semijoin_build": "HASH_JOIN_BUILD", "semijoin_probe": "HASH_JOIN_PROBE",
    "gb_card_estimate": "GROUP_BY", "gb_insert": "GROUP_BY", "gb_extract_keys": "GROUP_BY", "gb_aggregate": "GROUP_BY",
    "topk": "TOP_N", "sort": "ORDER/SORT", "sort_merge_search": "ORDER/SORT",
    "pred_binop": "FILTER", "pred_string": "FILTER", "pred_ast": "FILTER",
    "expr_binop": "PROJECTION", "expr_ast": "PROJECTION", "expr_cast": "PROJECTION", "string_op": "PROJECTION",
    "reduce_agg": "UNGROUPED_AGG", "concat": "CONCAT",
}
# context-dependent kernels: FORWARD ones materialise the output of the operator before them (gather after a
# compaction / join retrieve / sort); BACKWARD ones prepare the operator after them (hash-table init before an
# insert, minmax before a SUM, a sequence fill before a sort, an offsets scan before a string op).
FORWARD = {"gather", "scatter", "copy_range", "select_other", "compact_init", "mask_compact", "reduce_count"}
BACKWARD = {"ht_init", "fill", "minmax_reduce", "offsets_scan", "search", "encode", "list_op", "other"}
PRED = {"pred_ast", "pred_binop", "pred_string", "dynf_probe_mask"}
MAX_GAP_US = 300


def norm(name):
    """nsys demangled names are fully qualified; reduce them to the short form the regexes (and kclass.py) use."""
    n = re.sub(r"\((?:int|bool|unsigned int|long|unsigned long|cub::SelectImpl|cudf::[\w:]+)\)(?=-?\d)", "", name)
    n = re.sub(r"\b(?:detail|__4|compiled|ops|op)::", "", n)
    n = re.sub(r"\bcub::(?=(?:scan|select|transform|for_each|reduce|merge_sort|radix_sort|topk|batch_memcpy|reduce_by_key|find)::)", "", n)
    n = n.replace("cuda::std::", "std::")
    return n


def sub_op(name):
    name = norm(name)
    for rx, s in R:
        if rx.search(name):
            return s
    return "other"


def refine(seq):
    """seq: kernels of one host thread in time order, each with 'sub'. Sets k['sub'] refinements, k['op'] (level 1)
    and k['placed'] in {'name', 'context', 'unplaced'}."""
    n = len(seq)
    for i, k in enumerate(seq):  # compact_init is the first kernel of the cub select that follows it
        if k["sub"] == "compact_init":
            nxt = next((seq[j]["sub"] for j in range(i + 1, min(n, i + 3)) if seq[j]["sub"] != "compact_init"), None)
            if nxt in ("mask_compact", "join_retrieve", "semijoin_retrieve", "gb_extract_keys", "select_other"):
                k["sub"] = nxt
    for i, k in enumerate(seq):  # an AST/binop/cast evaluation whose output is compacted next is a predicate
        if k["sub"] in ("expr_ast", "expr_binop"):
            nxt = next((seq[j]["sub"] for j in range(i + 1, n) if seq[j]["sub"] not in ("expr_ast", "expr_binop", "pred_binop")), None)
            if nxt in ("mask_compact", "dynf_probe_mask"):
                k["sub"] = "pred_ast" if k["sub"] == "expr_ast" else "pred_binop"
    for k in seq:
        k["op"] = OP_OF.get(k["sub"])
        k["placed"] = "name" if k["op"] else None
    for i, k in enumerate(seq):  # a compaction belongs to the operator that produced its boolean mask
        if k["sub"] == "mask_compact":
            prev = next((seq[j] for j in range(i - 1, -1, -1) if seq[j]["sub"] != "mask_compact"), None)
            k["op"] = "DYNAMIC_FILTER" if prev is not None and prev["sub"] == "dynf_probe_mask" else "FILTER"
            k["placed"] = "context"
    # predicates evaluated right before a membership probe are the GPU_SCAN table filters that the DYNAMIC_FILTER
    # operator folds into its mask (one compaction for both): keep them FILTER-typed but mark them
    for i, k in enumerate(seq):
        if k["sub"] in PRED and k["sub"] != "dynf_probe_mask":
            nxt = next((seq[j] for j in range(i + 1, n) if seq[j]["sub"] not in PRED - {"dynf_probe_mask"}), None)
            if nxt is not None and nxt["sub"] == "dynf_probe_mask":
                k["op"] = "DYNAMIC_FILTER"; k["placed"] = "context"
    near = lambda a, b: a is not None and b is not None and abs(b["start"] - a["end"]) / 1e3 < MAX_GAP_US if "start" in b else True
    last = None
    for k in seq:  # forward carriers (only across a gap < MAX_GAP_US: a later launch belongs to another task)
        if k["op"] is None and k["sub"] in FORWARD and last is not None and near(last, k):
            k["op"] = last["op"]; k["placed"] = "context"
        if k["op"]:
            last = k
    nxt = None
    for k in reversed(seq):  # backward carriers (and forward ones with nothing before them)
        if k["op"] is None and nxt is not None and near(k, nxt):
            k["op"] = nxt["op"]; k["placed"] = "context"
        if k["op"]:
            nxt = k
    last = None
    for k in seq:  # whatever is left: inherit from the previous labelled kernel regardless of the gap, marked weak
        if k["op"] is None and last is not None:
            k["op"] = last["op"]; k["placed"] = "context_weak"
        if k["op"]:
            last = k
    for k in seq:
        if k["op"] is None:
            k["op"] = "UNPLACED"; k["placed"] = "unplaced"
    return seq
