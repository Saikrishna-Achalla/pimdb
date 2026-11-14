# Vortex baseline: scaled-down RTX 5070, multi-kernel operators and chains

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## Vortex baseline (scaled-down RTX 5070 on simx): findings

All five steps are done, and 115 of 115 simulator runs match their references exactly (`results/verification.csv`). That includes Q6 and Q1 against DuckDB at SF 0.01 and 0.1, and Q6 at SF 1. Times below are *simulated* (simx cycles at 2512 MHz) unless they are marked *measured (real GPU)* or *modeled*. Paths are relative to `sim/vortex_baseline/` unless they start with `sim/`.

### 1. Main findings

1. **The build works and both configurations pass calibration on the first try with option C (narrow GDDR6 channels).** The build lives in `sim/vortex` (90a6262), uses PoCL inside `localhost/vortex-dev:22.04` with `~/tools`, `~/pim` and `~/aimdb` mounted read-only, and passes the OpenCL `vecadd`, `atomicreduce` and `histogram` tests.
   - Streaming read of 16 MB with `vx_membw`:
     - S1 reaches **13.80 GB/s, 98.6 % of 14.0 GB/s**.
     - S4 reaches **52.6 GB/s, 93.9 % of 56.0 GB/s**.
   - The rejected alternative, one channel at 7000 MT/s, reaches only 77.1 %.
   - Unloaded DRAM latency is **752.7 cycles = 299.6 ns**, against the real 5070's 858 cycles at 2.866 GHz (299 ns). Getting there needed `MEMORY_LATENCY` = 503; the owner's 518 gives 767 cycles.
   - Source: `results/calibration.csv`.
2. **Three simx artifacts would have distorted every kernel. Each is fixed by a patch and the effect is measured.**
   - **(a) Writes were free.** The DRAM model acknowledged writes into an unbounded queue, a launch ended before its writes reached DRAM, and the next launch's reset dropped them. The fix makes a launch end and the post-launch flush wait until DRAM has drained.
   - **(b) Every store fetched its line first.** The L2 read each written line from DRAM before writing it. The fix lets a written sector skip that read, as GPU L2s do. A cast to 8 B is 1.65× faster with it (943 → 572 µs at SF 0.1); Q6 is 7 % faster (`runs/patch_effect/`).
   - **(c) Thread stacks collided in the caches.** Per-thread stacks sit 8 KB apart, so the stacks of all 1024 threads fell into 8 L2 sets and 4 L1 sets. Any register spill then thrashed: one kernel wrote 20.5k DRAM lines for a 3.7k-line output. The fix hashes the cache set index.
3. **Per-launch counters, and caches between launches (verified, not assumed).**
   - Core `cycles`/`instrs` run cumulatively from device reset (code comment in `core.cpp`; the device-close report equals the sum of the launches).
   - Memory requests and L1/L2/L3 statistics reset at every launch. The device-close report also includes the post-launch flush.
   - Caches are emptied at every launch (each launch starts cold) after a write-back flush. Ramulator row state and statistics persist for the whole process.
   - The patch writes one exact RUN/FLUSH line per launch to `$VX_LAUNCH_LOG`. Row-hit statistics exist per process only.
4. **A launch has a large fixed cost.**
   - An empty kernel costs **14.8k cycles (5.9 µs)** with one work-group and **23.1k cycles (9.2 µs)** with all 1024 threads on S1; S4 is the same at 9.5 µs.
   - This includes the PoCL stack frames written back (~41 KB). A real GPU launch costs about 2–3 µs of GPU time.
   - At SF 0.01 this fixed cost dominates. From SF 0.1 to SF 1, time per row stays within 3 % (`results/scaling.csv`).
5. **Which operators are memory-bound on S1 at SF 0.1** (`results/operators.csv`):

   | Class | Operators | % of bandwidth |
   |---|---|---|
   | Memory-bound | `pred_i32`, 4 B and 8 B gathers, cast, multiply, SUM/MINMAX reductions, conjunctive filter | 83–94 % |
   | Latency-bound | `pred_i16`, range, mask AND | 53–62 % |
   | Latency-bound | compaction | 37–49 % |
   | Latency-bound | group-by | 56 % |
   | Latency-bound | membership probe | 22 % |

   - Compaction and group-by are bound by barriers (PoCL lowers one barrier to about 18 warp instructions, ~570 cycles) and by IPC.
   - **simx reaches only about 0.8 warp-instructions per cycle per core, against 4 for an SM.** So issue-heavy kernels are pessimistic here.
   - Real-GPU cross-check: cub select runs at 13–25 % of DRAM bandwidth on the real 5070 (note 02), so compaction is latency-bound there too.
