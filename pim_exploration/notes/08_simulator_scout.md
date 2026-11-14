# Simulator scout: existing Vortex and AiM setups

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## sim_scout: what exists and how to build on it

I did not modify any of the owner's trees. One side effect: my `git status` / `git diff` calls refreshed the `.git/index` stat caches in `~/aimdb`, `~/aimdb/CENT`, `~/pim/vortex` and `~/pim/aim_simulator`. No tracked content changed (checked with `git status` afterwards). Next time, set `GIT_OPTIONAL_LOCKS=0`. All Vortex runs mounted `~/pim`, `~/aimdb` and `~/tools` **read-only** inside the container.

### 1. Most important findings

1. **The AiM toolchain works here today, and the README's 0.011 ms reproduces exactly.** SF1: 20,865 cycles × 0.5 ns = 10.4 µs scan + 0.187 µs CXL return = **0.011 ms**. SF10: 207,089 cycles, 0.104 ms. The functional check matches DuckDB exactly at SF0.01. I also built the simulator offline from two upstream commits, each with the owner's patch: the CENT-pinned `2eb1ee0` and the latest upstream `0f28a07` (in `~/pim/aim_simulator`). The patch applies cleanly to both, each build takes about 55–60 s, and both give the **identical** cycle counts. (`aim_q6/out/results_fused_sf1_sf10.txt`, `aim_build/rebuild_check.txt`)
2. **The Vortex toolchain also works without touching `~/pim`.** podman is available and `localhost/vortex-dev:22.04` (1.83 GB) is present. I ran the owner's prebuilt `tpch_q6` host binary with snapshot simx libraries, PoCL cache and HOME in my directory, and read-only mounts.
   - SF0.001: PASSED, 29,369 cycles, 3.0 s wall.
   - SF1 on h100_8ch with 64 cores: PASSED, **652,984 cycles (330 µs) = 164 GB/s = 19.5 % of 838 GB/s**, 160 s wall.
   - SF1 with fable's best memory fixes: 517,641 cycles = 207 GB/s = 24.7 %, 190 s wall.
   - (`vortex_q6/sf1_runs.out`, `vortex_q6/run_*/run.log`)
3. **The calibration wall has two causes, not one.** The README blames one row activation per 64 B line. A later diagnosis left untracked at `~/aimdb/vortex/sweep/logs/fable/` (Nov 11 23:17, after the README) shows:
   - **Cause (a): the simx L2 fill gate.** A cache bank accepts a new fill only when no fill is still in the pipe and no replay is pending (`sim/simx/mem/cache.cpp` `processInputs`). That gives about one fill per bank per ~8 cycles: 16 banks × 64 B / 8 = 128 B/cycle ≈ **253 GB/s (30 %)**.
   - **Cause (b): DRAM row locality.** The standalone harness `dramtest.cpp` drives `dram_sim.cpp` with Ramulator HBM3 and no Vortex. In-order 64 B lines reach **686–751 GB/s (82–90 %)**. Lines shuffled within a 4 MB window drop to **186–273 GB/s, with row hits falling from 97 % to 54–57 %**.
   - Fixing only one leaves the other. With 64 L2 banks, `L2_LATENCY=1`, queue 512 and a 128-thread-per-core grid, `vx_membw` reaches **471 GB/s (56 %)**, still far from the 90–95 % real GPUs stream at.
4. **The AiM model is timing-only, and the owner's three new ISRs are timing aliases.** `CMP_ABK` and `MMAC_ABK` map to `MAC16`, and `RD_MASK` maps to `RDMAC16`. The simulator moves no data, so correctness lives only in numpy (`q6_pim.py functional()`). Mask storage, the INT32 compare/MAC datapath, area, power and critical path are not modeled. Refresh is also never issued: the AllBank refresh manager loops over a "rank" level that GDDR6 does not have. That flatters PIM by roughly tRFC/tREFI, about 5–6 %; this figure is inferred, not measured.
5. **AiM's ceiling for streaming ISRs is about 57 % of its 16 TB/s.** Measured per-ISR timings on the patched latest build (`aim_micro/isr_timing.txt`):
   - A full-row `MAC_ABK 64` costs 128.9 cycles on an open row and **225.3 cycles when it opens a new row**.
   - The ~97-cycle row overhead (ACT→MAC 56 + MAC→PRE 12 + PRE→ACT 32) is not overlapped with compute: all banks step in lockstep with one row buffer each.
   - So 128/225 = 57 %, matching Q6's 9.2 TB/s of 16 TB/s.
   - Single-row ISRs cost 57 cycles; `WR_GB` / `WR_BIAS` / `RD_MAC` / `RD_MASK` pipeline at 2.5–3.5 cycles back to back (35 cycles alone).
