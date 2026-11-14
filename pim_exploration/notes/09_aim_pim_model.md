# AiM PIM model: database processing unit, operators and chains

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## AiM-PIM builder: database processing unit on aim_simulator — results

Everything below is CPU-only and regenerates in about 30 s (commands at the end). Every number comes from `sim/aim_pim/results/*.csv` and carries one of these labels: *simulated* (Ramulator2), *modeled* (an assumption I state), or *measured* (a real-GPU file). I compute no speedups against Vortex.

### 1. Main findings

1. **Project-owned build and regression pass.** `sim/scripts/setup_aim.sh` applies the patches and builds `sim/aim_simulator` at 0f28a07 offline in about 40 s. The dependencies are copied read-only from `~/aimdb/CENT/aim_simulator/ext`. The owner's fused Q6 trace gives exactly **20,865 cycles at SF1** (10.43 µs; with the 0.187 µs CXL return that is the README's 0.011 ms) and **207,089 cycles at SF10**. The functional result at SF0.01 matches DuckDB exactly. Source: `results/owner_q6_regression.csv`.
   - `git -C sim/aim_simulator diff` equals 0001 + 0002 applied in order. I checked this by reset, re-apply and `cmp`.
2. **Refresh now fires and costs 7–9 %** (simulated).
   - Upstream never refreshed: the AllBank manager loops over a "rank" level that GDDR6 does not have. It also had nREFI and nRFCpb swapped in the preset order, and indexed `tRFC_TABLE[0][-1]` (undefined behaviour) for the AiM density.
   - The 0002 patch fixes all three. The fix is opt-in through `refresh_without_rank: true`, so the owner's regression stays bit-identical. Settings: tREFI 1.9 µs, tRFC 120 ns.
   - Cost: +7.2 % on the owner's Q6 at SF1, +9.4 % at SF10, and 7–9 % on every workload (the `refresh_cyc` column).
3. **Execution order matters more than any circuit timing.** The data layout is a row-tile: each DRAM row of a bank holds T records of every column used, plus scratch space for intermediates, mask slots and a header word. In lockstep all-bank mode every operand must sit in the open row.
   - Operator-at-a-time (each general operator sweeps every row, as Sirius launches kernels) re-activates every row once per operator. Row activation/precharge is then **69–78 % of the time**.
   - Tile-at-a-time (the whole chain of general operators runs on one open row before moving on) is **2.5–2.8× faster**:

     | Chain, SF1, 1 channel | Operator-at-a-time | Tile-at-a-time |
     |---|---:|---:|
     | Q6 main | 969 µs | 386 µs |
     | Q1 | 6,610 µs | 2,345 µs |

   - Tile-at-a-time ordering is exactly what an in-memory sequencer provides.
4. **Q6 as a chain of general operators costs 6–9 % more than the owner's fused command.**
   - The main chain is 4 general operators: compare, compare AND, compare AND, then a masked multiply-accumulate.
   - SF1, 1 channel, tile-at-a-time: **385.6 µs**, 218 GB/s of input, i.e. 43 % of the 512 GB/s internal peak.
   - The owner's fused variant on the same channel: **362.9 µs**.
   - Full device (32 channels): **12.13 µs** unfused against **11.18 µs** fused (both with refresh; 10.43 µs fused without refresh).
   - Variants that write the product back to the row:
     - MUL with write-back, then masked SUM: 825 µs.
     - The Sirius mirror (two int32→int64 casts, a 64×64 multiply, then SUM): 1,782 µs, i.e. 4.6× the main chain.
   - The write-backs need scratch space in the row, which shrinks T from 128 to 64 to 32 and adds turnarounds.
5. **Q1 is compute-bound in the bank unit, not bandwidth-bound** (simulated).
   - SF1, 1 channel, tile-at-a-time: 2,345 µs. Input runs at 51 GB/s; column commands run at 279 GB/s internal.
   - T is only 32: 25 bytes per record of intermediates (1−disc, disc_price, 1+tax, charge, group key) must fit in the 2 KB row next to 20 bytes per record of input.
   - Five group aggregates plus a count, at 4 values per 2-cycle slot, make up about 40 % of the column commands.
   - All 4 groups match DuckDB exactly: every sum and count, with averages derived on the host.
