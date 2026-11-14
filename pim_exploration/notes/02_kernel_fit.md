# Kernel-family PIM fit (SF1, Q2–Q22)

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

> **Correction (independent review, note 12):** kernel durations taken from `warm_kernel_list.json` / `launches_all.csv:nsys_dur_ns` in this note are Nsight Compute serialized durations (sum 39.64 ms over the 21 queries), not real-clock nsys times (27.77 ms). Shares "of real-clock kernel time" below are therefore on the ncu basis; on the real-clock basis the bank-executable share is 21.4 % (not 20.5 %) and the sort block-sort family is 31 % (not 28 %).

## Kernel-family fit for PIM, TPC-H Q2-Q22 at SF1 (2,730 launches, 65 families)

All numbers come from the scripts in `pim_exploration/kernel_fit/`. Columns prefixed `ncu_` are Nsight Compute counters (serialized, clock-locked, L2 flushed before each kernel). Columns prefixed `nsys_` are real-clock durations. The two are never added, subtracted or divided by each other. The only cross-use is selecting launches by an ncu flag and summing their nsys durations. Tiers are my inference, not a measurement.

**Pipeline caveats (measured)**
- The brief says the venv has pandas and duckdb. It has only numpy and matplotlib, so the script uses the standard library plus numpy.
- Per-query launch counts equal `kernels` in `summary_data.json` for all 21 queries. The ncu list and the nsys list have the same length in every query.
- Position-by-position name agreement fails. The order differs in 18 of 21 queries (278 launches in total; only Q11, Q14 and Q18 agree). ncu serializes the 4 pipeline threads and nsys shows them interleaved. See `join_report.csv`.
- I therefore joined by k-th occurrence of (name, grid, block): 2,711 launches matched that way. The other 19 (Q3, Q4, Q5, Q7, Q8, Q9, Q10, Q12, Q13, Q15, Q16, Q17, Q20, Q21, Q22) differ only in name: ncu says `cuda_cub::functor<int*,int>` and nsys says `__uninitialized_fill::functor<int*,int>`. I matched them by func, grid and block. Nothing is left unmatched.
- ncu `dram_wr` is almost zero (91 MB written against 2,598 MB read). Writes stay in L2 at kernel end, so write bytes are undercounted. The flush before each kernel also means every input comes from DRAM, which overstates real read traffic for intermediates.
- Total real-clock kernel time is 39.64 ms. Total ncu DRAM traffic is 2.69 GB.

## 1. Key findings

1. **Memory bandwidth limits almost nothing at SF1.**
   - Median `dram_pct` is 1.34 %. 65.6 % of launches are below 5 %.
   - At or above 25 %: 299 kernels (10.9 % of launches, 10.8 % of nsys time). At or above 50 %: 108 kernels (4.0 %, 4.4 %). At or above 75 %: 11 kernels (0.4 %, 1.8 %). The maximum is 93.7 %. (`bw_bound.csv`)
   - 87 of the 108 kernels at 50 % or more are large 1-4 B gathers, mostly in Q18.
   - 64 % of launches run under 5 µs (11.7 % of time); the median launch is 3.4 µs. 37 % are single-block launches, and 61 % move under 100 KB of DRAM.
   - The comparison point is Q1. The brief calls `q1_u4` an SF10 study, but its report says SF1 (186 kernels, 117.9 MB large batch), so it is the SF1 comparison. The SF10 numbers are in `q1/REPORT_tpch_q1_sf10.md`. On hypothesis 3:
     - SF10, shipped library: `single_pass_shmem_aggs` runs at 73-146 GB/s (11-22 % of 672 GB/s), 108 GB/s on average (16 %), against a DRAM floor of 0.19 ms per batch.
     - SF1 control build (`orig`): the large batch runs at 327 GB/s (49 %) and the small batch at 250 GB/s (37 %).
     - SF1 unrolled (`u4`): the large batch runs at 450 GB/s (67 %) and the small batch at 316 GB/s (47 %).
     - Even unrolled, the group-by kernel stays at 67 % of peak at best, so hypothesis 3 holds. "The kernel is memory-bound" cannot be claimed.
     - The shipped library took 1,358 µs on the same batch, about 87 GB/s (13 %). That is a build artifact the report could not explain.

