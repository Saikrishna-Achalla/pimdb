# Operator chains and round-trip intermediates

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## Operator chains and round-trip intermediates (owner's hypothesis 5)

### 1. Main findings

1. **Data movement between chained operators is too small at SF1 to justify PIM.** Across 21 queries, 886 same-thread producer→consumer steps write an intermediate that the next kernel reads back. The round-trip bytes total **632 MB**, measured as min(producer SM-store+atomic bytes, consumer cold-L2 `dram_rd`). Base-table columns (pinned) total **1,898 MB**. Per query, round-trip bytes are a median **0.23×** the base-table bytes (0.05× in Q19 to 2.32× in Q18), and a median **0.24×** of all cold `dram_rd`.
   - Moving 2× those bytes at the 672 GB/s peak takes a median **0.72 %** of a query's engine window (max 6.1 %, Q18). This is modeled.
   - A looser bound assumes the chain's reader kernels do nothing but read the intermediate. It gives a median **3.9 %** (nsys).
   - Sources: `roundtrip_bytes.csv`, `upper_bound.csv`.
2. **What costs time inside the chains is the host, not the bytes.** Same-thread gaps between steps add up to **37.9 ms** over the 21 warm iterations, against **27.8 ms** of kernel time (nsys).
   - **350 of 886** steps have a size read-back (sync + device-to-host copy) between them. Median gap there is **33.6 µs** (p90 95 µs), 19.7 ms in total.
   - Gaps with only an allocation have a median of 7.4 µs.
   - Sources: `gap_by_host.csv`, `gap_by_host.py`.
   - Removing the launches and gaps inside the top chains as well as the data movement gives a modeled saving of a median **19 %** of the engine window (12.6–47.3 %). This uses the wall-clock union of gaps across threads. Source: `upper_bound.csv`.
3. **85 % of round-trip bytes stay inside one Sirius operator.** 534 of 632 MB flow between libcudf sub-operators of the same operator (mask → compaction → gather, insert → key extraction → aggregate). Only 98 MB cross from one Sirius operator to the next. Chaining therefore pays mainly at the sub-operator level. Source: `roundtrip_bytes.csv`.
4. **The most frequent chains are all general and expressible as "operator A, then operator B on A's buffer".** The top sub-operator 2-grams and 3-grams (`chain_ngrams.csv`):
   - `mask_compact > gather`: all 21 queries, 118 instances, 682 launches, 2.6 ms of kernels, 92 MB round-trip. 117 of 118 have a size read-back, average gap 31 µs.
   - `dynf_probe_mask > mask_compact > gather`: 17 queries, 59 instances, 154 MB.
   - `join_probe > join_retrieve > gather`: 15 queries, 42 instances, 23 MB, 42 read-backs.
   - `join_build > join_probe`: 15 queries, 42 instances, 32 MB (the hash table).
5. **Group-by → sort (your example) does not matter for data movement at SF1.** It occurs in 13 queries; 2 to 37,922 groups reach the sort.
   - Intermediate between the two sides: 32 B to 1.3 MB (10 MB in Q10, whose output carries string columns). Chain round-trip bytes total **2.2 MB** for all 13 queries.
   - Kernel time (nsys): group-by side 1.2 ms in total, sort side 6.9 ms in total. Of the sort time, Q16's string sort is 3.8 ms, Q21 1.0 ms and Q3 0.7 ms (a merge sort of only 11,295 rows).
   - Gaps inside the chain: 8.6 ms in total, median **607 µs per query**, against a median chain kernel time of 216 µs. A chain is about 23 launches on 2–3 threads.
   - Q1 at SF10 is the same: 4 groups (< 1 KB intermediate, inferred). The merge group-by is 35 launches / 170 µs and the sort side 16 launches / 203 µs, including a 162 µs single-CTA block sort. Together that is about 1 % of the 36.0 ms ncu iteration (ncu serialized times; there is no nsys trace for SF10). Source: `q1_sf10_groupby_sort.json`.
   - What this chain costs is launches, host gaps and an under-parallelized sort, not the memory → SM → memory trip.
