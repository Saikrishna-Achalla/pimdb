# Paper digest: PIMDAL and Membrane

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## Digest: PIMDAL (UPMEM) and Membrane (DDR4 bank-level filter PIM)

Reading status and caveats:
- Membrane: I read all 1,306 lines of `papers/membrane_taco2025.txt`. Numbers come from the text, tables and figure captions. Bar heights in the figures are not extractable.
- PIMDAL: I read it through WebFetch, which answers each call with a small model over a window. Each call covered chars 0–100,000 of 110,050, and I read the last window too. The numbers below are what that summarizer returned, so they are not guaranteed verbatim. Recheck any number you cite against the arXiv HTML. Per-query TPC-H bar values are only in PIMDAL Fig. 26 and I could not get them.
- Everything under "Inference" headings is mine. The rest is the authors' statement, with the location given.
- Reusable parameters: `/home/sai/cs254_project/pim_exploration/papers/model_parameters.csv` (83 rows: name, value, unit, source).

### 1. Most important findings

1. **Both papers say the same thing about complex operators.** Filtering is the only operator that wins clearly in PIM. Aggregation, sort and join lose to the CPU or GPU once cross-unit data movement is needed.
   - Membrane Table 1: only filter passes all four PIM-amenability tests. Aggregates and joins fail 3 of 4 (cache reuse, localized operands, aligned parallelism).
   - PIMDAL Sec 7.2, 8 GB including transfers: ordering 2.3x vs CPU and 0.9x vs GPU. Join 0.6x vs CPU and 0.3x vs GPU.
2. **PIMDAL's stated cause of the sort and join loss is inter-core redistribution through the host.**
   - Sec 5: the host reorder "is a key bottleneck since it is restricted by the lower bandwidth of the host system".
   - Sec 7.3 on the GPU: "the current UPMEM system cannot fully overcome this limitation, due to inter PIM-core communication".
   - Sec 7.1/9: this communication "will likely have to be implemented in hardware" and is "the key point for future PIM systems to address".
3. **Membrane's bank-level filter is cheap and fast.**
   - Area: 0.001 mm² per BFU (22 nm-scaled), which is 0.1% of the chip. Path delay 0.45 ns. Power 118.7 µW per BFU.
   - Throughput on a 1.12 GB 16-bit column: 37 GB/s (channel), 141 GB/s (rank), 4,286 GB/s (bank). Source: Table 5.
   - Cost: all-bank mode draws about 4x peak DRAM power (Sec 5, citing Newton).
4. **The Membrane speedup depends on denormalization.** Join-heavy schemas gain little from PIM filtering.
   - D1 (no denormalization): 1.2x SSB and 1.3x TPC-H geomean (Sec 6.2).
   - D3 (denormalized): 5.92x SSB and 6.38x TPC-H, with 3–17% extra space.
   - D2 gives 5.9x SSB and 4.8x TPC-H.
   - The authors' reason: join becomes the dominant remaining cost (Fig 8).
5. **Membrane's speedup depends on selectivity.** Queries with PIM selectivity below 1e-4 get at least 10x. Above 0.1 the best is 1.3x (Sec 6.4, Fig 11). D3 range is 2.2x–57x.
6. **Moving filtering from the bank to the subarray adds almost nothing end to end.** SALP-8 is 14x faster than bank on the microbenchmark (Table 5) but only 1.1x end to end (Sec 6.1). Amdahl's law applies once the CPU-side fetch and aggregate dominate.
7. **PIMDAL's strongest GPU result is on scan-like and aggregate-like queries, and it is a kernel-only result.**
   - TPC-H SF40 (Sec 7.3): PIM beats the A6000/cuDF by 2.2x on Q1 and 3.3x on Q6. The GPU wins on the join queries (Q3, Q4, Q5).
   - 8 GB kernel-only (Sec 7.2): selection is 3.0x vs the GPU and aggregation 2.2x. Including transfers both fall behind the CPU.
   - Caveat: the A6000 here pays PCIe for its inputs. Our GPU keeps tables resident, so this does not carry over (see section 4).
8. **Launch/orchestration cost is mostly not quantified.** PIMDAL gives no launch-latency number. Membrane gives a mode-switch cost of 150 ns and a worst-case slowdown (Sec 4.4). Details in section 3(a).

### 2. Hardware model

