# Review of the PU implementation (`rtl/`)

Date: 2026-11-23. Read: `README.md`, `PLAN.md`, `PLAN_REVIEW.md`, all of `src/`, `ref/`, `tb/`, `formal/`, `syn/` and
the reports in `syn/out/`, `tpch/NOTES.md` (PU section), `notes/22` 3.1-3.7 and 8.2-8.3, `tpch/bare.py`,
`tpch/lookahead.py`. Nothing under `paper/` was read.

All experiments ran on a copy of `rtl/` in a scratch directory. No file under `src`, `ref`, `tb`, `syn`, `formal`
was changed. Tools: the OSS CAD Suite in `~/tools/oss-cad-suite`, Nangate45 typical.

Marks: **[ran]** I ran it and give the output; **[read]** from reading the code.

## Verdict

**The PU datapath is correct as far as I can push it. The report around it is not yet trustworthy in four places.**

What holds:
- I re-ran `tb/run_rtl.sh` (22 runs, Icarus + Verilator) and `syn/gls.sh` (10 gate-level runs): 0 errors. [ran]
- The comparator proof passes, and three bugs I planted are caught. [ran]
- I wrote two more behavioural references and proved them against the RTL for all inputs: slot placement + mask op
  (`pu_slot`) and the whole filter result (`pu_filter`: range check, sign, invert, all four widths). Both pass. [ran]
- 15 of 16 real bugs I planted in the RTL are caught by the random test. [ran]
- I connected `pu_decoder` to 16 PUs and drove commands at issue time: 0 errors. [ran]

What does not hold:
1. **The logic-depth column of the README is wrong** (F1). The tool walked through flip-flops.
2. **The decoder and the per-bank PRD are not tested at all** (F2). They happen to work.
3. **The test scripts can report a pass on stale binaries** (F3).
4. **Every PWGB overwrites bounds and config**, also a PWGB that writes a set word (F4). Spec mismatch.

Area numbers are sound as "cells, no buffers". They rise 4-10 % once buffers are added (F5).

No functional bug was found in `pu`, `pu_filter`, `pu_join`, `pu_slot`, `pu_cmp_seg`, `pu_cfg`.

---

## Must-fix

### F1. Logic depth in the README is wrong: `ltp` ran through the flip-flops
- Evidence [ran]: `syn/out/*.flat.ltp` hold 2,396 to 29,294 "Detected loop" warnings each. The reported path contains
  flops, for example `all_x0.flat.ltp`: `36: \m_q [56] (via $auto$ff...)` ... `41: \g_join.u_join.m1_q [56]`.
  `ltp -noff` does not know that `DFF_X1` is a flop, because the library was read with `read_liberty -lib`.
- True depth, with the `DFF_X1` cells deleted before `ltp` (0 loop warnings):

  | Configuration | README | Flop to flop |
  |---|---|---|
  | filter, no X | 29 | 24 |
  | filter, X | 29 | 24 |
  | join core, no X | 43 | 28 |
  | join core, X | – (file says 44) | 30 |
  | all, no X | 43 | 28 |
  | all, X | 40 | 27 |

- Even the corrected number is weak. The netlist has no buffers (F5) and ABC ignores the period (F10), so it is the
  depth of an area-mapped netlist, not a minimum.
- Fix: in `syn/syn.sh` run `ltp` on a copy with the flops removed (`delete t:DFF_X1; ltp`), or run it before
  `dfflibmap` with `-noff`. Fail the script if the `.ltp` file contains "Detected loop". Correct the README table and
  fill the missing cell.

### F2. `pu_decoder` and the per-bank PRD are never simulated
- Evidence [read]: `tb/run_rtl.sh:6` and `syn/gls.sh:17` do not list `pu_decoder.sv`. `tb_pu.sv:33-45` drives `x_en`,
  `op`, `prd_sel` directly from the vector file, with `prd_sel = (op == PRD)` always.
- Evidence [ran]: Icarus cannot compile the decoder: `src/pu_decoder.sv:30: error: This assignment requires an
  explicit cast.`
- Evidence [ran]: a mutant that ignores the bank select (`pu.sv:110` changed to `(op == OP_PRD) ? m_q : arr_data`)
  passes every vector set with 0 errors. So accepted revision F1 of the plan (PRD per bank) has no test.