6. **Multi-kernel baselines are feasible on Vortex, and buffers persist between launches.**
   - The existing `tpch_q1` already launches two kernels (`q1_partial`, then `q1_reduce`, which reads the first kernel's `cl_mem`) and PASSES.
   - An empty kernel launch costs **~17.7k simulated cycles (7 µs at 2.512 GHz)** on the rtx5070q build. That is mostly cold instruction-cache and argument misses at the 518-cycle DRAM latency; simx models no driver or host launch latency. Wall time per launch is under 0.1 s (`vortex_q6/empty_rtx5070q_g*/`).
   - Host-side gaps (Sirius median 7–34 µs per step, `notes/04`) must therefore be **added analytically**.
7. **The existing Vortex kernels are whole-query fused kernels.** Q6 is filter, multiply and sum in one kernel; Q1 is filter, group and aggregate in one kernel plus a reduce. That violates the project's no-fusion rule (memory `no-kernel-fusion`), so they are smoke tests, not baselines. The AiM ISRs, by contrast, are already general sub-operators (range compare into a mask, masked MAC, mask read-out).

### 2. Inventory

| Item | Upstream @ commit | Local modifications | State |
|---|---|---|---|
| `~/aimdb` (git, 2 commits, `69a5fc5`) | own repo | untracked `vortex/sweep/logs/fable/` (diagnosis harness, 5 lib snapshots, plot) | README current up to the Nov 11 15:00 sweep |
| `~/aimdb/CENT` | github.com/Yufeng98/CENT @ `4c2aac6` | submodule pointer dirty only | `cent_simulation/` is LLM-specific; `cxl_latency.py` and `cent_power_calculator.py` are reused |
| `~/aimdb/CENT/aim_simulator` | github.com/arkhadem/aim_simulator @ `2eb1ee0` (Jan 2025) | `src/base/request.h`, `src/dram/impl/GDDR6.cpp`, `src/memory_system/impl/aim_DRAM_system.cpp` (+49/−2). Identical to `aim_simulator_db_isrs.patch` (byte diff empty) | built Nov 10 (`build/ramulator2`, `libramulator.so` 183 MB, GCC 16 needs `-include cstdint`); works |
| `~/aimdb/P3-LLM` | github.com/yc2367/P3-LLM @ `0652325` | none | unrelated LLM quantization; ignore |
| `~/pim/aim_simulator` | same upstream @ `0f28a07` (Jul 2025) | clean, never built | 2 commits newer: adds LPDDR5-AiM (`test/example_LPDDR5.yaml`) and GDDR6 fixes (ACT→ACT nRC, per-bank RTP/WR→PRE). **Q6 is unaffected** (same cycles) |
| `~/pim/vortex` | github.com/vortexgpgpu/vortex @ `90a6262` (Oct 21) | `VX_config.toml`, `sim/common/dram_sim.{cpp,h}` (= `aimdb/vortex/patches/vortex_dram_knobs.patch`); `third_party/ramulator` @ `e62c84a` (CMU-SAFARI/ramulator2) with `generic_dram_controller.cpp` dirty (= `ramulator_queue_size.patch`). Untracked: `profiles/rtx5070q.json`, symlink `profiles/h100_8ch.json` → aimdb, `tests/opencl/{tpch_q1,tpch_q6,vx_membw,vx_latency}` | build dirs `build64` (default 4w×4t), `build64-rtx5070q`, `build64-h100x8`. **The h100x8 runtime libs currently hold fable's last config (64 cores, L2 64 banks, L2_LATENCY=1, queue 512), not the defaults** |
| `~/pim/q1_vortex`, `q6_vortex` | — | data exports (sf0.001–sf1 `.bin` + `meta.json`), logs, `vx.sh`, `container/Containerfile` (ubuntu 22.04 + build-essential, ocl-icd, boost …) | Q1 SF1 on the default core: 201.6M cycles, 262 s; rtx5070q Q1 SF0.1: 71.7M cycles, 107 s |
| `~/pim/gpu_bw` | — | `membw.cu` / `latency.cu` on the real 5070 | measured L1 116 B/cycle per SM, L2 3.26 TB/s (1,138 B/cycle chip), DRAM 637 GB/s; latency L1 52 / L2 350 / DRAM 858 cycles at 2.866 GHz |
| `~/tools` | llvm-vortex 421 MB, riscv64-gnu-toolchain 1.4 GB, pocl, libc64, libcrt64 | — | used read-only by the container |

**`tpch-q6-on-a-gpu.html`**
- Method: Q6 written as one OpenCL kernel.
  - Columns are stored as exact fixed-point at the narrowest width: price i32, quantity and ship date i16, discount i8, so 9 B/row.
  - Each thread does a grid-stride loop with a branch-free predicated sum in a register, then a work-group tree reduction in local memory, then a host sum of the group results.
- Runs on Vortex simx at SF0.001–SF1, matching DuckDB and the TPC-H reference answer exactly.
- Compares a small default core (4 warps × 4 threads, 128 B/cycle memory) with a "quarter RTX 5070 SM" core (16 warps × 8 threads, 1.39 B/cycle GDDR6).
- Conclusions:
  - On the quarter-SM core, Q6 is memory-bound at 84 % of the bandwidth limit (a copy test reaches 92 %). SF1 takes 47.8M cycles, about 19 ms at 2.512 GHz.
  - On the small core it is latency-bound at under 1 % of bandwidth, and reads 1.78× its input: 16-thread groups touch only part of each 64 B line before eviction (9.61 MB predicted, 9.62 MB measured).
  - Lesson: time follows bytes read, not selectivity. That run used `MEMORY_LATENCY = 0`. The current build adds 518 cycles of latency, and the same SF0.1 run now takes 14.5M cycles (27 % of bandwidth, latency-bound; `q6_latency_sf0.1.log` and my rerun).

**`what-limits-a-gpu-kernel.html`**
- Method: the Q1 scan kernel on Vortex, analyzed with a roofline (IPC roof 1 per core; 128 B/cycle memory) and a sweep of 4–32 threads per warp × 4–16 warps.
- Default core: Q1 is latency-bound. IPC 0.36, core 64 % idle, 2 % of bandwidth, about 2.75 instructions issued per 28-cycle load wait.
  - More warps help up to 8 (IPC 0.57); at 16 warps the 16 KB L1 thrashes.
  - Wider warps help most: 32 × 4 is 5.26× faster because instructions fall 6×. Lane use drops to 63 %, divergence rises to 20 %. 32 × 16 is slower again (169 MB of DRAM traffic).
- Quarter-SM core: the same kernel becomes memory-bound at 94 % of 1.39 B/cycle, but moves 93.2 MB for 22.8 MB of columns.
  - Waste 1: the 36 per-group accumulators live in memory because of dynamic indexing. A deliberately wrong register-only variant moves 28.6 MB and runs 3.3× faster.
  - Waste 2: 8-byte columns; narrow types would give 12 B/row instead of 38 (estimated, not run).
- 5070 ncu classes: decode is latency-bound, shmem aggregation is latency-bound (0.7 wave), DeviceReduce is memory-bound at 76 %.
- Lesson: fixing one limit exposes the next.

### 3. Vortex: how the baseline is simulated

- **Driver:** `VORTEX_DRIVER=simx`, a cycle-level C++ model (rtlsim exists but was not used).
  - The OpenCL path is PoCL plus the Vortex backend: `kernel.cl` is compiled at **run time** by llvm-vortex, using `POCL_VORTEX_CFLAGS` that carry every `-DVX_CFG_*`.
  - Native tests (`tests/regression/*`) use the vortex2 API (`vx_enqueue_write/launch/read`, multi-kernel modules; see `regression/multikernel`).
  - All `VX_CFG_*` are **compile-time**. `make run-simx CONFIGS="-D…"` rebuilds `libsimx.so` in the build directory, which is why every config change writes into the build tree. Fable's workaround: build once, snapshot `libsimx.so`, `libvortex-simx.so` and `libvortex.so` plus the `make -n` command line, then run anywhere.
- **Data loading:** the host reads `.bin` columns and calls `clCreateBuffer` + `clEnqueueWriteBuffer` (a functional copy into simulated RAM, not timed as PCIe). The kernel then reads them through L1 → L2 → `dram_sim` (Ramulator2 per channel; `channel = line % NUM_BANKS`; 128 B row visit by default).
- **Counters:** `VORTEX_PROFILING=<class>`.
  - Class 1: core and scheduler stalls.
  - Class 7: memory, i.e. `PERF: memory: reqs (r/w), lat, bank_st`, L2 hit/miss and coalescer.
  - Always: `instrs` (warp instructions), `cycles`, IPC.
  - `ramulator.stats.log` in the cwd: per-channel row hits, misses, conflicts and average latency.
  - In the 2-kernel Q1 run, instructions and cycles look cumulative, but `memory: reqs` (769) was **smaller** than in the 1-kernel run (6,302). The memory counters probably reflect only the last launch. Not verified; check before using per-kernel memory counters.
- **Profiles:**
  - `h100_8ch`: h100 core (64 warps × 32 threads, issue 4, 256 KB L1), 33 cores by default (swept 1–64), L2 8 MB, 16 ways, 16 banks, HBM3 8 channels × 128-bit × 6545 MT/s = 837.8 GB/s, 256 DRAM banks, core clock 1980 MHz.
  - `rtx5070q`: 1 core, 16 warps × 8 threads, issue 4, ALU/FPU 4/4, TCU on, I$/D$ 16 KB 4-way (D$ write-back, 1 bank), LMEM 16 KB, L2 256 KB 16 ways 1 bank, L3 off, GDDR6 1 × x16 @ 1750 MT/s = 3.5 GB/s, 2512 MHz, `PLATFORM_MEMORY_LATENCY = 518`.
  - Note: the json's "sources" text says latency was "left at the default", but the value is 518. My inference is 858 measured cycles at 2.866 GHz ≈ 300 ns ≈ 750 cycles at 2.512 GHz, minus the Ramulator/pipeline part. Verify with the owner.
- **Speed and limits (h100_8ch, Q6 SF1, `SIMX_MT=8`, from `sweep/logs/sf1/c*_class7.log`):**

| cores | 1 | 2 | 4 | 8 | 16 | 24 | 32 | 48 | 64 |
|---|---|---|---|---|---|---|---|---|---|
| wall s | 27.8 | 17.4 | 13.1 | 22.8 | 30.0 | 39.5 | 53.1 | 88.3 | 131.3 |

  - That is 46k–458k rows per wall second.
  - rtx5070q (1 core × 128 threads) Q6: SF0.01 = 5.9 s, SF0.1 = 34.6 s (14.5M cycles, ~420k cycles/s, 17k rows/s).
  - Rule of thumb: wall ≈ cores × simulated cycles / (2–4.6 × 10^5 core-cycles/s), with roughly linear dependence on rows.
  - Largest scale run: SF1, which is about 6 min per point on a latency-bound 1-core config.
- **Commands that worked** (in `sim_scout/vortex_q6/`):
  ```
  ./vx_ro.sh bash run_q6_ro.sh q128m128rv5 0.001 16384 256            # fable lib snapshot, 64 cores
  VX_WORKDIR=/home/sai/pim/vortex/build64-rtx5070q/tests/opencl/tpch_q6 ./vx_ro.sh \
     'make -n run-simx OPTS="@@OPTS@@" | grep VORTEX_DRIVER=simx | tail -1' > cmdline_rtx5070q_q6.txt
  ./vx_ro.sh "bash run_app_ro.sh $PWD/cmdline_rtx5070q_q6.txt <app dir> tpch_q6 <tag> 7 '-d <data> -g 2048 -l 128' [kernel.cl]"
  ```
  The optional `kernel.cl` argument swaps the kernel source, because PoCL compiles at run time; that is how I ran the empty-kernel probe.
  A *new configuration* needs its own build. Either clone Vortex into the project and build there, or `cp -a ~/pim/vortex` (the tree with build dirs and third_party is about 170 MB). A simx-only rebuild is about 1 minute (`smoke.log`, `build_*.log`); a full clean `make` is several minutes (not timed).

### 4. Calibration: mechanism and options

- **Evidence:**
  - Default `vx_membw`: 126 GB/s (15 %).
  - Best of the README knobs (queue 128, 128 MSHRs, row visit 1 KB, 256 threads per core): 242 GB/s.
  - The 2nd-pass marginal rate equals the 253.4 GB/s fill gate.
  - Then 64 L2 banks gives 372 GB/s; adding `L2_LATENCY=1` gives 448; that plus 128 threads per core gives 471.
  - DRAM-only, queue 512, 1 KB requests: 741–749 GB/s at 96 % row hits.
  - My Q6 SF1 Ramulator stats: 70.2 % read row hits, 876k conflicts.
- **Mechanism:** about 131k threads interleave 64 B lines over a multi-MB address window. Each channel's FR-FCFS queue (32) sees lines from many rows, so rows are reopened. HBM3 with tRRD 4 ns and tFAW 15 ns then caps each channel. On top of that, simx L2 banks serialize fills. Real GPUs avoid this with sectored, coalesced 128 B+ requests, deep controller queues and address hashing.
- **Options:**
  - **(A) Analytic correction (least work).** Scale memory-bound kernel time by the `vx_membw` stream efficiency of the same config, e.g. 0.195 → 0.90. Report raw and corrected numbers side by side. Weakness: it is only valid for memory-bound phases.
  - **(B) Model fixes (most defensible).**
    - Raise L2 banks and MSHRs, and make the fill path pipelined: one fill per cycle per bank instead of one per pipe depth. This is a small simx change.
    - Queue 256–512, `ROW_VISIT_BITS = 5`.
    - Bigger requests per transaction (`MEM_BLOCK_SIZE` 128).
    - Validate with `vx_membw` until it reaches ≥ 85 %, then freeze.
  - **(C) Change the standard to GDDR6** at a low per-channel rate with many channels (this matches the 5070 better; see §7). The `rtx5070q` single-channel run already streamed at 92 %, because one narrow channel and few requests do not thrash rows.
  - Recommendation: (C) plus (A) as a cross-check, and (B) only if a wide HBM config is required.

### 5. AiM side

- **Organization (`GDDR6_AiM_org`):** 32 channels (fixed; `MAX_CHANNEL_COUNT 32`) × 4 bank groups × 4 banks = 512 PUs per device. 16K rows; the trace uses 64 × 256-bit columns = 2 KB per row. tCK 0.5 ns.
  - One global buffer per channel (256-bit registers), MAC accumulator registers per bank (`WR_BIAS` / `RD_MAC`), AF registers and LUT.
  - The host-side DMA holds 256-bit GPRs and CFRs (`AFM`, `BROADCAST`, `EWMUL_BG`).
  - LPDDR5-AiM exists only in upstream HEAD. There is no HBM model.
- **Timing (`GDDR6_AiM_timing`):** nCCDL = 2 cycles between MAC16s, so each all-bank column op reads 32 B × 16 banks per ns = 512 GB/s per channel, 16.4 TB/s per device.
  - nRCDRDMAC 56, nRTP 12, nRP 32, nRAS 54, nRRD 11; nRC 89 is enforced in HEAD only.
  - Upstream bug: the preset list orders nRFC/nRFCpb/nRREFD/nREFI differently from `m_timings`. It is moot, since refresh never fires.
- **ISR set:** `WR_SBK`, `WR_ABK`, `WR_GB`, `WR_BIAS`, `RD_MAC`, `RD_AF`, `RD_SBK`, `COPY_BKGB`, `COPY_GBBK`, `MAC_SBK`, `MAC_ABK`, `AF`, `EWMUL`, `EWADD` (no-op), `SYNC`, `EOC`, plus conventional `R`/`W MEM`, GPR and CFR.
  - Trace lines look like `AiM <ISR> <fields>`, `R|W MEM ch bank row`, `W GPR n`, `W CFR addr data`.
  - The DMA unrolls `opsize` into per-column, per-channel requests. AiM requests are served **in order** per channel and are mutually exclusive with conventional R/W (a mode switch costs TMOD 32 cycles when register-RW mode toggles). `RD_MAC` / `RD_AF` / `SYNC` / `EOC` block the DMA.
  - Statistics: `memory_system_cycles`, per-channel command counts, per-ISR issue-to-final cycles, active/precharged/idle cycles.
- **Owner's patch:**
  - `CMP_ABK opsize chmask row`: INT32 range compare against global-buffer constants, AND into a per-bank mask. Timing = MAC16.
  - `MMAC_ABK`: within one open row, the first half of the columns is operand a and the second half is b, optionally range-checked into the mask; acc64 += mask ? a·b : 0. Timing = MAC16.
  - `RD_MASK gpr chmask`: blocking. Timing = RDMAC16.
  - Not modeled: values, mask register count and size, the 64-bit accumulator width, any extra pipeline depth for compare+AND or a 32×32 multiply, area, power, and mask spill.
- **Changing AiM — `q6_pim.py`:** a 256-record tile per bank, 2 rows per tile (row 2t = shipdate | quantity, row 2t+1 = price | discount). Per tile: 2 `CMP_ABK 32`, then `MMAC_ABK 64`. Then 4 `RD_MAC`. Time = cycles × 0.5 ns + one 8 B CXL return.
- **Changing AiM — how to add an op:**
  1. `request.h`: add an `Opcode` enum value, `aim_opcode_to_str`, and `opcode_str_to_aim_ISR` with fields and the blocking / reg-mode flags.
  2. `GDDR6.cpp`: add it to `m_aim_requests` and map it in `m_aim_request_translations` to a DRAM command. For new timing, add a new command plus its scope, meta, timing rows and preq/action lambdas, instead of reusing MAC16.
  3. `aim_DRAM_system.cpp`: add the decode case.
  4. A functional model in Python, as for Q6.
- **Built-in assumptions every new circuit must respect:**
  - One command broadcasts the same row and column to all 16 banks of the selected channels (lockstep, one shared address; no per-bank addressing, so no gather).
  - Operands must sit in the open row or the global buffer.
  - Results leave only via per-bank registers read by `RD_*` into host GPRs (32 B per channel per op), or via `COPY`/`WR` back into banks.
  - There is no inter-bank or inter-channel path except through the host or global buffer.
  - AiM and normal traffic are serialized per channel.
- **CENT on top:** a CXL device model (analytic `cxl_latency.py`: 8 GB/s per lane, x4 device, x16 host, 180 ns RTT, multicast factor), PNM (8 RISC-V cores, reduction trees, accumulators, exp units, SRAM buffers; cycle and power constants in `cent_power_calculator.py`), and LLM trace generators.
  - For GPU-attached PIM, the CXL link, the host x16 pull, the multicast adjustment and the PNM RISC-V unit are irrelevant.
  - Instead you need a GPU-side command-issue cost (ISRs from the SM or memory controller) and the GPU memory-controller interleaving: the GPU spreads lines over all channels, while AiM needs whole tiles per bank. A layout transform is required, and its cost is unmodeled.

### 6. Gaps per operator

| Operator | Start from | Missing |
|---|---|---|
| predicate → mask | AiM `CMP_ABK` (timing only); Vortex Q6/Q1 inline predicates | a general mask-out kernel on Vortex; mask storage and write-back to a bank (`COPY`-like) and multi-predicate combine semantics in AiM |
| mask → compaction + count | nothing | AiM has no variable-length output; it needs a per-bank prefix count, a write pointer and a count read-out; the Vortex kernel (scan + scatter) |
| gather (fixed width, strings) | nothing | lockstep shared address forbids per-bank indices; it needs per-bank address registers (new command class) or a host-issued `RD_SBK` stream (~88 cycles each, measured); Vortex kernels |
| hash build / probe / retrieve | nothing | per-bank hashing plus CAS; cross-bank routing; Vortex kernels (atomics exist in simx: `VX_CFG_EXT_A`) |
| hash group-by | `MMAC_ABK` (masked accumulate, one group per pass) | multi-accumulator by key, atomics |
| dynamic-filter membership | `CMP_ABK` for ranges or small IN-lists | Bloom or set probe |
| sort (merge, radix) | nothing | inter-bank permutation; histogram plus scatter |
| element-wise / casts | `MAC_ABK` / `EWMUL` (BF16 semantics, MAC16 timing) | INT/decimal add, mul, compare, widen as ISRs (timing aliases are easy) |
| prefix scan | nothing | intra-bank adder chain plus cross-bank carry via the global buffer |

Vortex side: only fused Q1/Q6 kernels and the `vx_membw` / `vx_latency` probes exist. Every operator kernel (mask, compact, gather, hash, sort, scan) has to be written. They are best written as OpenCL in `tests/opencl/<op>`, chained by a host program that keeps `cl_mem` buffers resident and reads back counts between launches, as Sirius does.

**Repository layout (recommended):** git submodules pinned to upstream, with patches as files, the same pattern as Sirius and cuDF.
```
sim/vortex            -> vortexgpgpu/vortex @ 90a6262   (+ third_party/ramulator @ e62c84a via its own submodule)
sim/aim_simulator     -> arkhadem/aim_simulator @ 0f28a07 (latest; owner patch applies, results identical)
sim/patches/vortex/{vortex_dram_knobs,ramulator_queue_size}.patch, sim/patches/aim/db_isrs.patch (+ new ISRs)
sim/tests/            -> our OpenCL operator tests + profiles/*.json (symlinked/copied into the Vortex tree by a setup script)
sim/scripts/          -> setup.sh (init submodules, apply patches, offline deps), vx.sh (container), trace generators
```
Do not vendor: Vortex is about 170 MB with third_party, and each aim_simulator build is about 400 MB. Keep build directories untracked. The aim_simulator deps (yaml-cpp 0.7.0, spdlog 1.11.0, argparse 2.9) need network once, or can be copied from `CENT/aim_simulator/ext` as I did.

### 7. Owner's additions: multi-kernel baseline and a scaled-down 5070

- **Multi-kernel:**
  - OpenCL: create all buffers once, then `clEnqueueNDRangeKernel` A, B, … on one in-order queue. Interleave `clEnqueueReadBuffer` of a count as the "host step" between launches. Buffers persist (the Q1 two-kernel run passes).
  - Native: `vx_enqueue_launch` several kernels from one `.vxbin` (`tests/regression/multikernel`).
  - Cost per launch: about 17.7k simulated cycles cold for an empty kernel, under 0.1 s wall. The PoCL compile is about 2 s per process.
  - Read the counters per launch (or diff cumulative ones) and add measured host gaps separately.
- **Knobs:**
  - Compute: `VX_CFG_NUM_CLUSTERS`, `NUM_CORES`, `SOCKET_SIZE`, `NUM_WARPS`, `NUM_THREADS`, `ISSUE_WIDTH`, `NUM_{ALU,FPU,LSU,SFU}_BLOCKS`.
  - L1: `DCACHE_SIZE`, `_NUM_WAYS`, `_NUM_BANKS`, `_MSHR_SIZE` (default 16), `DCACHE_WRITEBACK`; `LMEM_LOG_SIZE` for shared memory.
  - L2: `L2_ENABLE`, `L2_SIZE`, `L2_NUM_WAYS`, `L2_NUM_BANKS`, `L2_MSHR_SIZE`, `L2_LATENCY`. L3: `L3_ENABLE` (off).
  - DRAM: `PLATFORM_MEMORY_NUM_BANKS` (= channels), `PLATFORM_MEMORY_TYPE` (HBM2 / HBM3 128-bit, GDDR6 x16 = 2 B per transfer), `PLATFORM_MEMORY_DATA_RATE` (MT/s), `PLATFORM_MEMORY_LATENCY` (added core cycles), `PLATFORM_MEMORY_QUEUE_SIZE`. Patched in: `PLATFORM_MEMORY_SCHED_QUEUE_SIZE` and `PLATFORM_MEMORY_ROW_VISIT_BITS`. `PLATFORM_CLOCK_RATE` sets the core clock.
  - `PEAK_BW` is informational only (reported via device caps).
- **Real 5070 figures:**
  - Measured or recorded: 48 SMs, 672 GB/s peak (637 GB/s measured), 48 MB L2, L1 116 B/cycle per SM, L2 1,138 B/cycle chip-wide, DRAM latency 858 cycles at 2.866 GHz.
  - L1 per SM is **not** recorded in any report or profile. 128 KB unified L1/shared per SM (≤ 100 KB shared) is my inference for sm_120; confirm with `cudaDevAttrMaxSharedMemoryPerMultiprocessor`.
- **Scaling rule:** 1 Vortex core × issue 4 × 32 threads = 128 lanes per cycle = one 5070 SM. So f = cores / 48.
- **Proposed configs** (all with 32 threads, issue 4, 2512 MHz, L3 off, latency 518 to be re-derived, D$ MSHR ≥ 64 and L2 MSHR ≥ 64):

| Config | Share of chip | DRAM bandwidth | DRAM setup | L1 | L2 |
|---|---|---|---|---|---|
| S1 | 1 core, 32 warps (1/48) | 672/48 = **14 GB/s** = 5.6 B/cycle | 4 × GDDR6 x16 @ 1750 MT/s (more banks, fewer row conflicts than 1 ch @ 7000) | 128 KB | 48/48 = 1 MB, 1 bank (64 B/cycle; 23.7 B/cycle would be faithful, so it is 2.7× generous; there is no smaller knob) |
| S4 | 4 cores (1/12) | **56 GB/s** | 4 × @ 7000 (or 1 × @ 28000 = one real 28 Gbps x16 channel; risky for row activations) | 128 KB each | 4 MB, 2 banks (95 B/cycle needed) |
| S12 | 12 cores (1/4) | **168 GB/s** | 12 × @ 7000, or 16 × @ 5250 if a power of two is required | 128 KB each | 12 MB, 4–8 banks (284 B/cycle needed) |

  - Little's law check for S1: 5.6 B/cycle × ~750-cycle latency ≈ 4.2 KB in flight ≈ 65 lines. The default 16-entry D$ MSHR caps throughput at 1.4 B/cycle, which explains why the current rtx5070q Q6 run sits at 27 % of bandwidth.
  - Raise warps (to 64) only if `vx_membw` on that config stays under ~85 %. Calibrate each config with `vx_membw` first.
  - Expected wall time: S1 Q6 at SF1 ≈ 1 min (est. from 205k core-cycles/s); keep multi-kernel queries at SF0.1 on S4 for a few minutes per run.

### 8. Could not determine

- Whether simx resets memory counters per launch (the evidence above is suggestive only).
- The exact derivation of the 518-cycle latency.
- Whether L2 contents persist across launches (probably yes; not checked).
- Clean-build time of Vortex from scratch.
- AiM energy for the new ISRs.

### 9. What I would measure next

- `vx_membw` on S1/S4 built in a project-owned Vortex clone.
- One three-kernel chain (mask → compact → gather) in OpenCL with a count read-back.
- `MMAC`/`CMP` with a distinct compare timing, plus a refresh-on variant of the AiM simulator.

### 10. Files written (`/home/sai/cs254_project/pim_exploration/sim_scout/`)

- `aim_q6/q6_pim_scout.py` (copy using absolute read-only paths, `dont_write_bytecode`), `aim_q6/out/{q6_sf1,q6_sf10}.trace`, `results_fused_sf1_sf10.txt`, `ramulator_sf1_stdout.txt`. Command: `PYTHONDONTWRITEBYTECODE=1 ~/aimdb/.venv/bin/python -B q6_pim_scout.py --check-sf 0.01 --sf 1 10` (1.7 s).
- `aim_build/rebuild.sh`, `aim_build/head/` (patched latest upstream, built), `aim_build/rebuild_check.txt`.
- `aim_micro/isr_timing.py` → `aim_micro/isr_timing.txt`.
- `vortex_q6/vx_ro.sh`, `run_q6_ro.sh`, `run_app_ro.sh`, `cmdline_rtx5070q_{q1,q6}.txt`, `empty_kernel/kernel.cl`, `sf1_runs.out`, `run_*/` and `q1_*/`, `q6_*/`, `empty_*/` (`run.log`, `cmd.txt`, `ramulator.stats.log`), `cache/` (PoCL), `home/`.