6. **The DRAM bytes are an upper bound, and most intermediates probably never reach DRAM in a warm run.**
   - With the L2 flushed, writes stay in the 48 MB L2: `dram_wr` is 91 MB in total against 1,094 MB of SM stores plus 351 MB of atomics. I therefore re-extracted store and load sectors from the existing `.ncu-rep` files on the CPU (`ncu_raw.py`).
   - Only 6 producer steps write more than 48 MB (Q18 group-by, Q9, Q13). They account for 118 MB (18.6 %) of the round-trip bytes. The other 81 % are written by producers small enough to stay in L2. That they are served from L2 when warm is inferred, not measured. Source: `l2_fit.py`.
   - This argues against a DRAM-traffic case for chaining at SF1.
7. **Partition → concat is irrelevant here.** PARTITION launches no kernels on one GPU. CONCAT launches kernels in only 3 queries (5 instances, 15 launches, 39 µs). Source: `chain_candidates.csv`.

### 2. Supporting tables

**Candidate chains** (`chain_candidates.csv`; kernel time and gaps from nsys, round-trip bytes from ncu)

| Chain | Queries | Instances | Launches | Kernel µs | Round-trip MB | Largest instance MB | Gaps µs (per instance) | Read-backs / syncs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| (f) dyn-filter probe → mask → compaction → gather | 17 | 60 | 454 | 6,048 | 188.9 | 13.0 | 11,479 (191) | 79 / 276 |
| (h) group-by internal (insert → extract keys → aggregate → gather) | 18 | 29 | 396 | 2,596 | 160.3 | 129.1 | 8,862 (306) | 102 / 565 |
| (a) predicate → mask → compaction → gather | 21 | 59 | 389 | 3,849 | 72.9 | 6.3 | 5,767 (98) | 95 / 373 |
| (e) expression → aggregate | 13 | 19 | 105 | 467 | 40.3 | 24.0 | 2,594 (137) | 15 / 218 |
| (b) hash probe → retrieve → gather | 17 | 50 | 437 | 1,506 | 25.4 | 4.0 | 5,678 (114) | 94 / 465 |
| (c) group-by → [projection] → sort / top-N | 13 | 13 | 299 | 7,107 | 2.2 | 1.1 | 8,585 (660) | 53 / 382 |
| (d) sort → gather → limit | 17 | 28 | 299 | 8,169 | 1.4 | 0.6 | 3,806 (136) | 50 / 386 |
| (g) partition → concat | 3 | 5 | 15 | 39 | 0 | 0 | 101 | 0 / 15 |

**What chaining needs, per candidate** (from cuDF and Sirius source)

| Chain | Interface | Size data-dependent? | Streamable? | Barrier / thread hand-off? | General? |
|---|---|---|---|---|---|
| (a) | bool mask → int32 index list → gathered columns | Yes: copy_if count goes to the host before gather allocates | Mask → compaction streams | No | Yes (apply_boolean_mask) |
| (b) | Hash table → (probe, build) index pairs | Yes: match count read back | Probe → retrieve streams | Build side crosses a pipeline barrier | Yes |
| (f) | Key set → mask → indices | Yes | Yes | Build → probe crosses threads (filter publisher; hand-off about 208 µs, low confidence) | Yes |
| (h) | Hash set → slot per row → distinct-key list | Yes: group count read back | Insert/aggregate stream; extraction does not | No | Yes (cudf::groupby) |
| (c) | Aggregated table → permutation | Group count known after the merge | No | 11 of 13 on the same thread in one pipeline (MERGE_GROUP_BY → ORDER_BY / TOP_N); Q12 and Q16 cross threads; ORDER_BY adds SORT_PARTITION / MERGE_SORT barriers | Yes, as two operators |
| (d) | Permutation → gather | No | After the sort finishes | No | Yes |
| (e) | Row-aligned column → aggregate | No | Yes | No | Chaining yes. Evaluating the expression inside the aggregate kernel, or filter + project + aggregate as one program (e.g. Q6), would be query-specific fusion and is flagged. |