- `pu_channel` (PLAN section 2: 16 PUs + decoder) was not built. The README file table leaves it out without saying so.
- What I ran: decoder + 16 `pu`, commands presented at issue time, PRD sent to bank `t mod 16`, the other 15 banks
  checked for `rd_data == arr_data`. Verilator, `rand_all` and `replay_q12join`, `HAS_XREG` 1 and 0: 0 errors.
  So `x_en` timing, the one-slot control delay and the one-hot are right. Testbench:
  `/tmp/claude-1005/-home-sai-cs254-project/ab6023de-ebfc-4e8d-bb2e-43d55316edda/scratchpad/tb_chan.sv`.
- Fix: add that testbench (or `pu_channel`) to `tb/`, with different data per bank and the F4 bank-to-record rule.
  Make line 30 compile in Icarus with `assign opi = op_t'(cmd_valid ? cmd_op : OP_NOP);` (checked: Icarus accepts it).

### F3. The test scripts hide compile errors and can pass on old binaries
- Evidence [read]: `tb/run_rtl.sh:11` sends the Icarus compile output to `/dev/null`; line 13-14 does the same for
  Verilator; `syn/gls.sh:17` keeps only lines with "error", 3 at most. No exit status is checked. `tb/build/` keeps
  the old `.vvp` files and Verilator binaries.
- Evidence [ran]: I appended a syntax error to `pu.sv` (scratch copy) and ran the script's own two lines for
  `q6f`. Output: `RESULT vec/replay_q6: 2304 commands, 64 PRDs, 2304 state checks, 0 errors`. The old binary ran.
- Fix: `set -e`; remove the target before compiling; print compiler errors; end the script with a count of RESULT
  lines against the expected number and a non-zero exit when any is missing.

### F4. Every PWGB loads bounds and config, also one that writes a set word
- Spec: buffer word 0 holds the bounds; words 1..63 hold set words; "assumes ... the filter's `PWGB` writes word 0
  only" (notes/22 3.5). The plan review F2 said: strobe on "PWGB to buffer word 0". PLAN section 9 F2 dropped the
  "word 0".
- RTL [read]: `pu.sv:44` `ld_bounds = (op == OP_PWGB)`, no word index. `pu_decoder` has no buffer word index and no
  strobe at all for PWGB or PLD GB.
- Effect: a PWGB that writes a set word puts set bits into lo, hi, size, sign, invert and mask op of all 16 PUs. The
  programs in `notes/*.pim` load set words before the filters, and each filter has its own PWGB, so they survive.
  It is still an unwritten ordering rule, and the golden model has the same reading, so no test can see it.
- Fix (pick one, write it in PLAN section 9):
  - the decoder makes `ld_bounds` only for a PWGB to word 0 and passes the buffer index for PLD GB; or
  - state the rule: "any PWGB clobbers bounds and config; a config PWGB must follow the last set-word PWGB".
  The first matches the notes.

---

## Should-fix

### F5. The netlists have no buffers; area is 4-10 % low and the set-select gain disappears
- Evidence [ran]: no `BUF_*` and no cell above X1 in any `syn/out/*.flat.stat`. `all_x0.flat.v` has 216 nets with
  fan-out above 32 and 48 above 100 (up to 265). `abc -liberty -D` without `-constr` runs
  `strash; ...; &nf; &put` (see `all_x0.flat.log:1373-1388`): no `buffer`, no `upsize`.
- Same flow with `-constr` (`set_driving_cell BUF_X1; set_load 3.0`), no X register [ran]:

  | Configuration | README um² | With buffers um² | Change | Buffers |
  |---|---|---|---|---|
  | filter | 5,623 | 5,821 | +3.5 % | 248 |
  | join core | 13,206 | 13,867 | +5.0 % | 669 |
  | all | 26,635 | 29,207 | +9.7 % | 3,223 |

- Increments become: join core 10.1 K gate-eq (README 9.5 K, estimate 9.5-11 K); set-select 19.2 K (README 16.8 K,
  estimate about 20 K). So "set-select is 16 % below the estimate" is an effect of leaving out the buffers.
- Fix: use the `-constr` form (or the OpenROAD-flow-scripts ABC script, plan review F27) for the headline, and say
  in the README which one it is.

