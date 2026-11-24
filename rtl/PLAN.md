# Plan: the per-bank PU in SystemVerilog (synthesizable)

Date: 2026-11-23. Goal: an RTL model of the processing unit that (1) matches the specified design bit for bit,
(2) synthesizes, so that area, timing and power can be measured, and (3) separates per-bank logic from per-channel
logic so the die overhead can be computed (16 PUs per channel, 24 channels per GPU, banks per die from the GDDR7
organization).

## 1. Sources of truth (what the RTL must implement)

| Part | Source |
|---|---|
| Filter unit: bound register, comparators A (x >= lo) and B (x <= hi), per-lane AND, invert, slot placement, mask op SET / AND / OR on the slot window, mask M 256 b, PRD | `tpch/NOTES.md` "Units, per bank"; functional model `tpch/bare.py` (`bitmap`, slot rule in the docstring) |
| Join unit: V (256 b, from row word or Global Buffer), comparator C (lt, eq per lane), 3-bit operator, set-select (32 x 256:1, optional invert), M1, mask combine (dest M / M1, src M / M1 / V, invert, op) | `pim_exploration/notes/22_join_unit.md` 3.1-3.3 |
| Touch points: 3-to-1 result mux before slot placement; second (whole-register) write port into M; GB -> V path | notes/22 3.2 |
| Pipeline: stage 1 = array read puts X on the data lines; stage 2 = compute, M / V captured at the end of stage 2; result latency 2 slots | notes/22 3.6 |
| Command decoding once per channel; config fields (size, sign, invert, mask op) loaded with the bounds from one Global Buffer word | decisions of 2026-11-23 (`pim_exploration/notes/25_ll_code_interleaving.md` header; figure `tpch/plots/make_pu_figure_excalidraw.py`) |

## 2. Module split

| Module | Instances | Contents |
|---|---|---|
| `pu_cmp_seg` | 3 per PU (A, B, C) | segmented magnitude comparator over 256 b: per-byte (lt, eq), combined by a fixed tree into 16 / 32 / 64-bit lanes; the lane width selects which level's result each lane uses. Signed: flip the top bit of each lane on both operands before comparing. Outputs per-lane lt, eq (32 lanes max; lanes wider than 8 b use the lowest-index entry of their group) |
| `pu_lane_bcast` | 2 per PU (lo, hi) | replicates a 64-bit bound to 256 b at the lane width (4-to-1 mux per bit). The bound register stores 8 B each, as in the spec |
| `pu_slot` | 1 per PU | slot placement: n = 256 / width result bits into mask bits [slot*n, slot*n + n); produces the 256-bit new-value vector and a 256-bit window enable. Slot = low bits of the word address (spec: each column starts on a word boundary that matches its width) |
| `pu_filter` | 1 per PU | A, B, AND, invert -> up to 32 result bits |
| `pu_join` | 1 per PU, `parameter HAS_JOIN` | V register + input mux, comparator C + operator select, set-select (`parameter HAS_SETSEL`), M1, mask combine |
| `pu` (top, per bank) | 16 per channel | registers (bound lo / hi, config 6 b, M), result mux, slot placement, mask logic, M write ports, PRD output; instantiates filter and join |
| `pu_decoder` | 1 per channel | decodes the PIM command (opcode + fields) into one-hot control signals broadcast to the 16 PUs; holds nothing data-dependent |
| `pu_channel` | 1 per channel (for integration tests only) | 16 `pu` + 1 `pu_decoder` + the Global Buffer as a behavioural memory (the Global Buffer is SRAM, not synthesized here; its area comes from a memory model, stated separately) |

Area is reported for `pu` (x16 per channel) and `pu_decoder` (x1 per channel) separately. Three configurations of
`pu`: filter only (`HAS_JOIN=0`), filter + join core (`HAS_JOIN=1, HAS_SETSEL=0`), all (`HAS_JOIN=1, HAS_SETSEL=1`),
matching the three area rows already estimated in notes/22 8.3, so the RTL numbers replace the estimates directly.

## 3. Interface of `pu` (one bank)