A legal general chain for (a), (b), (f) and (h) must keep the selected or match count in memory and let the consumer allocate without the host (device-side or worst-case-sized output). That count read-back is what costs 19.7 ms today.

**Operator-level 2-grams** (`chain_ngrams.csv`): JOIN_BUILD > JOIN_PROBE (19 queries, 59 instances, 39 MB, gap 29 µs); JOIN_PROBE > PROJECTION (16 queries, 35 instances); DYNF_BUILD > DYNAMIC_FILTER (15 queries, 47 instances, all cross-thread, hand-off about 208 µs); PROJECTION > GROUP_BY (14 queries, 22 instances, 29 MB); GROUP_BY > ORDER/SORT (9 queries, 14 instances, 0 MB on the same thread).

**Modeled upper bound per query** (`upper_bound.csv`; ncu bytes and nsys times kept apart)
- Q18: 163 MB round-trip → 485 µs at 672 GB/s (6.1 % of an 8 ms engine window). Data movement plus gaps: 23.8 %.
- Q3: 21 MB → 64 µs (0.9 %); 17.6 % with gaps.
- Q22: 5 MB → 16 µs (0.2 %); 47.3 % with gaps.
- Median over the 21 queries: 0.72 % (data movement only) and 19 % (with launches and gaps). 1,869 launch boundaries fall inside chains (of 2,730 launches).

### 3. What I could not determine
- **Confidence.** Every launch got an operator-type label (0 unplaced), but 66 % only from context (gathers, compactions, prep kernels next to them), covering 27 % of kernel time. Only 7.6 % of launches could be tied to a unique plan instance; Sirius logs have no per-operator events. Same-thread edges are medium confidence. Cross-thread edges are low confidence: I link to the latest earlier producer the plan allows, which can pick the wrong join port or branch. Their round-trip bytes and hand-off gaps are therefore reported separately (145 MB). Segmentation is robust: the round-trip total moves only from 630 to 649 MB as the task-gap threshold goes from 100 µs to infinite (`sensitivity.json`).
- **Real warm DRAM traffic.** The ncu runs flushed the L2, so the actual SM ↔ L2 ↔ DRAM split for intermediates is unknown.
- **Exact producer → consumer bytes.** min(write, read) bounds the round trip but can count unrelated reads by the consumer. Buffer addresses were not traced.
- **What makes up the host gaps.** No CPU sampling was recorded. Engine windows come from 1 ms log stamps.
- **SF10.** Only Q1 exists at SF10, with no nsys trace or thread information.

### 4. What to measure next
- One warm ncu or nsys GPU-metrics pass without cache control, to see whether intermediates leave the L2.
- Correlate allocation addresses (`cudaMallocFromPoolAsync`) with kernel pointer arguments, to get exact buffer-level edges and instance mapping.
- nsys with CPU sampling, to split read-back, allocation and scheduler time in the gaps.
- The same analysis at SF10/SF100, where producers exceed 48 MB in more than Q18.

### 5. Files (all in `/home/sai/cs254_project/pim_exploration/operator_chains/`)
- **Scripts:**
  - `extract.py`: nsys iteration 5, per-thread order, ncu 1:1 match (2,730 of 2,730 launches matched on exact grid).
  - `ncu_raw.py`: CPU-only import of store/load/atomic sectors from the existing reports.
  - `classify.py`, `plan.py`, `chains.py`: the main analysis.
  - `sort_input_rows.py`: run with the pixi Python, which has DuckDB; CPU only.
  - `q1_sf10_groupby_sort.py`, `gap_by_host.py`, `sensitivity.py`, `l2_fit.py`, `show.py`.
  - `report_numbers.py`: reprints every number above.
- **Data:**
  - `dataflow_q2.json` … `dataflow_q22.json`.
  - `chain_ngrams.csv`, `chain_candidates.csv`, `roundtrip_bytes.csv`.
  - `upper_bound.csv`, `groupby_sort.csv`, `gap_by_host.csv`, `placement.csv`.
  - `sensitivity.json`, `sort_input_rows.json`, `q1_sf10_groupby_sort.json`.
  - `ncu_raw/q2.json` … `ncu_raw/q22.json`.
