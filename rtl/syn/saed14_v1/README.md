# PU synthesis on SAED14 — v1 results (area, timing, power)

Synopsys flow (Design Compiler → VCS gate-level simulation → PrimeTime / PrimePower) of the per-bank processing unit
`pu` (6 parameter variants) and the per-channel `pu_decoder`, on the SAED14 14 nm educational library.
It complements the Yosys/ABC Nangate45 numbers in `../out/` (`../syn.sh`).

## 1. Target RTL version

| Item | Value |
|---|---|
| Repository | `Saikrishna-Achalla/pimdb`, branch `main` |
| Repo HEAD when synthesized | `0b7443a` (Merge pull request #1 from Saikrishna-Achalla/pu-rtl) |
| Commit that last changed `rtl/` | `8f481b2722e18f3b5c6841893b6b8f63f5cd0ed5` — "Add synthesizable SystemVerilog of the per-bank PU" (2026-11-23) |
| Files synthesized | `rtl/src/pu_pkg.sv pu_cmp_seg.sv pu_cfg.sv pu_filter.sv pu_slot.sv pu_join.sv pu.sv` (PU), `rtl/src/pu_pkg.sv pu_decoder.sv` (decoder) |
| Check | `rtl/src`, `rtl/tb`, `rtl/ref` in the work copy were diffed against `8f481b2`: identical |

The RTL was not modified. To reproduce on the same RTL: `git checkout 8f481b2 -- rtl/src`.

## 2. Configurations

| Name | `HAS_JOIN` | `HAS_SETSEL` | `HAS_XREG` | Meaning |
|---|---|---|---|---|
| filter_x0 | 0 | 0 | 0 | Filter only, X operand not registered |
| filter_x1 | 0 | 0 | 1 | Filter only, 256-bit X register |
| join_x0 | 1 | 0 | 0 | Filter + join core |
| join_x1 | 1 | 0 | 1 | Filter + join core, X register |
| all_x0 | 1 | 1 | 0 | Filter + join + set-select |
| all_x1 | 1 | 1 | 1 | Filter + join + set-select, X register |
| decoder | — | — | — | `pu_decoder`, one per channel (drives 16 PUs) |

## 3. Setup

| Item | Value |
|---|---|
| Library | SAED14 RVT, `saed14rvt_base_tt0p8v25c.db` + `saed14rvt_cg_tt0p8v25c.db` (EDK 08/2025), NLDM, **TT 0.8 V 25 °C only** |
| Clock | **2.284 ns** (438 MHz) = one 4-tCK command slot |
| Synthesis | DC Y-2026.03-SP2, `compile_ultra -no_autoungroup`; **flat** run (`ungroup -all -flatten`) for all headline numbers, separate **hierarchical** run for the per-block breakdown only |
| Sign-off timing / power | PrimeTime / PrimePower Y-2026.03-SP3, time-based power from a gate-level VCD |
| Gate simulation | VCS X-2025.06-SP1, zero delay (`+nospecify +notimingcheck`), SAED14 cell models generated from the `.lib` |
| Constraints | zero wire load (DC and PT), `high_fanout_net_threshold 0`, max_transition 0.2 ns, max_capacitance 0.05 pF, max_fanout 24, `SAEDRVT14_BUF_1` driving every input, 2.384 fF (4 × BUF_1 input cap) on every output, zero input/output delay, ideal clock, no clock uncertainty |
| Not used | no retiming, no clock gating, no DFT, no P&R |
| Gate equivalent | GE = area / `SAEDRVT14_ND2_1` (0.3108 µm²; SAED14's 2-input NAND is called ND2) |

## 4. Results (flat netlists)

| Config | Area µm² | Comb µm² | Seq µm² | GE | Flops | Cells | Setup WNS ns | Hold WNS ps | Power mW | Energy pJ/slot | Clock-net % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| filter_x0 | 1264.5 | 900.9 | 363.6 | 4 069 | 390 | 3 418 | +1.802 | +12.6 | 0.501 | 1.144 | 65.4 |
| filter_x1 | 1567.4 | 965.0 | 602.3 | 5 043 | 646 | 3 673 | +1.803 | +12.6 | 0.790 | 1.803 | 68.7 |
| join_x0 | 3124.9 | 2285.3 | 839.6 | 10 054 | 902 | 8 827 | +1.769 | +9.6 | 1.140 | 2.604 | 66.3 |
| join_x1 | 3424.2 | 2345.8 | 1078.4 | 11 017 | 1158 | 9 060 | +1.782 | +9.6 | 1.390 | 3.174 | 69.9 |
| all_x0 | 5971.0 | 5130.7 | 840.3 | 19 212 | 902 | 15 445 | +1.695 | +9.6 | 1.817 | 4.149 | 41.7 |
| all_x1 | 6279.1 | 5199.6 | 1079.5 | 20 203 | 1158 | 15 691 | +1.696 | +9.8 | 1.790 | 4.087 | 54.3 |
| decoder | 46.9 | 10.6 | 36.4 | 151 | 36 | 77 | +2.202 | −3.3 (see §5) | — | — | — |

Energy per slot = average power × 2.284 ns.

### 4.1 Comparison with the Nangate45 Yosys/ABC numbers (`../out/summary.txt`)

| Config | SAED14 µm² | SAED14 GE | N45 µm² | N45 GE | GE ratio SAED14/N45 |
|---|---:|---:|---:|---:|---:|
| filter_x0 | 1264.5 | 4 069 | 5759 | 7 217 | 0.56 |
| filter_x1 | 1567.4 | 5 043 | 7525 | 9 429 | 0.53 |
| join_x0 | 3124.9 | 10 054 | 13879 | 17 392 | 0.58 |
| join_x1 | 3424.2 | 11 017 | 15791 | 19 789 | 0.56 |
| all_x0 | 5971.0 | 19 212 | 29163 | 36 545 | 0.53 |
| all_x1 | 6279.1 | 20 203 | 30995 | 38 840 | 0.52 |
| decoder | 46.9 | 151 | 223 | 279 | 0.54 |

Flop counts are identical to the Yosys runs (390 / 646 / 902 / 1158 / 36). The GE gap is expected rather than a
mismatch: different libraries (SAED14 has many complex/compound cells and a relatively large ND2_1), different mappers
(DC compile_ultra vs ABC), and different timing pressure. Use the ratios *between configurations* within one flow, not GE
across flows.

### 4.2 Block area (hierarchical run, µm²)

| Block | filter_x0 | filter_x1 | join_x0 | join_x1 | all_x0 | all_x1 |
|---|---:|---:|---:|---:|---:|---:|
| Top total (hier run) | 1431.8 | 1787.1 | 3348.2 | 3703.4 | 6324.2 | 6680.0 |
| `u_filter` (comparators A + B) | 519.6 (243.6 + 237.6) | 519.6 | 519.5 | 519.5 | 517.7 (242.7 + 236.7) | 517.7 |
| `u_cfg` (bound + config) | 185.8 | 185.8 | 185.8 | 185.8 | 185.8 | 185.8 |
| `u_slot` (slot + mask) | 232.6 | 232.6 | 232.6 | 232.6 | 232.6 | 232.6 |
| `g_join.u_join` (whole join unit) | — | — | 1820.8 | 1820.8 | 4788.8 | 4789.3 |
| … of which comparator `u_c` | — | — | 317.5 | 317.5 | 317.8 | 318.2 |
| Top-level glue + X/M registers | rest | rest | rest | rest | rest | rest |

The hierarchical runs are 6–13 % larger than the flat ones, because they cannot optimize across module boundaries. Use
them for block *proportions* only. Set-select adds about 2970 µm² to the join unit (1821 → 4789), which is about half of
the full PU.

### 4.3 Power breakdown (PrimePower groups, mW)

| Config | Clock network | Register | Combinational | Leakage (total) | Total |
|---|---:|---:|---:|---:|---:|
| filter_x0 | 0.328 (65.4 %) | 0.009 | 0.165 | 0.0004 | 0.501 |
| filter_x1 | 0.543 (68.7 %) | 0.090 | 0.157 | 0.0005 | 0.790 |
| join_x0 | 0.756 (66.3 %) | 0.034 | 0.350 | 0.0009 | 1.140 |
| join_x1 | 0.971 (69.9 %) | 0.120 | 0.298 | 0.0010 | 1.390 |
| all_x0 | 0.757 (41.7 %) | 0.059 | 1.000 | 0.0017 | 1.817 |
| all_x1 | 0.972 (54.3 %) | 0.167 | 0.650 | 0.0017 | 1.790 |

"Clock network" is the clock pins of the flops. With an ideal clock there is no clock tree, so a real tree adds to this.
The RTL has no clock gating: every enabled register is a flop plus a feedback mux, so all flops are clocked every cycle.
This is why the clock is 42–70 % of the total and scales with flop count.
all_x1 is slightly *below* all_x0: with `HAS_XREG=1`, X is registered and so changes once per cycle, cleanly. With
`HAS_XREG=0` the random X input feeds the large set-select logic directly (combinational 1.000 vs 0.650 mW).

### 4.4 Energy per command type (pJ, `reports/<cfg>/per_op_energy.txt`)

| Command | filter_x0 | filter_x1 | join_x0 | join_x1 | all_x0 | all_x1 |
|---|---:|---:|---:|---:|---:|---:|
| NOP | 1.054 | 1.710 | 2.315 | 2.884 | 3.748 | 3.702 |
| PWGB | 1.600 | 2.177 | 2.822 | 3.323 | 4.232 | 4.126 |
| PCMP | 1.112 | 1.791 | 2.389 | 3.001 | 3.791 | 3.783 |
| PLD_ROW | 1.073 | 1.732 | 3.069 | 3.603 | 5.879 | 5.390 |
| PLD_GB | 1.057 | 1.703 | 2.874 | 3.402 | 5.686 | 5.225 |
| PCC | 1.061 | 1.744 | 2.431 | 3.044 | 3.802 | 3.833 |
| PSEL | 1.066 | 1.753 | 2.327 | 2.948 | 3.865 | 3.903 |
| PMC | 1.057 | 1.696 | 3.077 | 3.488 | 4.516 | 4.087 |
| PRD | 1.184 | 1.825 | 2.375 | 3.096 | 3.228 | 3.907 |
| **Average / slot** | **1.144** | **1.803** | **2.604** | **3.174** | **4.149** | **4.087** |

Method: PrimePower writes the power of every clock cycle. Cycle *t* is assigned to the command in pipeline stage 2
during that cycle, C[t−1]. The NOP row is effectively the floor, which here is mostly clock power plus random-input
toggling (see §6).

## 5. Timing

- **Setup met in every configuration at 2.284 ns**, with 0 violations in both DC and PT. The worst slack is +1.695 ns
  (all_x0), so the longest register-to-register or input-to-register path is about 0.59 ns. Example worst path
  (all_x0): `op[3]` → … → `m_q_reg[252]` (mask register through the set-select logic), arrival 0.58 ns.
  DC and PT slacks agree.
- **Hold met in every PU configuration**, by at least +9.6 ps.
- **Decoder hold −3.3 ps** on 15 paths from the `cmd_*` input ports straight to the output-stage flops (e.g. `cmd_addr[0]` → `addr_reg[0]`). This is a boundary artifact of the
  constraints (zero input delay plus an ideal clock, with the input driven by a BUF_1). In the chip these inputs come
  from flops clocked by the same clock tree, so this is not a design problem. It has not been re-checked with
  realistic input delays.
- **Other constraint "violations"** (`reports/<cfg>/constraint_summary.txt`): about 13 k `min_capacitance` entries on
  input nets. They are SAED14's tiny min-cap limit with "increase significant digits" rounding at 0.00 pF, not a real
  shortfall. There is also one `max_leakage_power`, which is compile_ultra's own optimization goal. There are no
  max_transition, max_capacitance or max_fanout violations.

**Caveats on timing:** TT corner only, zero wire load, ideal clock and no uncertainty, so these slacks are optimistic.
With about 74 % of the period free, the design is very likely to close at the SAED14 slow corners and after P&R, but
neither has been run yet. The 1.0 ns target mentioned in `rtl/PLAN.md` was not run in v1 (worst path ≈ 0.59 ns at TT
suggests it would pass at TT).

## 6. Power methodology and caveats

- **Stimulus:** `rtl/tb/gen.py random` (the partner's random mode), with the vector set chosen to match the variant:
  - `rand_filter` has 20 009 commands, for filter_*;
  - `rand_nosel` has 22 055 commands, for join_*;
  - `rand_all` has 22 055 commands, for all_*.

  The first 100 commands are excluded as warm-up, and power is measured over about 20–22 k cycles. Running `gen.py`
  in random mode needs a `numpy` stub (`scripts/npstub/`), because `pack.py` imports numpy but random mode never uses
  it. Real TPC-H replays need the `tpch/` SF10 data, which is not in the repo, so none were run.
- **Gate simulation checks** (`reports/<cfg>/gatesim_result.txt`): every PRD output word is compared with the golden
  model, and the read path must be transparent on every other cycle. All 6 configurations had **0 errors** (2 500–2 762
  PRDs each).
- **Annotation:** the VCD annotated 100 % of nets and cells (`vcd_annotation.txt`). The mean of the per-cycle power
  equals PrimePower's average.
- **Optimistic and pessimistic factors:**
  - **(a) Random stimulus.** X, gb and arr_data change every cycle even on NOPs. This raises the floor and compresses
    the spread between commands. Real query traffic has much lower activity on these buses.
  - **(b) No clock gating.** `compile_ultra -gate_clock` with the SAED14 `cg` ICG cells would cut the 42–70 % clock
    share substantially.
  - **(c) Ideal clock and no wires.** Both understate power (no clock tree, no wire capacitance).
  - **(d) TT corner only.**

  Treat these as v1 relative numbers between configurations, not final absolute energies.

## 7. Contents of this directory

```
README.md                this file
summary_table.txt        one-table summary (also lists the N45 numbers)
scripts/
  run_dc.sh              13 DC jobs in parallel: 6 configs x {flat, hier} + decoder flat.  Usage: run_dc.sh [period_ns] [tag]
  dc_pu.tcl              DC script (env TOP, PARAMS, MODE, PERIOD_NS, SRC, DB)
  run_pwr.sh             per flat netlist: VCS gate sim -> VCD -> PT/PrimePower (decoder: timing only).  Usage: run_pwr.sh [tag] [period_ns]
  pt_pu.tcl              PT timing + PrimePower time-based power (env TOP, NET, SDC, DB, VCD, PERIOD_NS)
  per_op.py              per-command energy from PrimePower's per-cycle waveform: per_op.py <pwr_wave.out> <vec dir> <period_ns>
  npstub/numpy.py        stub so gen.py random mode runs without numpy
tb/tb_pu_pwr.sv          gate-level power testbench (derived from rtl/tb/tb_pu.sv; clock PER_NS, VCD window, PRD checks)
reports/<cfg>/           cfg = filter_x0 filter_x1 join_x0 join_x1 all_x0 all_x1 decoder
  dc_area.rpt dc_area_hier.rpt dc_qor.rpt dc_timing_max.rpt dc_timing_min.rpt dc_reference.rpt dc_power_dc.rpt
  dc_check_design.rpt dc_markers.txt               flat DC run
  dc_hier_run_area_hier.rpt dc_hier_run_qor.rpt    hierarchical DC run (block breakdown)
  pt_markers.txt                                   PT WNS / violation counts / power (W: total internal switching leakage)
  power.rpt power_group.rpt power_cells.rpt        PrimePower (PU configs)
  per_op_energy.txt vcd_annotation.txt gatesim_result.txt constraint_summary.txt
```

Netlists, SDC, VCDs, DC databases and the generated cell models are not committed. The cell models are derived from
the licensed SAED14 `.lib`, and the rest is large. All of them are kept in the work directory listed below.
PT `report_timing` printed only violating paths, so there are none for the PUs. The DC timing reports hold the worst
paths, and PT slack is in `pt_markers.txt`.

## 8. How to rerun

Work directory layout (`W`, default `/edata1/yanggon/dc_work/pimdb_pu`):

- `src/ tb/ ref/`: copies of `rtl/src rtl/tb rtl/ref` at `8f481b2`;
- `tb/tb_pu_pwr.sv`;
- `tb/vec/{rand_filter,rand_nosel,rand_all}`;
- `cells/saed14_cells.v`;
- `scripts/`.

```bash
# vectors (in W/tb):  PYTHONPATH=../scripts/npstub python3 gen.py random <name> [n] [join] [setsel]
# cell models:        lib2v.py (from the VLA_LPDDR_AiM_RTL repo) on saed14rvt_base_tt0p8v25c.lib -> cells/saed14_cells.v
W=/path/to/work scripts/run_dc.sh 2.284 p2284      # DC  -> W/dc/p2284/<cfg>.<flat|hier>/
W=/path/to/work scripts/run_pwr.sh p2284 2.284     # sim + PT -> W/pwr/p2284/<cfg>/
python3 scripts/per_op.py W/pwr/p2284/all_x1/pwr_wave.out W/tb/vec/rand_all 2.284
```

Tools are loaded with environment modules: `synopsys/syn/Y-2026.03-SP2`, `synopsys/prime/Y-2026.03-SP3`, and
`synopsys/vcs/X-2025.06-SP1`.

## 9. Possible next steps (not in v1)

1. Clock gating (`compile_ultra -gate_clock`, SAED14 `cg` ICGs). This is the largest expected power reduction.
2. A 1.0 ns target run.
3. PT timing at the SAED14 slow corners (e.g. ss0p72v125c, ss0p72vm40c).
4. P&R (ICC2) for real wire and clock-tree power.
5. Power from real TPC-H vectors, once the `tpch/` SF10 data is available.