| Item | PIMDAL (UPMEM, real HW) | Membrane (BFU, simulated) |
|---|---|---|
| Logic location | DPU per DRAM bank, 8 DPUs per bank, 64 per rank (Sec 2.2) | Comparator per bank interface (all-bank mode); alternatives: subarray (Fulcrum-style), rank, channel (Sec 3.1, 4) |
| Native ops | 32-bit add/sub only. Mul, div, float are software-emulated (Sec 2.2). In-order, up to 24 hardware threads, at least 11 needed for full pipeline (IPC max 1) | Equality and range compare on int/float, 2–64 bit widths with SIMD packing. AND-accumulates a bitmap across predicates. No string/regex (Sec 4.1) |
| Word width | 32 bit | 64 bits per burst per bank, one per tCCD_L (Sec 4.1) |
| Clock | 350 MHz (Table 3) | Not stated. Path delay 0.45 ns fits within tCCD_L. DRAM is DDR4-3200 |
| Peak per unit | 350 MOps, 628 MB/s read, 633 MB/s write (Table 2) | 1 compare per 64-bit burst per tCCD_L (Sec 4.1) |
| Unit count | 2,048 DPUs (Table 3). System 760 GOps, 1,286 GB/s read (Table 2) | 8 channels x 4 ranks x 16 banks (Table 2). Bank-level filter 4.29 TB/s on one column (Table 5) |
| Memory per unit | 64 MiB MRAM, 64 KiB WRAM, 24 KiB IRAM (Sec 2.2) | Row buffer plus 64-bit bitmap buffer plus small scratchpad (Fig 3) |
| Internal vs external BW | 1.29 TB/s internal vs CPU 79 GB/s. No separate host-to-PIM figure in the text | 4,286 GB/s bank vs 37 GB/s channel, 141 GB/s rank (Table 5) |
| Communication between units | None. Via the host only: serial, broadcast, parallel and scatter/gather copies (Sec 2.2, 5) | None. The scheme relies on aligned, bank-local data (Table 1 test 3) |
| Host interface | Host copies columns in and results out. Async transfers and execution supported (Sec 5.3) | `pim_begin()`, `PIM_CONF`, `PIM_FILTER` per page, `pim_end()` (Sec 4.4) |
| Area and power | Not given | 0.1% area, 2.3% rank power, 4x all-bank peak power. Energy efficiency 3.6x SSB / 3.1x TPC-H (Sec 5) |
| Baselines | Xeon Gold 6226R, 79 GB/s. A6000: 108 SMs, 768 GB/s. PyArrow, cuDF (Table 3) | Xeon Silver 4314, 8-ch DDR4-3200, DuckDB (Table 2) |

### 3. Per-operator and cross-cutting facts

**Filter / selection**
- PIMDAL (Sec 4.3): threads handle contiguous blocks, filter in the scratchpad, wait for an offset handshake from the previous thread, then store at that offset. No host step. Selection scales linearly to 11 threads. Utilization about 80%.
- Membrane: the filter produces a bitmap. The CPU then fetches the selected rows (Fig 4). Bank-level filtering reduces filter time to a negligible share.
- Results:
  - PIMDAL 8 GB kernel only: 4.5x vs CPU, 3.0x vs GPU (Sec 7.2, Fig 24).
  - PIMDAL 8 GB with transfers: slower than CPU. At 32 GB the text blames transfer times that "grow disproportionally" (Fig 25).
  - Membrane: 5.92x/6.38x end to end, 1.89x/1.59x over rank-level, 3.7x/3.15x over channel-level.
- Why it wins (Membrane Sec 3.2): streaming, no reuse, one comparison per word, aligned data parallelism. Why it can lose (PIMDAL Q6): low selectivity.

**Aggregation / group-by**
- PIMDAL (Sec 4.4):
  - Hash-based: threads insert into a shared hash table in the scratchpad using mutexes. Conflicting elements are written back to the input array. "Efficiently partitioning the hash table for aggregation is not straightforward", so the authors skip partitioning.
  - Sort-based: quicksort the keys, then filter adjacent duplicates.
  - Hash is about 5x faster than sort at 50 groups (Sec 7.1). Hash time grows with the number of unique groups, sort time stays constant.
  - Hash performance drops beyond 11 threads from mutex contention.
  - Speedup: 1.5x vs CPU and 2.2x vs GPU kernel-only at 8 GB. Slower than CPU once transfers are included (Fig 24). Aggregation IPC is 90% on PIM vs 53% on CPU.
- Membrane: aggregation is better on the CPU. It has cache locality, needs more complex logic that is hard to localize in a bank, and needs costlier PIM units (Sec 3.2, Table 1). They keep aggregation, sort and group-by on the host.