2. **Time is dominated by a few latency-bound or compute-heavy kernels, not by bytes.** The merge-sort block-sort family is 27.6 % of all kernel time (10.96 ms) but 0.2 % of DRAM bytes.
   - Of that, 6.2 ms is two launches in Q16 (2.2 ms and 4.0 ms; Q16 is 9.8 ms of kernel time, a quarter of the total).
   - It runs at 23 warp instructions per DRAM byte, `thread_eff` 15.6, and 82 % of its launches are a single block.
   - I call this kernel T5. A sort operator could be redone for PIM, but this kernel cannot be moved.

3. **Tier shares** (launches / nsys time / ncu DRAM bytes; `tier_shares.csv`):

| Scope | T1 | T2 | T3 | T4 | T5 |
|---|---|---|---|---|---|
| ALL | 16/5/14 % | 19/11/15 % | 41/37/53 % | 21/4/2 % | 3/42/15 % |
| ALL excluding block sort | 16/8/14 % | 19/15/15 % | 42/51/53 % | 21/6/2 % | 3/20/15 % |
| Mean of queries | 17/7/8 % | 18/14/15 % | 40/39/55 % | 21/5/1 % | 4/36/21 % |

   - Only T1 plus T2 (clean streaming or compaction) is 35 % of launches, 16 % of time and 29 % of bytes, or 23 % of time without the block sort.
   - T3 (random access or atomics) is the largest tier by launches and bytes.
   - T4 is 21 % of launches but 4 % of time, so removing launches saves launch count rather than GPU time.

4. **Per-query spread is large.**
   - T5 time is 82 % in Q6, 66 % in Q19, 65 % in Q16, 63 % in Q13, 56 % in Q12 and 55 % in Q14. In those queries, the AST `compute_column_kernel` or the block sort dominates.
   - T3 time is 50-67 % in Q4, Q5, Q8, Q9, Q10, Q11, Q17.
   - Q18 is the most streaming-friendly: T1 is 24 % of time and 35 % of bytes.

5. **Hash and gather kernels do not behave like a "random access" expectation.**
   - Hash build and probe kernels have 70-82 % L2 hit, because SF1 hash tables fit in L2. Their dominant stall is `long_scoreboard`, 49-82 %. The build insert (`cuco: hash-join build insert (pair)`) executes 386,370 atomic and reduction instructions in total.
   - The 1-4 B gather has an L2 hit of only 19 %, with 86 % `long_scoreboard`. Those gathers run at a median 9.6 % `dram_pct` but reach 91 % on large launches.
   - Compaction kernels (boolean-mask select) stall mostly on `barrier` (39 %), not memory.

6. **SASS shows no multiply or float heaviness.** The families with SASS inventories (`sass_opcode_mix.csv`) have 0.3-21 % of executed instructions as multiply or wide multiply, under 4 % float, and mostly logic, compare, move and control flow. "Multiply-heavy hashing" is therefore not what the profile shows. Control flow is 7-22 % of executed instructions and integer add is 6-30 %. This counts only 8 launch types with `*_source.csv`; coverage is thin.

## 2. Classification rules (all inference)

**Access pattern**
- SEQ: the kernel reads and writes whole columns in order (a map, fill, scan or reduce).
- COMPACT: streaming read with a data-dependent write position (cub select).
- GATHER: reads at indices, hash probe, or binary search.
- RANDW: hash insert, atomics, or scatter.
- TINY: setup, finalize or single-block bookkeeping.
- Counters I used to check this: L2 hit, atomics, long-scoreboard share. Kernels where a counter contradicted my expectation are called out in finding 5. Another case: LIKE and substr read with L2 hit of 5-6 % at 46-56 % `dram_pct`, so they behave like streaming reads.

**Compute per byte**
- BIT: bitwise or compare only.
- INTADD: integer add or small arithmetic.
- HASH: hashing plus compare.
- WIDE: 64/128-bit decimal multiply, divide or rescale.
- STR: string byte-wise control flow.
- FP: no family needed it.
- Evidence used: `inst_per_byte`, `pipe_*` shares, and SASS where available.

**Tier**
- T1: SEQ with BIT or INTADD.
- T2: SEQ with multiply, divide or wide arithmetic, or COMPACT, or scan and reduce-by-key (data-dependent chain or output position).
- T3: GATHER or RANDW.
- T4: TINY, or a bookkeeping family with a median single-block share of 80 % or more.
- T5: string byte-wise, an AST interpreter, or at least 10 warp instructions per DRAM byte.

## 3. Family table: top 25 by real-clock time (`kernel_families.csv` has all 65 and all requested columns)

