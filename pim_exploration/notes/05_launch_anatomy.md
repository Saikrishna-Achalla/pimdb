# Launch anatomy: why one operator becomes many kernel launches

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## launch_anatomy: why one SQL operator becomes many kernel launches (TPC-H SF1 Q2–Q22, plus Q1 at SF10)

**Coverage.** All 2,730 warm-iteration launches are attributed. Per-query totals match `kernels` in `summary/summary_data.json` for all 21 queries (`attribute.py` checks this).

**Confidence of the operator-instance attribution:** high 1,229 (45.0%), medium 1,222 (44.8%), low 272 (10.0%), none 7 (0.26%).

**How the attribution works (inferred):**
- **Task boundaries.** Every Sirius pipeline task brackets its work with `stream.sync()` at `sirius/src/pipeline/gpu_pipeline_task.cpp:748` and `:890`. These show up as `cuStreamSynchronize` on the task stream (`tasks.py`).
- **Operator type.** Read from the demangled kernel functor: `cudf::gather(`, `unary_cast`, `membership_probe_functor`, `compute_single_pass_aggs`, and so on (`attribute.py:kind`).
- **Plan instance.** Matched by plan order plus operator-chain compatibility.

### 1. Main findings

1. **Hypothesis 1 is only partly right at SF1. Data-subset repetition is the smallest multiplier.** Shares of launches (and of kernel time) by cause, measured from nsys and classified by inference (`launch_causes.csv`, `stats.json`):

   | Cause | Launches | Share of launches | Share of kernel time |
   |---|---:|---:|---:|
   | Distinct work | 267 | 9.8% | 40.1% |
   | Multi-pass | 861 | 31.5% | 31.4% |
   | Per-column | 635 | 23.3% | 10.6% |
   | Bookkeeping | 597 | 21.9% | 1.8% |
   | Per-batch / partition | 370 | 13.6% | 16.1% |

   - Only about 1 launch in 10 is the operator's essential kernel.
   - 39.6% of launches repeat a kernel name already used in the same operator execution (50.6% within the same task). That repetition is mostly per-column gathers and casts plus multi-pass structure, not batches.

2. **Group-by specifically:** 454 launches over 23 executions (21 plan instances).
   - Launches per execution: min 5, median 16, max 68.
   - By cause: distinct 15, multi-pass 205, per-column 46, bookkeeping 136, per-batch 52. 193 of the 454 have `grid==1`.
   - **Q13** hash group-by (`walkthrough_q13.txt`, task 7), 13 launches:
     - Steps: is_sorted check (`init_found_pos_pointer`, `find_kernel`) → cuco slot init → fill → `mapping_indices` → retrieve keys (`DeviceCompactInit` + `SelectSweep`) → scatter → remap → identity fill → `single_pass_shmem_aggs` → 2 key/cast gathers.
     - Result: 1 distinct, 7 multi-pass, 4 bookkeeping, 1 per-column.
     - Host round trips: 3 (sorted bool, shared-memory fallback flag, number of groups).
     - Time: about 33 µs of GPU time inside a 349 µs task.
   - **Q18** (`walkthrough_q18.txt`):
     - Partial group-by on all 6.0M lineitem rows: Sirius found the keys sorted, so it took the sort-based path. 19 launches, 1 `reduce_by_key` doing the distinct work, 6 readbacks.
     - Hash group-by on 399 joined rows: 21 launches, 4 readbacks.
     - MERGE_GROUP_BY was a no-op (single partial).
     - MERGE_TOP_N re-sorts the 100 rows TOP_N had already sorted: 10 launches, including a 134 µs `grid=1` merge sort.
   - **Q1 at SF10 (`results/q1/`) is where the owner's picture holds.**
     - 873 launches, of which 13 per group-by kernel: 12 scan batches + 1 merge.
     - About 70 launches repeat per batch, so roughly 90% of launches come from batch repetition. This is inferred from per-name counts: 60 `DeviceReduce`, 13 `mapping_indices`, 13 `shmem_aggs`.