**Sort / ordering**
- PIMDAL (Sec 4.1.1, 4.2):
  - Single core: in-place quicksort with two scratchpad buffers, one scanned from each end. Mergesort is also implemented. Iterative quicksort is 1.1x faster than recursive. The recursive one uses up to 38 KB of 64 KB scratchpad.
  - Multi-core: each core partitions, the host reorders ("these partitions are transferred to the host together with the indices, where they are reordered"), then each core receives a contiguous range.
  - "Single PIM-core sorting with aggregation on the host is often sufficient", so the multi-core path is often avoided.
  - Radix sort: 32 buckets per pass was optimal (Sec 7.1). IPC up to 0.92.
- Speedup: 2.3x vs CPU and 0.9x vs GPU including transfers at 8 GB. 2.5x vs CPU at 32 GB (Sec 7.2).
- Stated limiter: inter-PIM-core redistribution (Figs 22–23).

**Join**
- PIMDAL (Sec 4.5):
  - Radix hash join: (1) partition both relations and redistribute so each core receives one bucket from every other core, (2) build per-core hash tables on inner partitions, (3) partition the outer relation, (4) probe and write join indices.
  - Sort-merge join: multi-core sort, then each core merges its key range.
- Speedup: 0.6x vs CPU and 0.3x vs GPU at 8 GB. 2.0x vs CPU at 32 GB. The PIMDAL join is about 1.5x faster than unoptimized PID-Join and about 2x slower than optimized PID-Join (Sec 8).
- Membrane: avoids join on PIM entirely. Denormalization turns joins into filters. It cites PID-Join at only 1.14x end to end (Sec 3.2).
- Broadcast join helps "only for very small table sizes (order of 10 MB)" (PIMDAL limitations).

**(a) Launch / orchestration overhead**
- PIMDAL gives no launch-latency number. It does say the host-side C++ container and POSIX allocation overhead is significant at around 10 GB (Sec 5.2), and fixes it with Arrow plus jemalloc. Sync vs async execution is discussed in Sec 5.3.
- Membrane:
  - A mode switch costs 150 ns (Sec 4.4).
  - Worst case, a read forcing a mode switch after every GDL chunk raises filter latency 23.9x. It is still 5.4x faster than CPU filtering, and SSB geomean falls from 5.9x to 4.8x.
  - If each PIM burst runs at least 50 ns uninterrupted, the geomean is 5.7x.
  - While in all-bank mode, regular loads and stores are blocked. One thread issues PIM commands.
  - Setup is per column (`PIM_CONF` broadcast), and `PIM_FILTER` is per 4 MB PIM page (Sec 4.4).

**(b) Inter-unit communication**
- PIMDAL: host mediated only. Naive path: copy PIM to host, reorder on CPU, copy back. Improvement: scatter/gather (Sec 5.1) replaces the host reorder, and async transfers (Sec 5.3) let early ranks start. The result is still limited by host bandwidth and by processor-centric design.
- Membrane: none. It argues operands must be bank-local (Table 1 test 3). A hash join would need a copy of the hash table in every bank (Sec 3.2).

**(c) Operators that stay on the host**
- Membrane: everything except filtering (aggregation, group-by, sort, join, projection, row fetch).
- PIMDAL: moves all operators to PIM. In practice it keeps data loading, Arrow table assembly and redistribution on the host. It also states that single-core sort followed by host aggregation is often sufficient.

**(d) Operator sequences without returning to the host**
- Membrane: filtering several columns accumulates one bitmap with AND inside the BFU. Multiple predicates are chained inside memory. Everything after the bitmap returns to the CPU. No chained heterogeneous operators.
- PIMDAL: within one DPU, operators can run back to back from MRAM (for example sort then aggregate on the same core). Anything needing a different partitioning (join, multi-core sort) goes via the host.

**(e) TPC-H queries covered**
- PIMDAL: Q1, 3, 4, 5, 6 at SF40 (Table 4).
  - Average 3.9x over CPU.
  - PIM beats CPU on all of them except Q6.
  - Q4 has the highest speedup (no multiplication).
  - Q1 wins on high selectivity plus a lot of intermediate results.
  - Q3, 4, 5 wins come mainly from the join.
  - vs GPU: 2.2x on Q1, 3.3x on Q6, GPU wins the join queries.
- Membrane: Q3, 5, 6, 8, 10, 12, 14, 19 (Fig 7b) plus 13 SSB queries.
  - Geomean 5.92x SSB and 6.38x TPC-H at D3 (SF100).
  - Q19 is among the most selective (PIM selectivity 2e-5).
  - D1 without denormalization: Q6 and Q14 exceed 2x, most others gain little.