nsys total µs and median µs; share of total nsys time; ncu median DRAM read per launch (KB) and total DRAM MB; ncu instructions per DRAM byte; ncu median `dram_pct`, max `dram_pct`, and L2 hit %; dominant stall (share of stall samples); single-block share. Median write per launch is 0-3 KB in every family listed, so I omit it.

| Family | n (queries) | nsys µs total/med | time % | rd KB med | DRAM MB | inst/B | dram% med/max | L2 % | stall | 1-blk | tier |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sort: merge-sort block sort | 17 (12) | 10955/406 | 27.6 | 92 | 4.6 | 23.0 | 0.1/0.2 | 84 | long_sb 60 | 82 % | T5 |
| AST compute_column | 51 (15) | 5272/72 | 13.3 | 3086 | 296 | 3.34 | 5.6/40 | 75 | long_sb 45 | 12 % | T5 |
| fused membership mask (dyn filter) | 33 (11) | 2590/73 | 6.5 | 8029 | 266 | 2.24 | 15.6/28 | 49 | long_sb 40 | 0 | T3 |
| strings: gather chars (char-parallel) | 171 (16) | 2123/6.5 | 5.4 | 34 | 134 | 2.44 | 0.8/36 | 66 | long_sb 58 | 26 % | T3 |
| sort: merge-sort merge | 10 (2) | 2022/226 | 5.1 | 1135 | 11 | 3.61 | 0.9/1.2 | 87 | long_sb 64 | 0 | T3 |
| gather fixed-width 1-4 B | 513 (21) | 2004/2.8 | 5.1 | 180 | 427 | 0.083 | 9.6/91 | 19 | long_sb 86 | 17 % | T3 |
| cub scan: string offsets | 188 (16) | 1848/12 | 4.7 | 59 | 67 | 0.144 | 1.4/61 | 76 | long_sb 64 | 63 % | T2 |
| cub select: boolean-mask compaction | 121 (21) | 1273/7.9 | 3.2 | 810 | 143 | 0.90 | 13/25 | 49 | barrier 39 | 17 % | T2 |
| cub tile-state / histogram init | 450 (21) | 798/1.8 | 2.0 | 3 | 1.3 | 0.07 | 0.3/0.3 | 82 | no_instr 62 | 79 % | T4 |
| hash-join build insert (pair) | 42 (15) | 625/7.7 | 1.6 | 29 | 74 | 0.33 | 0.7/37 | 80 | long_sb 82 | 38 % | T3 |
| dyn-filter key-set insert | 36 (16) | 612/5.5 | 1.5 | 378 | 39 | 1.21 | 6.6/26 | 79 | long_sb 68 | 6 % | T3 |
| groupby: mapping_indices | 17 (15) | 610/21 | 1.5 | 204 | 23 | 1.89 | 1.8/9.8 | 54 | long_sb 39 | 0 | T3 |
| for_each: group-by hash aggregate | 19 (15) | 601/3.0 | 1.5 | 127 | 36 | 1.01 | 4.5/12 | 56 | long_sb 58 | 5 % | T3 |
| for_each: dyn-filter membership (cuco set) | 12 (9) | 543/57 | 1.4 | 6449 | 97 | 1.41 | 28.7/35 | 62 | long_sb 51 | 8 % | T3 |
| cuco: hash-join probe find | 42 (15) | 510/11 | 1.3 | 147 | 35 | 1.25 | 2.2/39 | 70 | long_sb 49 | 10 % | T3 |
| for_each: binop compare | 31 (12) | 460/7.4 | 1.2 | 687 | 90 | 0.75 | 14/74 | 31 | long_sb 54 | 23 % | T1 |
| transform: cast integral widen | 127 (20) | 379/2.2 | 1.0 | 30 | 61 | 0.11 | 2.0/88 | 49 | long_sb 73 | 22 % | T1 |
| sort: radix sort | 29 (8) | 333/8.3 | 0.8 | 470 | 8 | 0.22 | 7.8/11 | 36 | long_sb 28 | 38 % | T3 |
| strings: gather chars (string-parallel) | 14 (2) | 313/4.2 | 0.8 | 56 | 23 | 2.31 | 2.3/19 | 63 | long_sb 80 | 0 | T3 |
| transform: fill constant / sequence | 47 (18) | 282/2.0 | 0.7 | 7 | 23 | 0.43 | 0.5/22 | 80 | long_sb 56 | 70 % | T1 |
| transform: misc elementwise | 12 (5) | 277/3.1 | 0.7 | 192 | 86 | 0.39 | 9.9/90 | 45 | long_sb 74 | 0 | T1 |
| gather fixed-width 8 B | 40 (14) | 257/2.6 | 0.6 | 7 | 99 | 0.056 | 0.4/91 | 76 | long_sb 94 | 57 % | T3 |
| for_each: cuco hash-table init | 110 (20) | 251/1.8 | 0.6 | 3 | 3.4 | 1.46 | 0.3/27 | 14 | drain 43 | 20 % | T1 |
| dyn-filter membership (bloom) | 6 (3) | 241/39 | 0.6 | 12100 | 73 | 0.83 | 45.8/49.5 | 56 | long_sb 64 | 0 | T3 |
| strings: LIKE multi-literal | 3 (2) | 222/106 | 0.6 | 39366 | 80 | 0.71 | 56/56 | 5 | long_sb 44 | 0 | T5 |