3. **The batch count is set by configuration and row-group size, not by thread count.** (Model in `batch_model.py`, output `batch_model.json`.)
   - Scan batches are row groups coalesced up to `scan_task_batch_size` (`op/scan/parquet_scan_core.cpp:415-460`).
   - The default size is `min(clamp(totalMem/40, 512 MiB, 5 GiB), capacity/40)` once YAML sets a usage limit (`sirius_config.cpp:46-66`, `:774-791`, `:918-919`, `:990`).
   - `hash_partition_bytes` and `concat_batch_bytes` use the same default (`sirius_config.hpp:56-58`).
   - The SF1 profiling YAML sets `usage_limit_fraction: 0.25`, which gives 73.6 MiB batches.
   - **The model reproduces every scan repeat seen in the traces:** Q6 3, Q19 6, Q12/Q13/Q14/Q15/Q17/Q21 2, Q18 1. It also reproduces Q1 SF10 = 12 at the Q1 YAML's 0.85.
   - Modeled alternatives:
     - With no usage limit (512 MiB batches), every SF1 table is 1 batch and Q1 SF10 drops to 6.
     - With the SF1 YAML, Q1 SF10 would be 56 batches.
   - **Hash partitioning never ran.** Every PARTITION had fewer than 2 partitions and was forwarded (`op/sirius_physical_partition.cpp:158`). No hash-partition kernel appears in any trace.
   - 254 of 481 tasks launched no kernel at all.

4. **Small inputs dominate the launch count.**
   - 1,022 launches (37.4%) have `grid==1`, accounting for 5.07 ms of 27.7 ms kernel time.
   - 1,341 (49.1%) have `grid×block ≤ 1024` threads.
   - 2,127 (77.9%) run under 5 µs.
   - By cause, the `grid==1` launches are: bookkeeping 400, multi-pass 277, per-batch 162, per-column 139, distinct 44.
   - Row counts are not in the trace, so these grid figures are the proxy for "<1,000 rows".
   - Only 200 distinct demangled kernel symbols (56 base names) cover all 2,730 launches. Per query it ranges from 15 symbols for 47 launches (Q6) to 71 for 156 (Q16).

5. **Host round trips the algorithms need** (`roundtrips.csv`), summed over 21 warm iterations:
   - 1,207 device-to-host readbacks followed by a sync before the next launch: median 48 per query, range 9–167, about 0.40 per launch.
   - 1,312 host-to-device copies followed by a sync.
   - 6,938 sync calls, which matches nsys API counts (Q18: 244).
   - 962 task-boundary syncs.
   - By readback size:
     - 445 are 8 B: cub DeviceSelect counts and offset totals. These are true size-then-allocate trips.
     - 313 are 4 B: string chars size, the group-by fallback flag, sizes.
     - 407 are 1 B: scalar `is_valid` reads and flags. These are not data-dependent and are avoidable.
   - Where the readback sits:

     | Operator / step | Readbacks | Source |
     |---|---:|---|
     | Compaction output size | 174 | `copy_if.cuh:57` → thrust `copy_if.h:149-151` |
     | String total bytes | 214 | `sizes_to_offsets_iterator.cuh:280`, `strings/utilities.cu:176` |
     | Join output size | 63 | `retrieve_impl.cuh:108`, `distinct_hash_join.cu:82`, `filtered_join.cu:150` |
     | Group-by number of groups | 28 | `open_addressing_impl.cuh:856-858` |
     | Group-by fallback flag | 17 | `compute_single_pass_aggs.cuh:115-119` |
     | Sirius pre-checks | 34 | keys sorted: `cuda/sorted_keys.cu:51/77`; SUM widen min/max: `op/aggregate/aggregate_op_util.cpp:436-437`; HyperLogLog: `gpu_aggregate_impl.cpp:317-322` |

     - Avoidable ones: device-view uploads (`column_device_view.cu:90`, `table_device_view.cu:79`) and scalar validity (`scalar.cpp:72`, `binaryop.cpp:66,69`).