**(f) Scale factors and data sizes**
- PIMDAL: micro up to 4M 32-bit ints per core (16 MB), strong scaling 4 GB over 256–2,048 cores, weak scaling 2–32 GB, operator comparison 8 and 32 GB, TPC-H SF40 (Sec 6).
- Membrane: SF10, 20, 50, 100 (Table 3: SSB 6.8–23.5 GB, TPC-H 7.8–39.3 GB). Speedup rises with scale. D3 at SF10: 4.4x/5.0x, at SF100: 5.9x/6.4x (Sec 6.3). The authors explain that fixed engine overheads dominate at small scale.

**(g) GPU comparison and the GPU's bottleneck**
- PIMDAL: the TPC-H "limiting factor is main memory bandwidth". The GPU wins on joins because it avoids the redistribution cost PIM pays. Its transfer costs are included in timings but not broken out. PCIe numbers are not given.
- Membrane: no GPU comparison. It claims GPU and FPGA are limited by on-board memory capacity. An optimized FPGA filter on an Alveo U280 with HBM is at least 27.46x slower than Membrane including transfers (Sec 7). It notes that earlier GPU filtering work omitted data retrieval and post-processing, which it says take a large share of time.

**Stated limitations**
- PIMDAL: no variable-length fields. Hash aggregation contention beyond 11 threads. Host-bound transfers. Broadcast join only at about 10 MB. Inter-core communication needs hardware support.
- Membrane: needs OS and CPU changes (`pim_malloc`, a TLB bit, page-sized granularity, a cache-line swizzle unit). All-bank mode blocks regular accesses and needs about 4x peak power. Denormalization needs workload analysis. Strings are unsupported (dictionary-coded only). Simulated, with the DRAM part modeled in DRAMsim3 and the CPU part measured in DuckDB.

**Limitations I see that they do not state (inference)**
- PIMDAL's GPU baseline is cuDF on an A6000 with PCIe transfers and no query optimizer (Sec 6.2). It does not model a GPU with resident data. Sirius' warm iterations have no table PCIe traffic, so the "PIM includes transfer" comparison does not transfer to our setting.
- PIMDAL's DPU is a 350 MHz in-order scalar core with no multiply. Its hash aggregation is bounded by locks on a shared scratchpad table, not by bandwidth. Compute, not bandwidth, bounds it.
- Membrane evaluates only filter plus CPU. The 60% to 5.9x gain assumes a denormalized schema, which Sirius' TPC-H pipeline does not use. Its end-to-end gain is Amdahl-limited, and the bank-level hardware blocks regular memory access while active.
- Both papers use DDR4 DIMMs. Neither tests GDDR or HBM. GDDR7 and HBM have different banks per channel, shorter rows and different power budgets.
- Membrane's all-bank command is lockstep with a single address. It cannot do data-dependent addressing such as gather or hash probe.

### 4. Hypotheses 1–5 (my inference)

- **H1 (many kernels per operator): not addressed.** Neither paper counts kernel launches. The closest is PIMDAL's cuDF baseline, which gives no launch counts.
- **H2 (GPU idle most of the wall time): not addressed.** Neither paper measures GPU idle time. PIMDAL's GPU baseline is dominated by PCIe, a different regime from our resident-data one.
- **H3 (Q1 group-by not yet memory-bound): not addressed, but PIMDAL is relevant evidence in the other direction.** Its UPMEM hash aggregation is compute-bound (mutex contention, no multiplier) at 0.56 ops/byte of DPU peak, so even a "memory-near" design can stay compute-bound.
- **H4 (no memory to SM to memory round trip): partly supported, for filter only.**
  - Support: Membrane's bank-level filter is 4,286 GB/s vs 37–141 GB/s for outside-the-DRAM options. On the GPU, an HBM-base-die or bank-level unit would eliminate the DRAM-to-SM trip for filter.
  - Against: the filter wins only when selective. At PIM selectivity above 0.1, the maximum end-to-end gain is 1.3x.
  - The one-launch-per-step part of H4 is addressed by Membrane's `pim_begin` / `PIM_FILTER` per page / `pim_end` sequence. Host commands are still issued per PIM page and per column, so the host still orchestrates (Sec 4.4).