Inputs, all synchronous to `clk` (one clock = one column-command slot, 4 tCK = 2.284 ns, 438 MHz):
- `x[255:0]`, `x_valid`: the row word from the bank's I/O sense amplifiers (stage 1 output).
- `gb[255:0]`: the Global Buffer word on the 256-bit channel bus.
- From the decoder (identical for all 16 PUs): `op` (one of NOP, LOAD_BOUNDS, PCMP, PLD_ROW, PLD_GB, PCC, PSEL,
  PMC, PRD), `addr[5:0]` (word address; slot derived), `cc_op[2:0]` (PCC operator L, E, G), `pmc_dst`, `pmc_src[1:0]`,
  `pmc_inv`, `pmc_op[1:0]`.
Outputs: `m_out[255:0]` (M, driven onto the bank's 256-bit read path on PRD), `m_valid`.

Global Buffer word layout for LOAD_BOUNDS: `lo = gb[63:0]`, `hi = gb[127:64]`, `cfg = gb[133:128]` with
`size[1:0]` (00 8 b, 01 16 b, 10 32 b, 11 64 b), `signed`, `invert`, `mask_op[1:0]` (00 SET, 01 AND, 10 OR).
PCC and PSEL use the same `size`, `signed`, `mask_op`; PSEL uses `invert`.

Pipeline: inputs captured in a stage-1 register (X held, per notes/22 3.6 "a 256-bit pipeline register is needed" if
the sense-amplifier latches do not hold it; included and reported separately so its area can be removed); stage 2
computes and writes M / M1 / V / bound / config at the end of the slot. One command per clock, result latency 2.

## 4. Semantics to match exactly

- Filter lane i (width w, n = 256 / w lanes): `R[i] = ((lo <= x_i) && (x_i <= hi)) ^ invert`, signed or unsigned
  at width w.
- C: per-lane lt, eq of `x_i` vs `v_i`; gt = !lt && !eq; `R[i] = (L && lt) || (E && eq) || (G && gt)`.
- Set-select (w must be 8): `R[i] = V[x_byte_i] ^ invert`, 32 lanes.
- Slot placement: mask bit `slot*n + r` takes lane r, r < n; other bits hold.
- Mask op on the window: SET M = R; AND M = M & R; OR M = M | R.
- PMC: `dst <= op(dst, src ^ (inv ? all ones : 0))` over all 256 bits; dst in {M, M1}, src in {M, M1, V}.
- PRD: `m_out = M`; no state change.
- Record order: mask bit `b` is record `b` of the row group (the `bare.py` functional model relies on this).

## 5. Verification

1. **Unit tests per module** (Verilator or Icarus): `pu_cmp_seg` against a behavioural per-lane compare for all four
   widths, signed and unsigned, random + edge values (0, max, min, equal, lo > hi); `pu_slot` for every width and slot.
2. **Golden model**: a small Python reference (`rtl/ref/pu_ref.py`) that executes the same command list on 256-bit
   integers, written from section 4 independently of the RTL. A random command-sequence test generates commands,
   runs RTL and reference, and compares M, M1, V and `m_out` after every command (10^5 commands per configuration).
3. **Real data**: replay the PIM steps of Q6 (filter only) and Q19 look-ahead (several bitmaps) for the first 64 row
   groups of channel 0 from `tpch/cache/*_sf10.npz` with the command order of `tpch/bare.py` / `lookahead.py`, and
   compare every PRD word with the bitmap the Python functional model produces (`bare.bitmap`, `lookahead.bitmap`).
4. A join-unit replay on a notes/22 example (Q12 `commit < receipt` via PLD ROW + PCC) against DuckDB-derived bits.

## 6. Synthesis flow

- Tools: OSS CAD Suite (YosysHQ release tarball: Yosys, Verilator, Icarus; slang or sv2v front end for SV) installed
  under `~/tools/oss-cad-suite`; OpenSTA (container or build) for timing and power.
- Library: Nangate / FreePDK45 open cell library (from OpenROAD-flow-scripts), typical corner. Optionally ASAP7.
- Yosys: `synth -top pu`, `dfflibmap`, `abc -liberty -D <period>`, `stat -liberty` -> area in um^2 and NAND2
  equivalents; per-configuration and per-submodule (hierarchy kept for the breakdown).
- OpenSTA: clock 2.284 ns (438 MHz) and a tighter 1.0 ns target; report worst slack and the critical path (expected
  through comparator + slot mux + mask op).
- Power: OpenSTA `report_power` with switching activity from the Q6 / Q19 replay (VCD from simulation), and with a
  default activity for comparison.
- **DRAM-process scaling**: the cell library is a logic process. The paper must state the conversion to a DRAM
  periphery process (DRAM logic is slower and less dense: a factor, cited, applied to area and delay), the same way
  the current estimates do in notes/22 8.3 and `join/area/AREA.md`. RTL gives gate counts and a logic-process
  baseline; the scaling factor stays an assumption and is reported as such.
- Die share: area per PU x 16 x banks per die / die area, using the die area already used in `join/area/AREA.md`.

## 7. Out of scope here

- The Global Buffer SRAM and the 256-bit channel bus wiring (area from a memory compiler model or CACTI, separate).
- The memory controller side (command issue, PIM mode switch); the mode-register write is standard DRAM logic.
- Bank array, sense amplifiers, I/O path: unchanged DRAM.

## 8. Deliverables

`rtl/src/*.sv`, `rtl/tb/*` (unit + random + replay tests), `rtl/ref/pu_ref.py`, `rtl/syn/` (Yosys / OpenSTA
scripts, reports), `rtl/README.md` with results: area per configuration (um^2, NAND2 eq), slack at 2.284 ns and
1.0 ns, power at the Q6 activity, and the die share after the stated DRAM-process factor.

## 9. Revisions after review (rtl/PLAN_REVIEW.md, 2026-11-23)

Accepted (F numbers of the review):
- **F1** PRD is per bank: `pu_decoder` makes a 16-line one-hot `prd_sel`; the PU has the read-path mux
  (`rd_data = prd_sel ? M : arr_data`, 256 x 2:1), reported as its own line. PRD writes no state.
- **F2** There is no LOAD_BOUNDS command. `PWGB` (one per filter, as `bare.py` charges) puts the buffer word on the
  256b bus and the bound and config registers capture it.
- **F3** Every command writes state at the end of its stage-2 slot (register-only commands idle in stage 1). Control
  and `gb` reach the PU in stage 2; the one-slot control delay sits in `pu_decoder` (per channel). PRD reads M in stage
  2. Any command order then gives the sequential result; no forwarding.

  | Command | stage 1 (slot t) | stage 2 (slot t+1) | write edge | visible to |
  |---|---|---|---|---|
  | PCMP, PCC, PSEL, PLD ROW | array read, X captured (`HAS_XREG`) | compute | end of t+1 | command issued at t+1 |
  | PWGB, PLD GB, PMC | idle | gb on bus / combine | end of t+1 | command issued at t+1 |
  | PRD (selected bank) | idle | `rd_data = M` | none | – |
- **F4** Orders: byte k = `x[8k+7:8k]`; lane i at width w = `x[i*w+w-1 : i*w]`; lane i of slot s = record `s*n + i`;
  mask bit b = record b of the bank's row group. Record placement: row group g = records `[4096g, 4096g+4096)` on
  channel `g mod 24`; bank b holds records `4096g + 256b .. +255`. A packer (`rtl/ref/pack.py`) writes the `.npz`
  columns into 32 B words with this rule; it is the storage format.
- **F5** Slot = `addr[2:0] / [3:0] / [4:0] / [5:0]` for 8 / 16 / 32 / 64 b; window of mask bit b: `b[7:5] / [7:4] /
  [7:3] / [7:2] == slot`; mask bit b takes lane `b mod n`. Layout rule: a column of width w starts at a word address
  that is a multiple of w (words) (corrected after the implementation review, F11).
- **F6** Comparator outputs four compact vectors per width; slot placement is one 4:1 mux per mask bit.
- **F7** PSEL always uses the 8-bit geometry (n = 32, slot `addr[2:0]`), whatever `size` holds.
- **F8** Supersedes: the NOTES "PCMP fields" and the notes/22 3.3 PCC width / sign / mask-op fields now come from the
  config register; a PCC or PSEL needing another size or mask op needs a PWGB first (not charged in notes/22 [sim]).
  Command fields that stay: `addr[5:0]`, `bank[3:0]` (PRD), `cc[2:0]` (PCC), PMC `dst, src[1:0], inv, op[1:0]`.
- **F9** `mask_op = 11`, `pmc_op = 11`, `pmc_src = 11`: no write. `cc = 000` all false, `111` all true. `cfg.invert`
  does not affect PCC. `gb[255:134]` ignored.
- **F10** Signed: the byte tree compares unsigned; at each lane root `lt = lt_u ^ (signed & (a_msb ^ b_msb))`; eq
  unchanged. `lo > hi` gives all-false (all-true with invert) at every width and sign, with no special logic.
- **F11** `parameter HAS_XREG` (1: 256-bit X register enabled only on PIM array reads; 0: X is a stage-2 input held
  by the sense amplifiers). No `x_valid` port.
- **F12** The PU counts in 4 tCK slots; PMC and PLD GB are 4 tCK commands here, as charged in notes/22.
- **F13** No reset on M, M1, V, bounds, config. Registers are flip-flops (the spec's "latch" would be smaller).
- **F15** The host writes each bound already repeated across its 64 bits (an 8-bit bound eight times, ...), so the
  256-bit bound is wiring: `bound256[j] = bound[j mod 64]`. `pu_lane_bcast` is dropped. Host-visible format change,
  to be copied into `tpch/NOTES.md`.
- **F16** Bound, config and the size / window decode sit in their own block `pu_cfg` for the report.
- **F17** Headline area from a flattened run; breakdown from a hierarchical run.
- **F18** Byte tree; A and B use only `lt` (`x >= lo` = `!lt(x, lo)`, `x <= hi` = `!lt(hi, x)`); C uses lt and eq.
- **F20** Formal equivalence of the comparator against a per-lane behavioural compare (Yosys miter + SAT, all widths,
  signed and unsigned) plus random operands that share a prefix down to each byte.
- **F21** The random and replay tests also run on the synthesized netlist; `verilator --lint-only`; no inferred
  latches; Yosys `check -assert`.
- **F22/F23** Replay anchors (Q6, Q12 look-ahead with OR, Q19 look-ahead) compare every PRD word with
  `bare.bitmap` / `lookahead.bitmap` per record; the random test covers invert, 32 / 64-bit lanes, lo > hi, all
  orders of commands.

Deferred to the synthesis phase (after this RTL is reviewed), as the review asks: timing as logic depth + FO4 and a
scaled-period sweep (F24), place and route with 3 routing layers or a stated utilization (F25), conversion to DRAM
area through gate-equivalents with low / central / high (F26), report list (F27), I/O delays (F28), netlist-activity
power and energy per command (F29), die share with the Global Buffer per configuration (F14, F30). This phase gives
cell area, gate-equivalents and logic depth from Yosys.

## 10. Revisions after the implementation review (rtl/IMPL_REVIEW.md, 2026-11-23)

- **F4** Only a PWGB to Global Buffer word 0 loads bounds and config. The decoder takes the buffer word index
  (`cmd_gbidx`) and sends `gb_w0` to the PUs; a PWGB of a set word (words 1..63) leaves bounds and config alone.
- **F6** The golden model reads lane i's bound from bits `(i*w mod 64) ..` of the 64-bit bound, as the hardware does;
  the random test sends non-repeated bounds on 10 % of PWGBs. Repeating the value is a host format rule.
- **F9** With `HAS_JOIN = 0` the join commands (PLD ROW, PLD GB, PCC, PSEL, PMC) change nothing; with
  `HAS_SETSEL = 0`, PSEL changes nothing. Opcodes 9..15 are NOP (the decoder maps them). `x_en` only gates the X
  register (power); results do not depend on it.
- **F2** Channel test: `pu_decoder` + 16 PUs, PRD rotating over the banks, the other banks checked for a transparent
  read path.
- **F5, F10** Synthesis maps with buffering and sizing (`abc -constr`); no timing constraint is applied yet.
- **F1** Logic depth is measured flop to flop (flops removed before `ltp`).