6. **Launches per operator type** (launches per execution, min/median/max; `stats.json` `by_type`):

   | Operator type | Launches | Per execution min/median/max | Executions |
   |---|---:|---|---:|
   | HASH_JOIN | 818 | 1/11/34 | 66 |
   | DYNAMIC_FILTER probe | 464 | 1/7/19 | 60 |
   | HASH_GROUP_BY | 454 | 5/16/68 | 23 |
   | GPU_SCAN (pushed-down filter) | 307 | 1/5/17 | 65 |
   | FILTER | 169 | 3/7/14 | 23 |
   | TOP_N | 124 | 6/15/56 | 6 |
   | ORDER_BY | 116 | 4/7.5/38 | 10 |
   | DYNAMIC_FILTER build | 70 | 1/2/4 | 34 |
   | UNGROUPED_AGGREGATE | 63 | 3/7/14 | 9 |
   | MERGE_TOP_N | 44 | 6/8/22 | 4 |
   | CONCAT | 6 | 2/3/4 | 2 |

7. **Which launches only near-memory execution (PIM) could remove, and which software alone removes:**
   - **Per-batch (370):**
     - Raising `scan_task_batch_size` or dropping `usage_limit_fraction` removes the 192 scan-repeat launches at SF1 (modeled).
     - Skipping MERGE_TOP_N when there is a single batch removes 44 more.
     - These are configuration or Sirius changes. **Do not credit them to PIM.**
   - **Per-column (635):** gather (`include/cudf/detail/gather.cuh:659`), cast and fill (`aggregation.cu:93`) each launch once per column. A multi-column gather kernel or late materialization removes them. A PIM command would remove them only if its interface took many columns, and a GPU kernel can do that too. **Not a PIM property.**
   - **Bookkeeping (597, 1.8% of time):**
     - Sources: cub tile-state init, cuco slot init (`bucket_storage.inl:145`), sequences, fills, `single_thread_kernel`.
     - Fusing these into the main kernel removes the launches. CUDA graphs only cut the CPU cost of launching them.
     - **PIM is irrelevant here.**
   - **Multi-pass (861):**
     - What it covers:
       - size-then-allocate;
       - predicate → compact → gather;
       - hash build before probe (`hash_join.cu:121-161`);
       - count/scan/retrieve;
       - merge-sort passes (`dispatch_merge_sort.cuh:267-361`).
     - Removable without PIM: launches that exist only to learn a size. Over-allocation or device-side allocation removes them, along with their readbacks.
     - What PIM could uniquely save: the passes themselves still run, but their memory → SM → memory trip per pass (compaction, gather, hash probe, scan). That is a bandwidth and energy argument, not a launch-count argument.
   - **Sirius pre-checks:** is_sorted, min/max widen and HyperLogLog are planner policy that statistics could skip.

### 2. Supporting table: per-query launches by cause (`launch_causes.csv`)

| Query | Total | Distinct | Multi-pass | Per-column | Per-batch | Bookkeeping |
|---|---:|---:|---:|---:|---:|---:|
| Q2 | 229 | 16 | 74 | 58 | 22 | 59 |
| Q3 | 92 | 15 | 28 | 25 | 6 | 18 |
| Q4 | 56 | 7 | 26 | 6 | 0 | 17 |
| Q5 | 133 | 14 | 32 | 31 | 32 | 24 |
| Q6 | 47 | 3 | 5 | 4 | 32 | 3 |
| Q7 | 207 | 22 | 72 | 63 | 0 | 50 |
| Q8 | 172 | 20 | 38 | 44 | 43 | 27 |
| Q9 | 144 | 17 | 41 | 56 | 0 | 30 |
| Q10 | 238 | 14 | 81 | 56 | 39 | 48 |
| Q11 | 168 | 20 | 60 | 44 | 0 | 44 |
| Q12 | 86 | 8 | 27 | 13 | 19 | 19 |
| Q13 | 36 | 4 | 14 | 6 | 5 | 7 |
| Q14 | 46 | 6 | 12 | 14 | 6 | 8 |
| Q15 | 112 | 7 | 29 | 19 | 37 | 20 |
| Q16 | 156 | 10 | 74 | 29 | 0 | 43 |
| Q17 | 74 | 9 | 26 | 16 | 6 | 17 |
| Q18 | 127 | 13 | 42 | 32 | 10 | 30 |
| Q19 | 175 | 9 | 23 | 30 | 94 | 19 |
| Q20 | 142 | 17 | 54 | 34 | 0 | 37 |
| Q21 | 166 | 21 | 53 | 36 | 19 | 37 |
| Q22 | 124 | 15 | 50 | 19 | 0 | 40 |

