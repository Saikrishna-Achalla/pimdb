# Simulation phase — design brief (shared by the Vortex-baseline and AiM-PIM builders)

Read first: `pim_exploration/BRIEF_COMMON.md` (project question and rules) and the filed findings in
`pim_exploration/notes/` — at least `08_simulator_scout.md` (how the simulators work here, exact commands, the
calibration problem), `05_launch_anatomy.md`, `07_sf10_scaling.md`, `04_operator_chains.md`, `02_kernel_fit.md`.

## Goal

PIM does not exist on the real GPU, so we model it:

- **Baseline** = database operators run as **a sequence of general operator kernels** (the way Sirius/libcudf
  launches them: one kernel per sub-operator and per column, with a host step between launches) on the **Vortex**
  GPU simulator (simx), configured as a **scaled-down RTX 5070**.
- **PIM** = the same operators executed by **SK hynix AiM-style bank-level processing units** extended with circuits
  for database operations, timed with the Ramulator2-based **aim_simulator**.
- **Result** = per operator and per operator chain: baseline time, PIM time, speedup, with every assumption stated,
  on the **same memory** (same external bandwidth and capacity on both sides).

The real-GPU profiling (ncu/nsys, already on disk — **do not run ncu or use the GPU**) is the workload
characterization: it says which kernels, how many launches, how many bytes. The simulators give the baseline/PIM
timing of those operators.

## Owner's rules for the Vortex baseline (binding)

1. **Multi-kernel, like Sirius.** No whole-query fused kernel. The earlier `tpch_q1`/`tpch_q6` Vortex tests are
   fused and are only smoke tests.
2. **Scaled-down RTX 5070.** Start with **1 core**; scale memory bandwidth by the same factor as compute; scale L1
   and L2; **L3 disabled**. A large configuration takes too long to simulate.
3. **Threads per warp is always 32.** If a kernel is not memory-bound only because too few requests are in flight,
   increase warps and cores — never threads per warp.
4. Project rule: operators stay general-purpose (no query-specific fusion); chaining general operators is fine.

Scaling convention: one Vortex core (issue width 4 × 32 threads = 128 lanes/cycle) stands for one 5070 SM, so
`f = cores / 48`. Real machine: 48 SMs, 672 GB/s peak (637 GB/s measured stream), 48 MB L2, 12 GB GDDR7, DRAM
latency ≈ 858 cycles at 2.866 GHz (≈ 300 ns). Starting point `S1`: 1 core, 32 warps × 32 threads, DRAM
672/48 = 14 GB/s, L2 = 48 MB/48 = 1 MB, L1 per core at the real per-SM size (128 KB is an inference — say so),
L3 off, D-cache and L2 MSHRs large enough not to cap the request rate (see the Little's-law note in note 08 §7).
`S4` (4 cores, 56 GB/s, 4 MB L2) is the cross-check that results scale. **Calibrate every configuration with a pure
streaming read before trusting any kernel result: the stream must reach ≥ 85 % of the configured bandwidth** (real
GPUs reach 90–95 %); follow option (C) of note 08 §4 (narrow GDDR6 channels) first, model fixes only if needed, and
report raw numbers plus the stream efficiency of each configuration.

## Same-memory normalization for the speedup

GDDR6-AiM: one channel = 16 banks, 32 GB/s external, 512 GB/s internal (16×). A GPU memory system with external
bandwidth B therefore corresponds to B/32 AiM channels. Scaled configuration `S(f)` has B = 672·f GB/s, i.e.
21·f channels (S1: 0.44 channel ≈ 7 banks). The AiM simulator runs whole channels, so simulate 1 channel and
normalize linearly (bank-parallel work on evenly spread data), and state this as a modeled step. Report speedups
(a) for the scaled pair and (b) projected to the full 5070 (48 cores vs 21 channels), saying what assumption each
needs. The test GPU has GDDR7 and AiM is GDDR6 — a projection, say so.

## Workloads (both sides implement the same ones, on the same data)

Data: TPC-H `lineitem` generated with DuckDB's `tpch` extension (`/home/sai/aimdb/.venv/bin/python` has duckdb +
numpy; use it read-only) at SF 0.01 and 0.1 (SF 1 only if a run stays under ~10 minutes). Use the physical column
widths cuDF used in the real runs (check `tpch_q1_analysis/analysis/results/q6/physical_floor.md` and `q1/`), not
hand-narrowed types. Results must equal DuckDB exactly (integers/fixed-point) on both sides.