### F6. The golden model and the RTL differ when a bound is not repeated
- Evidence [ran]: 8-bit lanes, `lo = 0x10`, `hi = 0x20` only in byte 0 of each 64-bit field, `x` = all bytes 0x18.
  Golden: all 256 bits pass. RTL: `0101...01` (only lanes 0, 8, 16, 24 of each word pass). 10 mismatches.
- Cause [read]: `pu_ref.py:63-64` uses `lo & mask` for every lane; `pu_cfg.sv:26` uses `lo[j mod 64]`.
- The generator always repeats the bound (1,468 of 1,468 PWGBs in `rand_all`), so this never shows.
- Fix: the golden model should model the hardware (lane i uses bits `(i*w) mod 64 ...`), and the random test should
  send some non-repeated bounds. Then the host rule F15 is a format rule, not a hidden assumption of the test.

### F7. What the independent anchor covers, and what rests on one author's reading
- The replay check is sound [read]: `gen.py:213-227` compares each golden PRD word with per-record bits computed by
  numpy in `lookahead.bitmap` (or `commit < receipt`), through the packer. It runs before the vectors are written.
- It anchors only: signed, 8 and 16 b, `invert = 0`, SET / AND / OR, PCMP, and PCC with operator `<` at 16 b
  (measured from the vector files).
- Not anchored by anything but `pu_ref.py` (same author, word level; plan review F22 asked for a per-record model):
  PSEL, PMC, M1, PLD GB, operators other than `<`, unsigned, invert, 32 / 64 b, mask op 11, the config bit positions
  (the packer is shared by both sides).
- I closed part of this [ran]: `pu_slot` and `pu_filter` proved equal to references I wrote from PLAN section 4
  (slot proof 488 K variables, a planted slot bug fails; filter proof 0.4 s). I also read PSEL, the operator bits and
  PMC against notes/22 3.1-3.3; they match.
- Fix: add the two proofs to `formal/`. Add two replays against DuckDB-derived bits: a set test with PSEL (Q12
  shipmode, `notes/L2_q12_join_set.pim`) and Q19's exact OR groups through M1 (notes/22 6.5).

### F8. The replays do not check state, and the "state checks" count is not a count of checks
- Evidence [ran]: bit 21 (M defined) is 0 on every command of all four replay files. `gen.py:48` sets it only from
  `m_defined`, which only `init_m` uses. So replays compare PRD words only.
- `tb_pu.sv:85` counts `checks++` before the `c[21]` test. "2304 state checks" for Q6 is 0 real M compares.
- Fix: in `write()`, mark M defined once a SET has covered all slots (or call `init_m` first in replays); count a
  check only when a compare happens; print M, M1, V compares separately. README line "state after every command"
  is true for the random runs only.

### F9. Behaviours with no test or no definition
Measured on the vector files, or by a planted bug [ran]:

| Behaviour | Status |
|---|---|
| PRD to another bank (`op = PRD`, `prd_sel = 0`) | never driven (F2) |
| PCC / PSEL / PMC / PLD on a PU with `HAS_JOIN = 0`; PSEL with `HAS_SETSEL = 0` | never driven. The RTL ignores them (M holds; I checked with a short directed run). The plan does not define it and the golden model has no configuration switch |
| `HAS_JOIN = 1, HAS_SETSEL = 0, HAS_XREG = 0` | never simulated; `join_x0` netlist has no gate-level run; `all_x0` has one |
| `x_en` | not observable: a mutant with X captured every cycle passes everything. It is a power feature only; say so, and check it with an assertion or in the power run |
| `x` on slots that do not read | the vectors hold 0 there (random only on NOP). Drive random data |
| Last, partly filled row group (the `pad` path of `pack.column`) | not replayed |
| Non-repeated bounds | F6 |

Well covered in `rand_all` (counts): PCC at 64 b 738, each of the 8 operators 329-382 times at all four widths,
`cfg.invert = 1` during PCC 839, PSEL with size not 8 b 2,132, PSEL invert 880, PMC with dst = src 585 (all 8
invert / op combinations), ignored PWGB bits non-zero 1,467 of 1,468, `lo > hi` 644, compare decided at every byte
position (64 b: 217-828 lanes per byte), sign-bit cases, `PLD; PCC; PLD` 13 (960 in the Q12 replay), `PCMP; PRD` 294,
`PCMP; PMC` 777, `PWGB; PCMP` 319. The random generator is good.