Notes on this table:
- These are the final numbers, computed after the batch-repeat rule was tightened; they match `launch_causes.csv` as written by the final `attribute.py` run.
- Per-batch splits into:
  - 306 launches in repeated tasks: 192 from GPU_SCAN repeats, plus 114 low/medium-confidence repeats of join pipelines (Q5, Q8) and a MERGE_GROUP_BY pipeline (Q10);
  - 64 launches in merge/concat operators.

### 3. What I could not determine

- **No NVTX in the traces.** Mapping tasks to pipelines is inferred. Known errors:
  - Q13 and Q14: the second-table scan filter is attributed to GPU_SCAN P0 rather than the scan that actually reads `orders` / `lineitem`.
  - Q9, Q21: some tasks span several pipelines.
- **Deferred work.** 265 launches run on a stream other than their task's (159 on another thread's task stream). This is dynamic-filter work materialized in the consumer task. I attributed it to the nearest upstream DYNAMIC_FILTER, at medium confidence.
- **Rows per launch** are not in the trace. `grid==1` and grid×block are proxies only.
- **The cause split is my definition**: one "distinct" launch per libcudf call; the first output gather counts as multi-pass. A different convention moves roughly 100–200 launches between distinct and multi-pass.
- **Source paths.** cub/thrust/cuco are not under `sirius/.pixi/envs/default/include`. File:line references for them are from `cudf_u4/cudf/cpp/build/_deps/{cccl,cuco}-src` (CCCL 3.5).

### 4. What to measure next

- Re-run nsys with `-t cuda,nvtx`. Sirius already emits a "Pipeline X Task Y [op chain]" range (`gpu_pipeline_task.cpp:700`) and per-operator ranges, so attribution would become exact.
- Re-run SF1 (GPU allowed) without `usage_limit_fraction`, or with `scan_task_batch_size` = 512 MiB, to measure the per-batch removal and the change in wall time.
- Count how many 4-byte readbacks are sizes versus flags by adding call-stack sampling.
- Prototype over-allocation for compaction and string sizes to measure how many readbacks are truly unavoidable.

### 5. Files written (all in `/home/sai/cs254_project/pim_exploration/launch_anatomy/`)

- **Scripts:**
  - `trace_events.py`: per-thread CUDA event stream of one warm iteration.
  - `tasks.py`: task segmentation.
  - `plan.py`: plan parser.
  - `attribute.py`: labelling, matching, causes; writes `launch_attribution.json` and `launch_causes.csv`, and checks totals against the summary.
  - `stats.py`: aggregates; writes `stats.json` and `roundtrips.csv`.
  - `walkthrough.py`: writes `walkthrough_q13.txt` and `walkthrough_q18.txt`.
  - `batch_model.py`: run with the pixi python, which has pyarrow; writes `batch_model.json`.
  - `show.py`: per-task view.
- **Data:**
  - `launch_attribution.json`: per query → per operator instance → launches with cause, role, call and confidence.
  - `launch_causes.csv`: query × cause → launches, kernel µs.
  - `stats.json`, `roundtrips.csv`, `batch_model.json`, `walkthrough_q13.txt`, `walkthrough_q18.txt`.