6. **More warps or cores at the same DRAM (rule 3, `results/rule3.csv`).**

   | Kernel | 64 warps | 2 cores | Bound after |
   |---|---|---|---|
   | `pred_i16` | 1.12× (71 %) | 1.44× (91 %) | memory-bound |
   | group-by | 1.08× | 1.45× (83 %) | memory-bound |
   | compaction | 0.83× | 1.34× (65 %) | still latency-bound |
   | gathers, `pred_i32`, multiply | about 1.0× | about 1.0× | memory-bound already |

   - In every case, cores help much more than warps, which points at issue slots rather than requests in flight.
   - 16 warps hurts everything that is memory-bound (0.76–0.82×).
7. **The chains are correct and S4 scales as expected** (`results/chains_totals.csv`).

   | Chain | Config | SF | Launches | Simulated time | ns/row | % of bandwidth |
   |---|---|---|---|---|---|---|
   | Q6 | S1 | 0.1 | 13 | 1.198 ms | 1.99 | 65 % |
   | Q6 | S1 | 1 | 13 | 10.68 ms | 1.78 | 69 % |
   | Q6 | S4 | 1 | 13 | 2.68 ms | — | — |
   | Q1 | S1 | 0.01 | 42 | 2.63 ms | 43.7 | — |
   | Q1 | S1 | 0.1 | 42 | 21.25 ms | 35.4 | 78 % |
   | Q1 | S4 | 0.1 | 42 | 5.69 ms | — | — |

   - S4 over S1: Q6 SF 1 = **3.98×**, Q1 SF 0.1 = 3.73×. Memory-bound operators reach 3.6–3.9× at SF 0.1. At SF 0.01, launch cost holds S4 to 1.5–3×.
   - Q6 at SF 1: the filter takes 53 % of the time and compaction 31 %.
   - Q1 at SF 0.1: six casts take 16 %, four gathers 12 %, the multiplies 10 %, group-by map 10 % and aggregate 9 %, the five Sirius MIN/MAX pre-checks 8 %, and the string gather 26 %.
   - **The host term is reported separately and is modeled**: read-back gaps × 33.6 µs plus other gaps × 7.4 µs = Q6 141 µs, Q1 513 µs. Omitted bookkeeping launches are priced as empty kernels: Q6 3 per batch = 28 µs, Q1 17 per batch = 156 µs.
8. **This baseline is faster than real Sirius on Q6 and slower on Q1. Neither result should be read as a property of PIM.**
   - Q6, *modeled* projection S1 × 1/48: 222 µs at SF 1. The real Q6 SF 1 kernel time is 973 µs (*measured*, nsys), of which 799 µs is cuDF's AST `compute_column` kernel at about 11 % of DRAM. Our general filter kernel runs at 83 %.
   - Q1, *modeled* projection: 35.4 ns/row ÷ 48 ≈ 44 ms at SF 10, against about 27 ms real GPU busy time (*measured*, note 07). Likely causes are caches emptied at every launch and full-width intermediates.

### 2. Comparison with the owner's `rtx5070q` (`results/owner_comparison.csv`)

That configuration is 1 core, 16 warps × 8 threads, 3.5 GB/s, 16 MSHRs, 518 cycles of added latency; it is 1/192 of the GPU. Our S1 is 1/48.

| Run | Time | GB/s | % of configured | Projected to full GPU (modeled) |
|---|---|---|---|---|
| Owner stream | — | 1.79 | 51 % | — |
| Owner Q6 SF 0.1, one fused kernel, 9 B/row | 5.78 ms | — | 27 % | 30 µs |
| Owner Q6, latency 0 | 2.02 ms | — | 77 % | 10.5 µs |
| S1 stream | — | 13.80 | 98.6 % | — |
| S1 Q6 SF 0.1, 13 kernels | 1.198 ms | — | 65 % | 25 µs |

- **Why the owner's runs were latency-bound:** 16 MSHRs and 128 resident lanes cannot cover 750 cycles of latency (Little's law), which caps that machine at 51 % of its bandwidth.
- **Q6:** our 13-kernel Q6 moves 10.9 MB, against a fused floor of 6.0 MB at our widths. It is still faster than the owner's fused Q6 only because the owner's fused run sat at 27 % of its bandwidth.

### 3. Mapping and column widths