A. **Operator micro-suite** — each a general operator over N rows, timed alone:
   1. predicate: column ⟨op⟩ constant → boolean mask (1 byte/row as cuDF does; note the alternative bitmask)
   2. mask AND / range predicate (two compares)
   3. compaction: mask → count (host reads it back) → selected row indices (scan + scatter, or cub-style select)
   4. gather: indices → one fixed-width column (4 B and 8 B)
   5. element-wise binary op (multiply two columns → 8 B column) and cast/widen (4 B → 8 B)
   6. reduce: sum of one column
   7. small-group aggregation: sum/count by a low-cardinality key (≤ 8 groups, Q1-style)
   8. (stretch) membership probe of a column against a small key set (dynamic-filter style)
B. **Chain Q6** — scan → filter → aggregate as Sirius executes it: derive the per-batch launch sequence from
   `results/q6/warm_kernel_list.json` and `pim_exploration/launch_anatomy/launch_attribution.json` (≈ 15 launches per
   batch: predicate evaluation, compaction with a count read-back, one gather per needed column, the multiply, the
   reduce) and mirror it at sub-operator level. Give the mapping table real kernel → simulated kernel and say what
   was left out (bookkeeping launches on tiny inputs).
C. **Chain Q1** — filter → expressions → small-group aggregation (→ sort of the ≤ 6 result rows on the host/GPU
   side): same approach from `results/q1/q1_warm_kernel_list.json` (Q1 at SF10).

The host step between launches is not simulated by either simulator. Report simulator time only, and separately
add the measured host cost as an explicit, labelled term (real-GPU medians: 7.4 µs for a gap with only an
allocation, 33.6 µs for a gap with a size read-back; note 04) — never silently.

## Ground rules

- `/home/sai/pim`, `/home/sai/aimdb`, `/home/sai/tools` are the owner's other work: **read-only**. Copy what you need
  (kernels such as `vx_membw`, patches, profiles, the container wrapper) into `sim/`; mount those trees read-only in
  the container; set `GIT_OPTIONAL_LOCKS=0` when running git there.
- Project-owned copies: `sim/vortex` (submodule, vortexgpgpu/vortex @ 90a6262) and `sim/aim_simulator` (submodule,
  arkhadem/aim_simulator @ 0f28a07). You may patch and build inside them; keep every source change as a patch file
  under `sim/patches/{vortex,aim}/` with a `sim/scripts/setup_*.sh` that applies it to a fresh checkout, and leave
  the submodule's own tracked files restorable (`git -C … diff` must equal the patches). Build outputs stay
  untracked.
- Each builder writes only in its own directory plus its submodule and its patch directory:
  Vortex builder → `sim/vortex_baseline/`, `sim/vortex/`, `sim/patches/vortex/`, `sim/scripts/*vortex*`;
  AiM builder → `sim/aim_pim/`, `sim/aim_simulator/`, `sim/patches/aim/`, `sim/scripts/*aim*`.
  Do not run `git add/commit/submodule` in the project repository; the orchestrator does that.
- No GPU, no sudo, no ncu. Long runs in the background; keep individual simulations to minutes.
- Every reported number must be regenerable by a script you leave, from files you leave (CSV/JSON). Label each
  number *simulated*, *measured (real GPU, file)*, or *modeled (assumption)*. Report results that go against PIM as
  plainly as those for it.
- Do not write report documents; return findings as your final message (≤ ~200 lines) in the format of
  `BRIEF_COMMON.md`, including the exact commands to rebuild and rerun.
