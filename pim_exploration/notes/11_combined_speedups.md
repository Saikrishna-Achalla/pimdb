# Combined: Vortex baseline vs AiM PIM speedups, end-to-end and coverage

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

> **Correction (independent review, note 12):** kernel durations taken from `warm_kernel_list.json` / `launches_all.csv:nsys_dur_ns` in this note are Nsight Compute serialized durations (sum 39.64 ms over the 21 queries), not real-clock nsys times (27.77 ms). Shares "of real-clock kernel time" below are therefore on the ncu basis; on the real-clock basis the bank-executable share is 21.4 % (not 20.5 %) and the sort block-sort family is 31 % (not 28 %).

## Combiner: Vortex baseline vs AiM bank-level unit, turned into speedups

Everything here is recomputed by `sim/combined/combine.py`, `coverage.py` and `plots.py`, which you run in that order with `tpch_q1_analysis/venv/bin/python -I`; they take about 3 s. The labels mean:
- **sim**: simulated (simx or Ramulator2).
- **meas**: measured on the real RTX 5070 (a file).
- **mod**: modeled; the assumption is stated in the CSV's `basis`/`note` column.

### 1. Findings

1. **The fair chain speedup is (b)/(d)**: the best memory-bound GPU plan, reading the same bytes once, against PIM tile-at-a-time. It is **6.8× for Q6** (SF 0.01–1) and **1.6× for Q1** (2.2× if the GPU must read cuDF's string flags), mod (`chains_speedup.csv`).
   - It equals the internal-to-external bandwidth gain the unit actually reaches: Q6 runs at 218 GB/s per channel, Q1 at 51 GB/s, against 32 GB/s external.
   - The larger ratios against the simulated baseline are not the PIM effect: Q6 (a)/(d) = 12.1×, Q1 (a)/(d) = 39.6×. They also contain:
     - a plan change: a masked aggregate replaces compaction + gather, and a GPU could do the same;
     - simx pessimism: the Q1 baseline runs at 17.7× its own floor;
     - Q1's string gathers, which are 26 % of the Vortex Q1 time.
2. **PIM operator-at-a-time loses most of the gain.** Row activate/precharge is 69 % (Q6) and 73 % (Q1) of the PIM time (`pim_time_composition.png`).
   - Q6 (b)/(c) = 2.7×.
   - Q1 (b)/(c) = **0.57×**: an operator-at-a-time Q1 is slower than a GPU at its bandwidth floor.
   - The Sirius-mirror Q6 (casts + 64×64 multiply with write-back) is only 1.47× over the floor.
3. **Operators (S1 memory, SF 0.1).** For memory-bound baseline kernels (80–95 % of configured bandwidth), the speedup against the simulated baseline and against the floor differ by only 5–25 %:
   - **5.3–9.1× against the floor**: predicate, cast, multiply, sum.
   - Lower when the result must be read back to the GPU:
     - predicate with mask read-out: 6.6×;
     - compaction: **1.75–2.4× in memory, 0.89–1.02× once the GPU reads the segments**;
     - 8-key IN-list: 1.8× as one operator, 0.77× as 8 separate operators.
4. **End to end at full-5070 scale (mod, `end_to_end.csv`).** These are the cases where the host term matters.
   - **Q6 SF 1:**
     - Baseline 371 µs = 222 µs kernels + 141 µs host gaps + 7.5 µs omitted launches. It drops to 319 µs if the size read-backs are removed in software, which notes 05/06 show is possible without PIM.
     - PIM with the sequencer is 26.4 µs with posted commands and 29.1 µs with synchronous ones, so **14× (12× against the software-improved baseline)**.
     - Against the GPU floor plus one launch gap it is **5.0×**.
   - **Q1 SF 0.1:**
     - PIM sequencer is 19.4 µs posted, but **78 µs synchronous**: 197 host commands, 192 of them group-accumulator read-outs, at 300 ns each.
     - Against the floor plus one gap: **1.30× posted, 0.32× synchronous**.
5. **Query level on the real GPU (Amdahl; meas inputs, mod result).** Planning, non-replaceable kernels and host time stay; the share of GPU busy the unit can replace comes from the overlap-aware union of kernel intervals.

   | Run | Replaceable share of GPU busy | Wall speedup at s = (b)/(d) | at s = ∞ | at ∞ + chain host gaps removed |
   |---|---|---|---|---|
   | Q6 SF 1 | 91 % | 1.23× | **1.28×** | 1.54× |
   | Q6 SF 10 | 98 % | 1.85× | **2.17×** | 2.60× |
   | Q1 SF 1 | 77 % | 1.13× | **1.46×** | 3.50× (weak) |
   | Q1 SF 10 | 87 % | 1.34× | **3.14×** | 5.66× (weak) |

   Planning alone is 2–5 ms (1 ms resolution).
6. **Coverage across Q2–Q22 at SF 1 (`coverage.csv`).**
   - The bank unit can execute 16.1 % of launches and **20.5 % of real-clock kernel time** (8.15 of 39.64 ms). 75.1 % is not executable and 4.4 % is bookkeeping.
   - Upper bounds with s → ∞ on the executable part: GPU busy falls by at most 28 %; summed wall improves by **at most 1.052×** (163.5 → 155.4 ms).
   - **64.7 % of the executable time is the AST `compute_column` interpreter** (5.27 ms, 13.3 % of all kernel time). The real GPU runs it latency-bound at 11–13 % of bandwidth, so part of that gain is just a better GPU kernel. Without the AST kernel the bound is **1.018×**, and no query exceeds 1.041×.
7. **Scaling invariance holds once launch cost is amortised.**
   - S4 over S1 speedup: Q6 SF 1 1.004, Q1 SF 0.1 1.07.
   - It fails at Q6 SF 0.1 (1.42) and at SF 0.01 (up to 2.7×), because simx's 6–9 µs launch cost does not shrink with cores: Vortex S4/S1 is only 2.82× at Q6 SF 0.1.
   - The projection to the full 5070 equals the S1 ratio by construction: 48 cores for 1, and 21 channels for 0.4375.
   - It agrees with the AiM builder's direct 1/21-share simulation within 0.2 % (Q6 tile-at-a-time 18.36 vs 18.40 µs).

### 2. Tables

**Operators, S1 memory, SF 0.1** (`operators_speedup.csv`; SF 1 rows agree within 3 %). Vortex time is sim; PIM is the 1-channel sim time × 1/0.4375 (mod).

| Operator | Vortex µs | % of BW | Floor µs | PIM variant (where the result ends) | PIM µs | vs sim | vs floor |
|---|---|---|---|---|---|---|---|
| Predicate int32 | 232.8 | 93 | 214.5 | bit mask stays in memory / bool8 / GPU reads the mask | 23.7 / 26.0 / 32.7 | 9.8 / 9.0 / 7.1 | 9.1 / 8.3 / 6.6 |
| Cast 4→8 B | 571.9 | 91 | 514.8 | int64 written back | 80.0 | 7.2 | 6.4 |
| Multiply 64×64 | 1116.9 | 93 | 1029.6 | written back | 193.4 | 5.8 | 5.3 |
| Sum int32 / int64 | 222.1 / 372.6 | 80 / 94 | 171.6 / 343.2 | scalar read out | 21.2 / 44.2 | 10.5 / 8.4 | 8.1 / 7.8 |
| Compaction (15.3 % selected)* | 407.0 (mod) | 40 | 69.2 | in memory, sequencer / + GPU reads, sequencer | 28.9 / 67.9 | 14.1 / 6.0 | 2.4 / 1.0 |
| 8-key IN* | 999.6 | 22 | 214.5 | one operator / 8 operators | 117 / 280 | 8.5 / 3.6 | 1.8 / 0.77 |
| Range filter* | 578.2 | 82 | 471.9 | one operator / 2 operators | 60.7 / 91.7 | 9.5 / 6.3 | 7.8 / 5.1 |

\* Normalisations, all mod:
- Compaction: the Vortex time is interpolated between `compact_1` and `compact_25`, and the output order differs.
- IN-list: the PIM key column is int16, so the PIM time is ×2.
- Range filter: the semantics differ, so the PIM time is ×10/8 (per input byte).

No speedup was computed for these:
- **Group-by**: not comparable. Vortex has 2 string keys, 3 int64 SUMs and a COUNT; PIM has a uint8 key, 1 int16 SUM and a COUNT.
- **int16 predicate, range predicate, mask AND, min/max**: no PIM run.
- **Gather, hash build/probe, sort, strings**: not executable at bank level.

**Chains, µs.** S1 for the speedups; the 5070 rows are mod.

| | Q6 SF 1, S1 | Q6 SF 1, 5070 | Q1 SF 0.1, S1 | Q1 SF 0.1, 5070 |
|---|---|---|---|---|
| (a) baseline, sim | 10,677 | 222.4 (252 with real-GPU launch cost) | 21,247 | 442.6 |
| (a') (a) without the min/max pre-check | 10,581 | 220.4 | 19,392 | 404.0 |
| (b) floor, same bytes | 6,001 | 125.0 | 858 (1,201 at cuDF widths) | 17.9 |
| (c) PIM operator-at-a-time | 2,216 | 46.2 | 1,513 | 31.5 |
| (d) PIM tile-at-a-time | 881 | 18.4 | 537 | 11.2 |
| (e) PIM Sirius mirror, tile / operator | 4,072 / 14,081 | 84.8 | n/a | n/a |
| (f) fused command (not compliant) | 829 | 17.3 | n/a | n/a |
| Speedups (a)/(c), (a)/(d), (a')/(d), **(b)/(d)**, (a)/(e) | 4.8, 12.1, 12.0, **6.8**, 2.6 | same | 14.0, 39.6, 36.1, **1.6**, n/a | same |

### 3. Inconsistencies between the two builders

- **Column split.** Both sides total 14 B/row for Q6, and both infer the split. Vortex uses l_shipdate int16 + l_quantity int32; PIM uses int32 + int16.
- **Q1 widths.** Vortex reads 28 B/row (flags as cuDF strings); PIM reads 20 B/row (1-byte dictionary codes). This favours PIM by 8 B/row, so floors are given at both widths.
- **Fused reference.** The owner's fused Q6 command reads 16 B/row (quantity int32), not the 14 B/row of the general chain.
- **Q6 parameters and rows.** Both simulators use DuckDB dbgen data with the default parameters (1994, 0.05–0.07): 114,160 selected rows at SF 1, the same data on both sides, with 6,001,215 / 600,572 rows matching exactly. The real GPU ran 1997 / 0.02–0.04 on Parquet (114,271 rows). Selectivity is the same (1.90 %).
- **Mapping CSVs.** Vortex mirrors the min/max pre-check; PIM leaves it out, hence row (a'). Vortex omits Q1's `batch_memcpy` string path; PIM counts it as removed. Vortex launches the casts; PIM folds them into the operand widths.
- **AiM regexes don't match nsys names.** They were written against namespace-stripped names and miss nsys demangled names (`binops::compiled::ops::`, `cub::detail::`, `cuda::std::`). I normalise the names; afterwards every Q6/Q1 launch matches, and busy and launch counts equal the existing `nsys_iteration_breakdown.json` exactly.
- **Clocks.** simx runs at 2512 MHz and AiM at tCK 0.5 ns. Both report µs, so no conversion is needed. GDDR7 vs GDDR6 remains a projection.
- **End of an operation.** Vortex ends when its writes have drained to DRAM; host read-backs are not simulated. PIM ends with results in rows or PU registers (RD_MAC read-out included); mask and segment read-out to the GPU are separate "+readout" variants, so I report both cases.

### 4. What I could not combine or determine

- **Q1 at SF 1 on Vortex** does not exist. The SF 1 end-to-end row uses SF 0.1 × 10 (mod). Note that Vortex Q6 time per row fell 11 % from SF 0.1 to SF 1.
- **Multiply and sum at SF 1, int16 predicates, a comparable group-by**: missing on one side.
- **Layout transform is not included anywhere.** It is the one-time cost of moving columns into the row-tile layout: 250 µs (Q6) and 357 µs (Q1) at 5070 scale, versus 18 µs for the Q6 chain. PIM wins only if the layout persists across queries.
- **Power** is not modeled (Membrane reports about 4× peak DRAM power in all-bank mode).
- **The "host gaps removed" Amdahl rows are the weakest numbers.** The per-batch Vortex gap model exceeds the measured GPU-idle time for Q1 SF 10 (6.07 vs 4.90 ms, capped). The 4 pipeline threads overlap their gaps, and the traced engine windows are inflated ×1.2–1.7 against the untraced wall.
- **Real Q1 kernels overlap.** Summed kernel time exceeds GPU busy (SF 10: 44.8 vs 27.1 ms), so I used union-based shares rather than summed time.
- **Coverage classification has unverified assumptions:**
  - IN-lists are assumed to have ≤ 8 keys.
  - Small-group group-bys (Q4, Q5, Q7, Q8, Q12, Q22, all ≤ 8 groups) assume their join-output input is already in row-tile layout, which is optimistic.
  - min/max, divide, int128 and select are counted as not executable because the ISA lacks them.

### 5. Plots (`sim/combined/plots/`)

- **`operator_speedups.png`** (linear axis). Read: predicate in memory 9.8× / 9.1×; multiply 5.8× / 5.3×; compaction with GPU read-out 1.0× against the floor.
- **`chain_time_breakdown.png`**. Read: Q6 222 / 125 / 46 / 18 µs; Q1 443 / 17.9 / 31.5 / 11.2 µs. For Q1 the floor (17.9 µs) sits below PIM operator-at-a-time (31.5 µs).
- **`pim_time_composition.png`**. Read: row overhead 69 % → 37 % (Q6) and 73 % → 38 % (Q1) going from operator-at-a-time to tile-at-a-time; refresh 8 %.
- **`coverage_by_query.png`**. Read: ALL 21 % executable (13 points of it AST); Q6 92 %, Q19 71 %; Q16 1 %, Q2 4 %.

### 6. Files (all in `/home/sai/cs254_project/sim/combined/`)

- Scripts: `combine.py`, `coverage.py`, `plots.py`.
- Data:
  - `operators_speedup.csv`, `chains_speedup.csv`, `end_to_end.csv` (sections `host+e2e` and `amdahl`);
  - `realgpu_amdahl_detail.csv` (per nsys iteration);
  - `coverage.csv`, `coverage_families.csv` (class and reason per kernel family);
  - `combined_numbers.json` (all chain times, Amdahl inputs, constants, and the issues list).
- Plots: the four PNGs in `plots/`.
