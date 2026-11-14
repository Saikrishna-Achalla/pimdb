# Group-by aggregation microbenchmark: current pattern vs fixed unroll

Models the inner loop of cuDF's `single_pass_shmem_aggs_kernel` (TPC-H Q1 SF1 on Sirius, RTX 5070).
Input: the 3,153,518 rows that pass Q1's filter, with their **real** group ids in table order
(`q1_groups.csv`, from `make_q1_groups.sh`). Launch: 240 CTAs x 128 threads, as ncu recorded.

```bash
./build.sh                                   # pixi CUDA 13.5 (system CUDA 12.9 fails on this glibc)
./make_q1_groups.sh                          # writes q1_groups.csv
./groupby_unroll_bench LLLLL 3153518 50 q1_groups.csv   # L=int64 SUM, I=int32 SUM, C=COUNT
```

Variants (all use the same generic `ATOM.E.ADD.64.STRONG.SYS` into shared memory that cuDF's SASS uses):

| Variant | What it is |
|---|---|
| `baseline (simple sw)` | 1 row per iteration; runtime column loop; load -> atomic per row x column |
| `unroll U=k` | U rows per batch (warp-striped); runtime column loop; per column: U loads, one wait, U atomics |
| `unroll U=8 +ATOMS` | address space visible -> compiler emits `ATOMS.CAST.SPIN.64` (CAS loop): no native 64-bit shared add |
| `cudf-disp *` | 64-B column descriptor + type_id binary-search switch (cuDF type_dispatcher shape) |

## Results (CUDA events, median of 50, L2 flushed each rep; `results.txt`)

5 int64 SUM columns (matches the real kernel: ~5 atomics/row, 45 B/row DRAM):

| Variant | regs | us | GB/s | vs baseline |
|---|---:|---:|---:|---:|
| baseline | 38 | 349.7 | 397 | 1.00x |
| unroll U=1 | 34 | ~352 | 394 | 0.99x |
| unroll U=4 / U=8 | 38 / 56 | ~254 | 547 | 1.37x |
| unroll U=16 | 120 | 268 | 518 | 1.30x |
| cudf-disp baseline | 26 | 335.4 | 414 | 1.00x |
| cudf-disp U=4 | 40 | 241.4 | 575 | **1.45x** (86% of 672 GB/s) |
| unroll U=8 +ATOMS | 40 | 739 | 188 | 0.47x |

Floor for 139 MB at 672 GB/s: 207 us. LLLL: 1.39-1.46x; IIL (narrow cols): 1.68-1.83x.

ncu (`ncu/`, locked clocks): baseline 409.6 GB/s -> U=8 610.6 GB/s DRAM, both ~87% long_scoreboard.

## Caveat: the model is ~5x faster than the real kernel

Real cuDF launches 104+111 under ncu: 1,594 us, 5.09e7 warp-instructions, 89 GB/s.
This baseline under ncu: 291 us, 9.6e6 warp-instructions. The real kernel runs ~500 warp-instructions
per row-warp (~70 per column) vs ~100 here, plus 19% barrier stalls and 72 regs. Adding a cuDF-shaped
type switch did not reproduce that cost, so the remaining overhead is something in cuDF's per-element
path this model doesn't contain (likely validity/null and aggregation-kind handling). The 1.4x here is
the gain on the load->atomic core; the real kernel's per-row x column overhead is the bigger lever and
needs cuDF's source to model.