6. **Host-paced issue only works if commands stream.** Counts are in `chains.csv`; the costs are modeled.

   | Chain, SF1, 1 channel, tile-at-a-time | Host-issued commands | Posted-write cost (1 ns each) | Synchronous cost (300 ns each) | Sequencer host commands |
   |---|---:|---:|---:|---:|
   | Q6 main | 11,732 | 11.7 µs, hidden | 3.9 ms (10×) | 9 |
   | Q1 | 199,470 | 199 µs, hidden | 62 ms (27×) | 197 (192 are group-accumulator read-outs) |

   - A posted write means each command is a 32-byte write over the channel's 32 GB/s link, overlapped with execution. Synchronous means each command waits one GPU-to-DRAM round trip of about 300 ns.
   - Both per-command costs are weak; neither is measured.
   - A sequencer adds about 0.6 µs (start plus completion).
7. **Normalized to the same memory** (modeled, linear in channels).

   | Chain, SF1, tile-at-a-time | 1 channel | S1 (0.4375 ch) | S4 (1.75 ch) | RTX 5070 (21 ch), linear | RTX 5070, direct 1/21 simulation | Layout transform (one-time) |
   |---|---:|---:|---:|---:|---:|---:|
   | Q6 main | 385.6 µs | 881 µs | 220 µs | 18.36 µs | 18.40 µs | 250 µs |
   | Q1 | 2,345 µs | 5,359 µs | 1,340 µs | 111.6 µs | 112.0 µs | 357 µs |

   - Linear scaling and direct simulation of a 1/21 share agree within 0.4 %.
   - The layout transform is the cost of moving the columns from the GPU's interleaved layout into row-tiles, estimated as reading and writing every input byte once over the external bus. It is one-time per table load, but it is **14× the Q6 chain time** and 3× the Q1 chain time.
8. **Not executable at bank level: gather, hash build/probe, sort/merge/radix partition, the inter-bank part of a prefix scan, and strings/LIKE.** Compaction works only bank-locally.
   - Reason: one shared row/column address, no inter-bank path.
   - Cheapest extensions, on paper only, with no timing faked:
     - A per-bank column-address register gives a gather inside the open row only.
     - A gather across rows needs per-bank ACTs, which is ordinary DRAM access with no gain.
     - Hash and sort need a base-die router (HBM) or the GPU.
     - A broadcast "join" works only against key sets small enough for the global buffer.
   - Small-set IN-lists (≤ 8 keys) are executable as OR-ed equality compares.

### 2. Tables

**Micro-suite: 1 channel, simulated, time in µs at SF 0.01 / 0.1 / 1** (`results/operators.csv`; all checks equal DuckDB)

| Operator (main variant) | Time (µs) | T | Input GB/s at SF1 | Compute / row overhead / read-out / refresh (%) | ISRs at SF1 |
|---|---|---:|---:|---|---:|
| Predicate, int32 date → 1-bit mask | 0.98 / 10.3 / 103.1 | 480 | 233 | 47 / 45 / 0 / 8 | 1,566 |
| … + GPU read of the bitmask | 1.40 / 14.3 / 141.6 | 480 | 170 | read-out 25 % | 26,590 |
| … bool8 output (cuDF format) | 1.08 / 11.4 / 114.2 | 480 | 210 | | 1,566 |
| Predicate, 64-bit decimal | 2.15 / 21.3 / 212.0 | 224 | 226 | 2.06× the int32 version | 3,352 |
| Range AND range (one operator) | 2.11 / 21.3 / 212.0 | 224 | 226 | as 2 operators: 322.2 | 5,028 |
| Compaction: mask → ids + per-bank count, host-paced | 1.64 / 17.3 / 172.0 | 224 | | 30 / 62 / 0 / 7 | 11,728 |
| Compaction, sequencer (max count over the 16 banks) | 1.22 / 12.6 / 127.2 | 224 | | | 6,858 |
| … + GPU reads the packed segments (host-paced / sequencer) | 340.3 / 295.5 at SF1 | | | read-out 45–52 % | |
| Element-wise int32×int32 → int64, written back | 5.25 / 52.2 / 522.0 | 96 | 92 | 36 / 56 / 0 / 8 | 23,449 |
| Element-wise int64×int64, written back | 845.7 at SF1 | 64 | 114 | | |
| Widen int32 → int64, written back | 349.4 at SF1 | 160 | 69 | | |
| Sum, int32 / int64 | 92.8 / 192.8 at SF1 | 480 / 224 | 259 / 249 | | |
| Group sum + count (≤ 8 groups) | 1.80 / 16.9 / 167.8 | 512 | 107 | 70 / 21 / 0 / 9 | 1,531 |
| IN-list of 8 keys (one operator) | 2.72 / 25.6 / 253.3 | 512 | 47 | as 8 separate operators: 607.3 | 6,606 |