- **H5 (chain group-by then sort inside memory): contradicted for current designs, not for a redesign.**
  - Membrane argues aggregation is better on the CPU. PIMDAL's sort and join are bottlenecked by inter-core communication through the host.
  - Filter then compact then gather is the best-supported chain. Membrane already chains predicates inside memory into one bitmap. Compaction and gather are not evaluated, and gather needs data-dependent addressing that all-bank lockstep cannot provide.

**What would have to be different for "group-by then sort without leaving memory" to be viable (inference)**
1. **Reach across banks.** Logic in an HBM base die that can address every bank in a stack, so partitioning and merge do not need the host. PIMDAL's key weakness is that this does not exist on UPMEM ("will likely have to be implemented in hardware").
2. **A real arithmetic core, not a comparator.**
   - Needed operations: multiply and add for sum/avg, hashing, compare-and-swap for sort. UPMEM's 350 MOps/DPU with software multiply and a mutex-limited scratchpad shows what happens without them.
   - Membrane's BFU comparator is 0.001 mm² and 119 µW. Hash and sort units are far larger, and Membrane says "costlier processing units" are needed (Sec 3.2).
3. **Scratchpad size.**
   - UPMEM has 64 KiB per core, and recursive quicksort alone uses up to 38 KB of it.
   - Group-by needs a hash table. PIMDAL skips partitioning because the table does not fit.
   - The base die needs enough SRAM, or fast access to DRAM rows, to hold per-group state.
4. **A write path that lets intermediate results stay in memory, with addressable output.** Membrane writes an output bitmap into a PIM page (Sec 4.4). A group-by output needs variable-size writes.
5. **Concurrency with normal accesses.** Membrane's all-bank mode blocks everything else. A GPU needs the SMs to keep reading other data while PIM runs. Its worst-case 23.9x slowdown shows what interference costs.

**Compute per byte (modeled, my arithmetic from the papers' numbers)**
- Filter: about 1 compare per element. For a 16-bit column that is 0.5 op/byte. Membrane's 4,286 GB/s then implies about 2.1 T compare/s across the chip (modeled from Table 5, 2 B/element).
- UPMEM DPU peak: 350 MOps / 628 MB/s = 0.56 op/byte (from Table 2). System: 760 GOps / 1,286 GB/s = 0.59 op/byte. The CPU: 1,606 GOps / 79 GB/s = 20 op/byte.
- Group-by or sort needs far more than a compare per byte. A comparison sort of n 4-byte keys does about log2(n) compares per key, around 5 per byte at n = 1M, plus swaps and index math. Hash aggregation needs hash, probe, update and lock.
- So a group-by-plus-sort chain needs more than 10x the compute density of Membrane's filter at the same bandwidth. At roughly 5–20 ops per byte, a unit would need to be CPU-like in compute density, not a bank comparator. This is my estimate, not a number from either paper.
- PIMDAL's measurements support this direction: aggregation kernel-only reaches only 1.5x the CPU, even with 1.29 TB/s of internal bandwidth vs 79 GB/s.
- Compare to our GPU (inference): the RTX 5070 has 672 GB/s. Bank-level internal bandwidth multipliers of about 21x (4,286 / 204.8 GB/s for 8-channel DDR4-3200) are a DDR4 figure. A GDDR7 or HBM bank-level multiplier would differ and has to be modeled from their bank counts.

### 5. Not determined
- PIMDAL per-query TPC-H bars (Fig. 26), time breakdowns (Figs 22–23), and strong/weak scaling values: these are only in figures I could not read. Host-to-PIM bandwidth and launch latency are not stated numerically in the text I retrieved.
- Membrane DRAM tCCD_L and the per-bank rate in GB/s are not stated. I inferred about 1.05 GB/s per physical bank from 4,286 GB/s over 4,096 banks, which is my arithmetic.
- No data on group-by or sort in HBM or GDDR PIM from either paper.

### 6. What to measure or look up next
- Re-read PIMDAL Sec 5, Sec 7 and Fig 22–26 directly (PDF) to get the host-transfer share and per-query numbers.
- From our nsys/ncu data, measure ops per byte and selectivity per filter in the Sirius TPC-H queries, then apply Membrane's selectivity curve (Fig 11) to estimate which of our filters would gain.
- Check Samsung HBM-PIM and SK hynix AiM papers for bank counts, command bandwidth and base-die options to replace the DDR4 numbers.

### 7. Files written
- `/home/sai/cs254_project/pim_exploration/papers/model_parameters.csv` (83 data rows). No scripts, because all values are transcribed from the papers. Derived numbers in the text (0.56 op/B, 20 op/B, 21x, 1.05 GB/s per bank) are hand arithmetic from the table values.