The CSV also has bandwidth in GB/s, global loads, stores, atomics and reductions per launch, waves, `thread_eff` and the `pipe_*` shares. Two examples of what the stall and SASS columns show:
- `cub: tile-state init` and `thrust find` are almost pure launch overhead.
- Hash-aggregate kernels have `ATOM` executions in the hundreds of thousands in total.

## 4. The 10 families that matter most (`top10_groups.csv`)

Grouping is my choice. Tier is inference. Measured bytes are ncu DRAM read plus write for the whole group (write undercounted). Each group's time share is nsys, and groups overlap no families.

| Group | nsys time % | ncu DRAM read / write MB | Primitive | In-memory logic needed |
|---|---|---|---|---|
| G1 gather fixed-width | 5.7 | 506 / 22 | gather | address indirection across banks (T3) |
| G2 dyn-filter / semi-join membership | 8.6 | 436 / 0.05 | hash probe or IN-list | hash unit plus indirection (T1 for the small-set case) |
| G3 boolean-mask compaction plus position scan | 4.7 | 202 / 4 | compact, prefix sum | adder chain plus write pointer (T2) |
| G4 string gather (chars plus offsets scan) | 10.9 | 225 / 0.001 | string gather | indirection plus byte copy (T2/T3) |
| G5 hash build / insert | 6.0 | 133 / 22 | hash build | hash unit plus CAS or atomic across banks (T3) |
| G6 hash probe | 2.5 | 64 / 0.08 | hash probe | hash unit, indirection, comparator (T3) |
| G7 group-by aggregate | 2.9 | 146 / 7 | atomic hash aggregate | atomic add plus type dispatch (T2/T3) |
| G8 element-wise map (compare, add, mul, cast, fill, copy) | 5.0 | 315 / 29 | map, filter predicate | comparator, adder, multiplier or wide ALU (T1/T2) |
| G9 AST expression (`compute_column`) | 13.3 | 296 / 0.03 | map (expression) | generic ALU, not fixed-function (T5) |
| G10 sort and reduce | 35.7 | 98 / 1.4 | sort, reduce | comparator network, adder tree (mixed tiers) |

G10's share is mostly the Q16 block sort. Read the shares as time on the GPU today, not time PIM would save.

## 5. What I could not determine

- The true real-clock DRAM traffic, write bytes included. ncu flushes L2 before each kernel and mostly does not capture write-back.
- The decimal precision (and so the true multiply cost) in `binop mul/div` and `cast decimal` kernels. The kernel names give no types, and I did not trace SASS for them.
- Whether the Q16 sort launches are representative of other sorts at larger scale.
- Whether kclass's operator labels agree with my family names for borderline cases; my family rules are in `family()` in the script.
- SASS opcode evidence covers only 8 launch types. Others rely on counters.

## 6. What I would measure next

- A real-clock traffic measurement with nsys GPU metrics, to remove the L2-flush and write-back distortion.
- SASS inventories for the other hot families (gather, compaction, hash probe) to test finding 6.
- Q16's two block-sort launches in isolation.
- Larger scale (SF10) for the top families to see which cross 50 % `dram_pct`.

## 7. Files written (all in `/home/sai/cs254_project/pim_exploration/kernel_fit/`)

- `build_family_table.py` (builds everything below) and `top10_groups.py`
- `kernel_families.csv` (one row per family), `launches_all.csv` (one row per launch, with family and tier), `tier_shares.csv` (query by tier, plus ALL, ALL_excl_block_sort and MEAN_OF_QUERIES)
- `bw_bound.csv`, `join_report.csv`, `sass_opcode_mix.csv`, `stats.json`, `top10_groups.csv`
- `tier_shares.png` (plot of the tier shares per query, for embedding in a report)