**Per-command timing** (`results/isr_timing.csv`, 64 back-to-back ISRs)
- Every new read-class command (CMP16, ALU16, MUL16, GAG16) times like MAC16 in the main configuration:
  - a full row on an open row: 128.9 cycles;
  - a full row that opens a new row: 225.3 cycles.
- PUWR16 (internal write-back): 128.4 cycles on an open row, 218 cycles on a new row.
- Read 8 + write 8 words on a new row: 150 cycles.
- The GPU reading 1 word per bank across 16 banks is activation-bound at 6.2 cycles per word, about **10 GB/s per channel against 32 GB/s**. This is why mask and segment read-out is expensive.

**Sensitivity** (SF1, 1 channel; time relative to main; `results/sensitivity.csv`)

| Change | Q6 main, tile | Q6 main, operator | Q1, tile | Micro-op |
|---|---:|---:|---:|---|
| Compare 2 → 4 cycles | 1.33 | 1.13 | 1.03 | predicate 1.50 |
| Multiply slot 2 → 4 cycles | 1.26 | 1.10 | 1.12 | element-wise multiply 1.17 |
| Multiply slot 2 → 8 cycles | **1.78** | 1.30 | 1.38 | element-wise multiply 1.54 |
| Group aggregation 2 → 4 cycles | — | — | 1.25 | group sum + count 1.76 |
| tRFC 120 → 210 ns | 1.04 | 1.06 | 1.06 | |
| Write turnaround 0 / 22 cycles (main 11) | 1.00 / 1.00 | | 0.88 / 1.16 | |
| No 10 ns PU offset on ACT→first read | 0.92 | 0.87 | 0.95 | |

The result is most sensitive to the multiply throughput (multipliers per bank) and, for Q1, to the group-aggregation adder width. The operator-at-a-time numbers are less sensitive because row overhead dominates them.

**Real Sirius kernels → PIM operators** (`results/sirius_to_pim_mapping.csv`; counts from the nsys kernel lists, all launches matched)
- **Q6 SF1, 47 launches.** Mapped:
  - the AST predicate (3 launches) → 3 compares;
  - Mul (3) → masked multiply-accumulate;
  - sum (6) → accumulators plus read-out.
- **Q6, removed:** compaction (6 launches plus 1 size read-back per batch) and the int32 gathers (6). The 6 casts fold into the 32×32→64 multiply.
- **Q6, left out:** the Sirius min/max SUM-widening pre-check (9 launches; planner policy). 8 merge launches go to the GPU/host.
- **Q1 SF10, 873 launches.** Mapped:
  - LessEqual (12) → compare;
  - Sub/Mul/Add (48) → element-wise ops with write-back;
  - hash group-by (182) → key packing plus group aggregation with 8 accumulators.
- **Q1, removed:** compaction (37), numeric and string gathers (252). The casts (72) fold into the operator widths.
- **Q1, left out:** min/max pre-checks (180). 90 merge/average/sort launches go to the GPU/host.

**Host round trips a sequencer chain removes:**
- the compaction→gather size read-back: 1 per batch, so 3 in Q6 SF1 and 13 in Q1 SF10;
- Q1's group-count and shared-memory-fallback read-backs: 2 per batch.

The chain stores a short micro-program (about 16 entries), a row loop counter, the constants in the global buffer, a status flag, and the per-bank count and accumulator registers.

**What remains host-visible:** start, parameters (WR_GB), completion, one result read-out per chain, and for compaction the per-bank count read-out plus a prefix over 16 × channels banks.

Caveat: the "mask instead of compaction + gather" trick is a general masked-aggregate operator that a GPU could use too. What PIM adds is running it at internal bandwidth without SM round trips. Sirius' scalar and validity read-backs (Q6 has 14 read-back syncs per scan task) are software artifacts, not credited to PIM.

### 3. Design choices (detailed in `sim/aim_pim/isr_spec.json`)

- **Operand widths** are what cuDF/Sirius used: price, discount and tax int32 (×100); quantity int16; dates int32; products and sums int64; partial sums combined on the GPU in int128.
  - The per-column split is *inferred* from the 14.0 B/row Q6 footprint plus the int32 gathers and `device_cast<int,long>` in the kernel list.
  - Return flag and line status are 1-byte dictionary codes; cuDF keeps them as strings (1 B + 4 B offset). This favours PIM by 8 B/row in Q1.