### F10. "ABC target 2.284 ns" has no effect
- Evidence [ran]: with `-D 500` and `-D 2284` ABC returns the same gates (3,625 and 22,769); only sizing moves
  (area +2 % and +0.1 %). ABC's own estimate with buffers: about 0.9 ns (filter) and 1.0 ns (all), no wires.
- The README header reads as if a 2.284 ns constraint were met. No timing run exists yet.
- Fix: write "no timing constraint applied; timing is the next phase", or quote the ABC `stime` number as a rough
  logic-process figure.

### F11. Layout rule is written wrong
- PLAN F5 and `pack.py:6-7`: "a column of width w starts at a word address that is a multiple of w/8".
- Slot = `addr mod w` (8 b: `addr[2:0]`, 16 b: `addr[3:0]`...), and a column has w words, so the start must be a
  multiple of **w words**. A 16-bit column at word 2 obeys the written rule and breaks. Every column in `bare.py`
  (32, 48, 56, 16, 40) meets the stronger rule, so nothing fails today.
- Fix: correct both texts before the rule is copied to `tpch/NOTES.md`.

### F12. Smaller report and method gaps
- Hierarchical and decoder runs have no `check -assert` (`syn.sh:21, 27`).
- PLAN section 5 promised 10^5 random commands per configuration and unit tests per module; the runs have about
  20 K and no unit tests (the proofs replace the comparator test; say so).
- Gate-level runs check PRD words only (`CHECK_STATE = 0`). That is fine with the forced `PMC; PRD` pairs (5 % of
  commands), but say it. The cell models come from the same Liberty file read by the same tool; a run with the
  vendor Verilog models would be more independent. No clock-gate cell is in any netlist, so ignoring `CLKGATETST`
  changes nothing.
- With `HAS_XREG = 0`, normal reads toggle `x` into three comparators (plan review F11). Not gated, not reported.
- The config register makes a PSEL or PCC with a new mask op cost one more PWGB (PLAN F8). The `.pim` programs issue
  PSEL at the start of a step with no PWGB in front, so their times do not match this RTL yet.
- Comparison with the hand estimates: fair in scope (X register left out on both sides, flop about 6 gate-eq). The
  filter figure includes the read-path mux, which the estimate did not have. Quote the buffered numbers (F5).

---

## Nits

- **N1.** Dead logic: `pu_slot.we` and the `pmc_op != 3` term in `pu_join.sv:94` change nothing (mutants without them
  pass, because op 11 already returns the old value). `op == OP_PRD &&` in `pu.sv:110` repeats what `prd_sel` says.
- **N2.** Icarus prints "sorry: constant selects in always_* processes are not fully supported" for `cfg.size`
  inside `always_comb` (`pu.sv:85-91`). Harmless, but hidden by `2>/dev/null`. Copy the fields to plain wires.
- **N3.** `pu_decoder` passes opcodes 9-15 through. The PU treats them as NOP. State it.
- **N4.** Lint: `ue64` unused when `EQ_OUT = 0`; `MOP_*` unused in the decoder; `gb[255:134]` unused. As the README
  says.
- **N5.** `tb/build/` is 1.9 GB (Verilator object trees) and is not ignored by git.
- **N6.** `tb_pu.sv` reaches into `dut.g_join.u_join.m1_q` with an `ifdef`; the gate-level run edits the testbench
  with `sed`. A small wrapper with debug ports would remove both.

---

## Checked and found correct

- Slot and window per width; PSEL forced to the 8-bit geometry; `cfg.invert` not applied to PCC; no-write codes;
  `cc = 000 / 111`; PMC semantics and dst = src; operand order "row word op V"; V and M written at the end of
  stage 2; `PLD j; PCC j; PLD j+1`; `PCMP; PRD` reads the new M. [read + ran]
- Two writers of M cannot fire together (`cmp_op` and `pmc_m_we` need different opcodes). [read]
- Testbench timing: inputs change while the clock is low, state is compared after the edge, a mutant that bypasses
  the X register fails 44,941 checks. A one-slot error in the RTL would not be hidden. [ran]
- Formal miter: both modules present (581 cells), all eight outputs compared, no constraints, three planted bugs
  fail. [ran]
- Flop counts (390 / 902, +256 with X), cell areas and the per-block list match the `.stat` files. Flattening,
  `check -assert`, `dfflibmap` are in the headline run. [read]
