# Per-bank PU in SystemVerilog

Synthesizable RTL of the processing unit (filter unit + join unit) drawn in `tpch/results/plots/pu_figure.excalidraw`,
following `rtl/PLAN.md` (sections 1-4; revised in section 9 after the plan review `PLAN_REVIEW.md` and in section 10
after the implementation review `IMPL_REVIEW.md`).

## Files

| Path | What |
|---|---|
| `src/pu_pkg.sv` | command opcodes, mask-op codes, config register type |
| `src/pu_cmp_seg.sv` | segmented 256-bit comparator: byte tree 8 -> 16 -> 32 -> 64 b, signed correction at the lane root |
| `src/pu_cfg.sv` | bound register (lo, hi, 64 b each, host-repeated) + 6-bit config, loaded by PWGB |
| `src/pu_filter.sv` | comparators A (x >= lo) and B (x <= hi), AND, invert |
| `src/pu_join.sv` | V register (from X or the Global Buffer), comparator C + 3-bit operator, set-select, M1, mask combine |
| `src/pu_slot.sv` | slot placement + mask logic (SET / AND / OR on the window) |
| `src/pu.sv` | top, one per bank: X register (`HAS_XREG`), result mux, M, read-path mux for PRD |
| `src/pu_decoder.sv` | one per channel: opcode decode (9-15 -> NOP), one-slot control delay, PRD bank one-hot, PWGB word-0 strobe |
| `ref/pu_ref.py` | golden model (word level) |
| `ref/pack.py` | storage format: records -> 32 B words, bound / config word for PWGB |
| `tb/gen.py`, `tb/tb_pu.sv`, `tb/tb_chan.sv`, `tb/run_rtl.sh` | vectors (random + real-data replay), PU and channel testbenches, RTL runs (Icarus + Verilator) |
| `formal/prove_{cmp,slot,filter}.ys` | proofs: comparator, slot placement + mask op, filter result = behavioural references, all inputs |
| `syn/syn.sh`, `syn/gls.sh` | Yosys + ABC synthesis to Nangate45; gate-level runs of the netlists |

Parameters of `pu`: `HAS_JOIN`, `HAS_SETSEL`, `HAS_XREG`. Tools: OSS CAD Suite 2026-11-03 (Yosys 0.70+309 with the
slang front end, Verilator 5.055, Icarus 14), Nangate45 typical library from OpenROAD-flow-scripts.

## Verification (all pass, 2026-11-23; after the implementation review `IMPL_REVIEW.md`)

| Check | Result |
|---|---|
| Lint (`verilator --lint-only -Wall`) | clean except unused-signal warnings from parameterization |
| Formal proofs (Yosys miter + SAT, all inputs): comparator = per-lane compare (4 widths, signed and unsigned, lt and eq); slot placement + mask op = reference; whole filter result (range, sign, invert) = reference | all three proved; planted bugs (wrong sign bit at 16 b, wrong 16-bit window) make them fail |
| Golden model vs the project's functional model (`tpch/lookahead.bitmap`, per record) on real SF10 data | equal on every PRD word: Q6 (64), Q12 look-ahead (192), Q19 look-ahead (256), Q12 `commit < receipt` via PLD ROW + PCC (64) |
| RTL vs golden model, Icarus (4-state) and Verilator, state (M, M1, V) after every command + every PRD | **32 of 32 runs, 0 errors**: about 100 K random commands per configuration (prefix-sharing operands, invert, lo > hi, 8-64 b lanes, non-repeated bounds, set-word PWGBs, mask op 11, PMC no-write codes, join commands sent to a PU without them), the four replays, `HAS_XREG` 0 / 1, all three configurations |
| Channel test: `pu_decoder` + 16 PUs, PRD rotating over the banks, other banks checked for a transparent read path | 0 errors; a PU that ignores its bank select is caught |
| Gate level: synthesized Nangate45 netlists, cells expanded from their Liberty functions, PRD words + read path | **11 of 11 runs, 0 errors** (random about 100 K commands per configuration + replays, all three configurations, `HAS_XREG` 0 / 1) |

Run: `tb/run_rtl.sh` (about 35 min), `cd formal && for p in cmp slot filter; do yosys -m slang prove_$p.ys; done`,
`syn/syn.sh`, `syn/gls.sh` (`export PATH=~/tools/oss-cad-suite/bin:$PATH`). The scripts rebuild from scratch and exit
non-zero unless every run passes.

## Synthesis (Yosys + ABC with buffering and sizing, Nangate45 typical, flattened)

Cell area only (no routing, no utilization); gate-equivalents = area / 0.798 um^2 (NAND2_X1). No timing constraint is
applied yet (ABC's `-D` does not change the gates). Depth = cells on the longest flop-to-flop path, buffers included.

| Configuration | X register | Cell area (um^2) | Gate-eq | Flip-flops | Buffers | Depth |
|---|---|---|---|---|---|---|
| Filter only | no | 5,759 | 7.2 K | 390 | 233 | 26 |
| Filter only | yes | 7,525 | 9.4 K | 646 | 295 | 25 |
| Filter + join core | no | 13,879 | 17.4 K | 902 | 832 | 31 |
| Filter + join core | yes | 15,791 | 19.8 K | 1,158 | 943 | 29 |
| Filter + join + set-select | no | 29,163 | 36.5 K | 902 | 3,218 | 29 |
| Filter + join + set-select | yes | 30,995 | 38.8 K | 1,158 | 3,280 | 30 |
| Decoder (per channel, not per bank) | – | 223 | 0.28 K | – | – | – |

Against the hand estimates of notes/22 8.3 (X register left out on both sides): the join core adds 10.2 K gate-eq
(estimate 9.5-11 K); set-select adds 19.2 K (estimate about 20 K). The filter unit is 7.2 K gate-eq (estimate: 48 B of
flops + 5-7 K gates); it includes the 256-bit read-path mux for PRD, which the estimate did not have.

Per block (hierarchical run, full configuration, no X register, um^2): comparators A, B, C 1,070 / 1,070 / 1,140;
slot placement + mask logic 1,180; bound + config 870; join unit 21,700 (V, M1, set-select, mask combine, comparator
C); filter AND / invert 150. Reports in `syn/out/` (`summary.txt`, `*.stat`, `*.ltp`).

## Not done yet (next phase, PLAN.md section 9)

Timing in FO4 and a scaled-period sweep, place and route with 3 routing layers, conversion to a DRAM process through
gate-equivalents (low / central / high), power and energy per command from netlist activity, die share including the
Global Buffer per configuration. The numbers above are cell area in a logic process and are not die overheads.