- **Masks** are 1 bit per record. Each bank's unit has 4 mask registers of 512 bits. In operator-at-a-time mode masks are stored in the row's mask slot (ceil(T/256) words, written by PUWR16) and reloaded by the next operator; in a tile chain they stay in registers.
- **Compute-slot timing:**
  - Compare and ALU fit the 2-cycle MAC16 slot (Membrane reports 0.45 ns for its comparator).
  - Multiply: 4 32×32 multipliers per bank, 3-stage pipelined: 4 partial products per 2-cycle slot, 6-cycle latency. 64×32 needs 2 partials, 64×64 needs 3. This is about 4× the multiplier area of AiM's 16 BF16 MACs.
  - Group aggregation: 8 groups × 4-input adder trees, so 4 values per slot.
- **Write-back timing:**
  - Results go through an 8-word staging buffer.
  - Write-back after compute waits 2 cycles (6 after a multiply). A read after a write waits 11 cycles (nWTRL); precharge after a write waits 33 (nWR).
- **Compaction** packs in the bank, into the same row, in (bank, row, lane) order rather than record order.
  - A host-paced issuer does not know the counts and writes the whole slot.
  - A sequencer issues max-over-16-banks writes.

### 4. Not modeled / could not determine

- **Not modeled:**
  - Area, power and thermal: Membrane reports about 4× peak DRAM power in all-bank mode, and with 512 active banks the device would likely be power-limited.
  - Coexistence with normal GPU traffic: AiM mode is exclusive per channel and a mode switch costs 32 cycles.
  - The GPU→DRAM command path (only analytic).
  - The layout transform (only estimated).
  - Data loading.
- **Simulator artifacts and approximations:**
  - EOC does not wait for trailing conventional reads, which undercounts read-out by about one latency (under 50 cycles).
  - The data-dependent compaction write count uses channel 0's banks.
  - The ~0.9-cycle DMA overhead per ISR is included.
- **GDDR6 tRFC:** I used the preset's intent of 120 ns; the sensitivity run covers 210 ns.
- **The 1-channel → S1/S4/5070 scaling is modeled as linear,** and AiM GDDR6 stands in for GDDR7.

### 5. Next to measure

- Larger mask registers (T up to 2048) or a separate scratch row for intermediates to recover Q1's T.
- A per-bank column-address register (gather within a row) as a real command class.
- Power per command from AiM/CENT constants.
- Mixing PIM chains with GPU reads on the same channel.

### 6. Commands

- Build from a fresh checkout (≈ 40 s): `bash sim/scripts/setup_aim.sh --reset`
- Rerun everything (≈ 30 s; regression, spec, mapping, all workloads): `bash sim/scripts/run_aim.sh`
- Regression only: `/home/sai/aimdb/.venv/bin/python -B sim/aim_pim/regress_owner_q6.py`
- Workloads only: `cd sim/aim_pim && /home/sai/aimdb/.venv/bin/python -B run_all.py [--sf 0.01 0.1 1]`

### 7. Files

- **Patches:**
  - `/home/sai/cs254_project/sim/patches/aim/0001-owner-db-isrs.patch` (the owner's patch, unchanged)
  - `/home/sai/cs254_project/sim/patches/aim/0002-db-pu-isrs-refresh.patch`: 5 new ISRs (`PCMP_ABK`, `PALU_ABK`, `PMUL_ABK`, `PGAG_ABK`, `PWB_ABK`) mapped to their own commands (CMP16, ALU16, MUL16, GAG16, PUWR16), new timing parameters (nCCDCMP, nCCDALU, nCCDMUL, nCCDGAG, nPULAT, nPULATMUL, nPUWTR, nPUWR, all overridable from YAML), and the refresh/preset fixes.
- **Scripts:** `/home/sai/cs254_project/sim/scripts/setup_aim.sh`, `/home/sai/cs254_project/sim/scripts/run_aim.sh`
- **Code** in `/home/sai/cs254_project/sim/aim_pim/`:
  - `dbpu.py`: layout, functional model, trace generator, simulator driver.
  - `data.py`: DuckDB data and exact references.
  - `workloads.py`, `run_all.py`, `regress_owner_q6.py`.
  - `tools/write_isr_spec.py`, `tools/write_mapping.py`, `tools/make_db_pu_patch.py` (used only to author 0002).
- **Specification:** `/home/sai/cs254_project/sim/aim_pim/isr_spec.json`
- **Results** in `/home/sai/cs254_project/sim/aim_pim/results/`: `operators.csv`, `chains.csv`, `isr_timing.csv`, `normalization.csv`, `sensitivity.csv`, `owner_q6_regression.csv`, `sirius_to_pim_mapping.csv`.
- **Not to commit:** `sim/aim_pim/cache/` (256 MB of traces and npz data, git-ignored, regenerable), and the build and `ext/` directories in the submodule (already ignored upstream).