- `results/mapping_q6.csv` and `results/mapping_q1.csv` map each real kernel family to its simulated kernel, from the real traces.
- Q6 has 15.7 real launches per batch, simulated as 13. Cub's single-pass select becomes count, scan and scatter, which is three launches.
- Q1 has 72.8 real launches per batch, simulated as 42. Of the omitted ones, 25 per batch are bookkeeping and 6 are `batch_memcpy` (`batch_memcpy` is not modeled; its cost is unknown).
- Column widths are inferred from the traces:
  - `l_shipdate`: 2 B.
  - The four decimals: int32 (the gather and cast kernel names say int).
  - Flags: cuDF strings (int32 offsets plus chars).
  - The total is 14 B/row for Q6 and 28 B/row for Q1, matching the pinned footprints.

### 4. What does not work yet, or could not be determined

- Ramulator row-hit statistics are per process, not per launch. Up to about 26 writes per channel can remain in Ramulator's write buffer when a launch ends; they are issued during the next launch, not dropped.
- The launch fixed cost and the IPC ceiling of about 0.8 are PoCL/simx properties, not 5070 properties, so issue-bound kernels are pessimistic. A spill-free kernel ABI would be needed to remove them.
- Strings use a row-parallel character copy. The `batch_memcpy` path is omitted.
- The SF 1 Q6 result has 114,160 selected rows (DuckDB dbgen), against 114,271 in the owner's Parquet SF 1. The data sets differ.
- With caches emptied at every launch there is no L2 reuse between launches. This is consistent with the scaled 1 MB L2 but differs from a warm 48 MB L2.

### 5. Rebuild and rerun (CPU only)

```
sim/scripts/run_vortex_baseline.sh                  # setup + data + hosts + calibration + suite + results (~45 min, 28 parallel jobs)
STEPS=results sim/scripts/run_vortex_baseline.sh    # verify + mapping + CSVs from existing runs
sim/scripts/setup_vortex.sh [S1 S4 ...]             # init submodules, apply patches, build third_party and configs
sim/scripts/run_vortex.sh S1 <rundir> sim/vortex_baseline/tests/dbops/kernel.cl sim/vortex_baseline/bin/dbops \
   -d sim/vortex_baseline/data/sf0.1 -o <rundir> -c 1 -w 32 chain_q6     # one run; launch.log has per-launch RUN/FLUSH
```

### 6. Files written

- **Configurations:** `configs/S1.json` and `configs/S4.json`; every knob carries its value and derivation under `sources`. Variants in `configs/calib/`: `S1_1ch7000`, `S1_w16`, `S1_w64`, `S1_c2`, `S1_nowv`.
- **Tests:** `tests/vx_membw/` and `tests/vx_latency/` (copied), `tests/dbops/kernel.cl` (kernels for items 1–8) and `tests/dbops/host.cc` (driver).
- **Scripts:** `scripts/gen_data.py`, `build_hosts.sh`, `run_calibration.sh`, `calibration.py`, `run_suite.py`, `verify.py`, `chain_mapping.py`, `results.py`, `compare_owner.py`, `vxlog.py`, `mkvariant.py`, `show.sh`.
- **Results:** `results/calibration.csv`, `operators.csv`, `chains.csv` (per launch), `chains_totals.csv`, `scaling.csv`, `rule3.csv`, `mapping_q6.csv`, `mapping_q1.csv`, `owner_comparison.csv`, `verification.csv`.
- **Runs and logs:** `runs/` (logs per run), `logs/`, `.gitignore` (data, caches and output `.bin` files are regenerable).
- **sim/scripts:** `sim/scripts/vx.sh`, `setup_vortex.sh`, `run_vortex.sh`, `run_vortex_baseline.sh`, `mkpatches_vortex.sh`.
- **Patches in `sim/patches/vortex/`:**
  - `vortex_dram_knobs.patch` and `ramulator_queue_size.patch` are the owner's, copied unchanged.
  - **`vortex_cs254_model.patch`** is new. It adds the launch log and the DRAM drain (`processor.cpp`, `memory.*`, `dram_sim.*`), and the L2 write fix and hashed cache sets (`cache.cpp`) with their two knobs in `VX_config.toml`.
  - Checked: on a fresh 90a6262 checkout these patches reproduce the `sim/vortex` working tree file for file, and the ramulator submodule's diff equals `ramulator_queue_size.patch`.
  - The submodule also has untracked `profiles/*.json` symlinks and `build64-*` directories.
