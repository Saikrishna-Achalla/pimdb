# Review of `rtl/PLAN.md` (per-bank PU in SystemVerilog)

Date: 2026-11-23. Read: `rtl/PLAN.md`, `tpch/NOTES.md` (PU section), `notes/22` 3.1-3.7 and 8, `notes/25` header,
`join/area/AREA.md`, `area_estimate.py`, `tpch/bare.py`, `tpch/lookahead.py`, the PU figure generator and preview.
Nothing under `paper/` was read. No tool was run (none is installed).

Marks: **[spec]** read in the project notes today; **[calc]** worked out here by hand; **[recalled]** from memory, to
be checked before it is cited.

## Verdict

**Sound outline, not ready to implement.** The module list, the three configurations and the segmented comparator are
the right choices. Three kinds of gaps would make the result untrustworthy as written:

1. **The interface and pipeline are under-defined.** Several points where the plan is silent or differs from the
   notes (PRD is per bank, what LOAD_BOUNDS is, when register-only commands act, PSEL width, lane and byte order). Two
   people would write two different RTLs from section 3-4.
2. **The numbers would not survive review.** Timing "met at 2.284 ns in Nangate45" says nothing about a DRAM process;
   cell area is not die area; the Global Buffer is added hardware and is left out of the die share.
3. **Verification cannot yet claim bit-exactness.** Random data almost never exercises the comparator's carry
   path across bytes, and nothing checks the synthesized netlist.

All are fixable in the plan before any RTL is written. Findings follow, grouped by the six questions.

---

## 1. Semantics and interface against the spec

### F1. PRD is addressed to one bank, not broadcast — **must-fix**
- Spec: "16 PRDs per row step, read one bank at a time" [spec, NOTES "Units, per bank"]. Plan section 3 says all
  decoder signals are "identical for all 16 PUs" and gives no bank select.
- Change: add a per-bank `prd_sel` input, driven from a 16-line one-hot that `pu_decoder` makes from the bank address.
  Every other command stays broadcast. State that PRD writes no state.
- Also include the **read-path mux** (256 x 2-to-1, M or array data, about 0.6 K gate-eq [calc]) in `pu` and report it
  as its own line. NOTES says "none extra" for bitmap out; that is not true in gates, and the mux sits on the normal
  read path, which a reviewer will ask about.

### F2. LOAD_BOUNDS is not a command in the spec — **must-fix**
- Spec commands are `PWGB, ACT, PCMP, PRD` (+ `PLD ROW, PLD GB, PCC, PSEL, PMC`). The bound latch is "loaded by PWGB"
  [spec]. `bare.py` and `lookahead.py` charge **one PWGB per filter and nothing else**.
- The plan adds an op `LOAD_BOUNDS`. If that is a second command after PWGB, every reported PIM time is short by one
  command per filter.
- Change: define LOAD_BOUNDS as the internal strobe of `PWGB` to buffer word 0 (the bound and config registers capture
  the word as it is written). No extra command. Say on which slot after PWGB the registers hold the new value, and
  that a PCMP / PCC / PSEL must not be in stage 2 before that slot.

### F3. Pipeline position of every command is not defined — **must-fix**
- notes/22 3.6 defines it only for array-read commands (stage 1 read, stage 2 compute, write at end of stage 2) and
  then adds ordering rules for PMC ("8 tCK after the writer of its source"), PRD and PLD GB.
- Plan: "inputs captured in a stage-1 register ... one command per clock, result latency 2". It does not say when
  PMC, PLD_GB, PRD and LOAD_BOUNDS act, whether `gb` and the control signals are also registered, or where.
- Change, simplest correct form:
  - **Every command writes state at the end of its stage-2 slot**, register-only commands included (they idle through
    stage 1). Then any command order gives the sequential result, the PU needs no forwarding, and the 8 tCK rules of
    3.6 become latency statements, not correctness rules.
  - The one-slot delay of the control signals lives **in `pu_decoder` (per channel)**, not in each PU.
  - `gb` is not registered in the PU; the decoder times the buffer read so the word is on the bus in stage 2.
  - PRD selects M in stage 2 as well, so `PCMP; PRD` back to back reads the new M.
- Add a one-row-per-command timing table to the plan (slot of issue, slot of compute, edge of write, first slot the
  result is visible). The reference model and testbench are written from that table.

### F4. Lane order, byte order and record order are not written down — **must-fix**
- Needed, and consistent with notes/22 8.2 ("lane 13 (bits 208-223)" at 16 b) [spec]:
  - byte k of the 32 B word = `x[8k+7:8k]`; lane i at width w = `x[i*w + w-1 : i*w]`, little-endian inside the lane;
  - lane i of slot s is record `s*n + i`; mask bit b = record b of the bank's row group.
- Also missing: which records go to which bank and channel (bare.py implies group g = records `[4096g, 4096g+4096)`,
  channel `g mod 24`; bank b = records `256b .. 256b+255` of the group is **not stated anywhere** I read).
- No packer exists in `tpch/` that turns the `.npz` columns into 32 B words (the functional model works per record).
  The replay test must write one. Put its definition in the plan, because it is the storage format the paper claims.

### F5. Slot derivation: give the exact bits — **should-fix**
"Slot = low bits of the word address" is ambiguous. Exact rule [calc from the tile map in bare.py; all columns check]:

| size | w | n lanes | words per column | slot | window of mask bit b |
|---|---|---|---|---|---|
| 00 | 8 | 32 | 8 | `addr[2:0]` | `b[7:5] == slot` |
| 01 | 16 | 16 | 16 | `addr[3:0]` | `b[7:4] == slot` |
| 10 | 32 | 8 | 32 | `addr[4:0]` | `b[7:3] == slot` |
| 11 | 64 | 4 | 64 | `addr[5:0]` | `b[7:2] == slot` |

Mask bit b takes lane `b mod n`. State the layout rule it relies on: a column of width w starts at a word address
that is a multiple of w/8.

### F6. Comparator output format conflicts with slot placement — **should-fix**
- Plan: `pu_cmp_seg` outputs 32 entries and "lanes wider than 8 b use the lowest-index entry of their group", so at
  16 b lane i sits at entry 2i. `pu_slot` and section 4 assume lane r at index r.
- Change: the comparator outputs four compact vectors (`r8[31:0]`, `r16[15:0]`, `r32[7:0]`, `r64[3:0]`). Slot
  placement is then the spec's single 4-to-1 mux per mask bit: `{r8[b%32], r16[b%16], r32[b%8], r64[b%4]}` by size.
  One mux level, no separate lane-select mux. The filter AND / invert and the operator select are done per vector
  (60 lanes in total) before the mux.

### F7. PSEL when `size != 8` — **must-fix (define it)**
- Spec: PSEL is 8-bit only and has its own fields (address, invert, mask op) [spec 3.3]. In the plan it takes
  geometry from the config register, which may hold 16 / 32 / 64.
- Change: PSEL forces the 8-bit geometry (n = 32, slot = `addr[2:0]`) whatever `size` holds. Put this in section 4,
  the reference model and the random test.

### F8. Config register changes what PCC / PSEL cost — **should-fix**
- notes/22 3.3 has width, sign, operator and mask op as **PCC command fields**; NOTES has them as **PCMP fields "not
  stored"**. The 2026-11-23 decision moves size / sign / invert / mask op to the config register. The plan follows the
  decision. Good, but:
  - a PCC or PSEL whose size or mask op differs from the previous filter now needs a PWGB first (for example
    `PSEL ... SET` then `PCC ... AND`). The [sim] times in notes/22 do not charge it;
  - `cc_op`, `pmc_*` stay command bits. The plan never says where these bits sit in a GDDR7 column command in PIM
    mode. notes/22 marks this "[est: not checked]".
- Change: add a short "supersedes" list (NOTES PCMP fields, notes/22 3.3 PCC fields) and state the extra PWGB. Define
  the command word that enters `pu_decoder` (opcode bits, address, bank address, 3 b operator, 6 b PMC fields), even
  if provisional; the decoder cannot be synthesized without it.

### F9. Undefined encodings — **should-fix**
Define, and test: `mask_op = 11`, `pmc_op = 11`, `pmc_src = 11` (suggest: no write); `cc_op = 000` (all false) and
`111` (all true); PMC with `dst == src`; `cfg.invert` must **not** affect PCC (spec: PCC has no invert); bits of lo / hi
above the lane width are ignored (or see F13); `gb[255:134]` ignored.

### F10. Signed handling: say which bits flip — **should-fix**
- "Flip the top bit of each lane" depends on the width: byte k holds a lane's top bit when `(k+1) mod (w/8) == 0`.
- Correct and cheaper inside a byte tree: do not flip inputs; at each lane-top byte use
  `lt' = lt xor (signed and (a[7] xor b[7]))`, `eq` unchanged. One AND + XOR per byte per comparator, reusing the
  XOR the equality already has. Either form is right; pick one and write it down.
- If the inputs are flipped instead, flip `x` **once** in `pu` and share it between A, B and C, not inside each
  `pu_cmp_seg`.
- `lo > hi` gives all-false (all-true with invert) in every width and sign with no special logic. Add it to
  section 4 as a stated property, since the planner relies on it [spec].

### F11. X pipeline register: keep it, make it a parameter — **should-fix**
- notes/22 3.6: needed only "if the read-amplifier latches do not hold" X; "not counted in the core". The plan
  includes it and reports it separately. That is the right call, with three changes:
  - `parameter HAS_XREG`, so both areas come from synthesis, not from subtraction;
  - with `HAS_XREG = 0`, `x` is a primary input in stage 2; state the input delay assumed (0 = the sense-amp latch
    holds it for the whole slot);
  - the X register, enabled only on PIM array reads, also keeps normal-mode reads from toggling the three
    comparators. Without it, 256 AND gates on `x` (gated by PIM mode) are needed. Say which, and count them.
- `x_valid`: the decoder already knows whether the command reads the array. Remove it or define what it adds.

### F12. Clock: 4 tCK slot against 2 tCK commands — **should-fix**
- The plan clocks the PU once per 4 tCK. But PRDs are 2 tCK apart (different banks) and notes/22 wants a
  register-only class at 2 tCK for PMC / PLD GB, while charging them 4 tCK today [spec 3.3, 3.6].
- Change: state that the PU model counts in 4 tCK slots, that PMC / PLD GB are 4 tCK commands in this RTL, and that
  PRD spacing is not a PU matter because each bank sees one PRD. If the 2 tCK class is ever claimed, the PMC path must
  be timed at 1.142 ns (DRAM time) separately.

### F13. Reset and register type — **should-fix**
- Say whether M, M1, V, bounds have a reset. Suggest none (M is defined by SET, V by PLD); a small reset only on
  control flops. It changes the flop cell and the area.
- The spec says "bound **latch**"; the plan builds flip-flops. That is the safe (larger) choice; say so in the report.
- Yosys has no enable flops or clock gates in Nangate45, so every held register becomes flop + 2-to-1 mux
  (about 2.5 gate-eq x up to 1.3 K bits [calc]). Report it, or instantiate one clock-gate cell per register and say so.

---

## 2. Module split, per bank against per channel

### F14. The Global Buffer is added hardware and must be in the die share — **must-fix**
- Plain GDDR7 has no global buffer; it comes from AiM. Section 7 puts it "out of scope, separate".
- 2 KB = 16 K bits. As flops that is about 98 K gate-eq per channel, or about 6 K per bank [calc] — the same size
  as the whole filter unit. Even as SRAM it is not zero.
- Change: report it per configuration and add it to the die share:
  - filter only: **no buffer needed** if PWGB data goes straight to the bound / config registers (one word);
  - join without set-select: one word for PLD GB;
  - with set-select: 64 words (state the cell assumed: latch array or small SRAM, and its source).

### F15. Bound replication can be free — **should-fix**
- `pu_lane_bcast` puts a 4-to-1 mux on each of 256 bits, twice. Two points [calc]:
  - the pattern repeats every 64 bits and bits 0-7 need no mux, so it is at most 56 muxes per bound, not 256;
  - the host writes the buffer word, so it can write the bound **already repeated across the 64 bits** (an 8-bit
    bound eight times, a 16-bit bound four times...). The hardware is then wires: `bound256[j] = bound[j mod 64]`.
    `pu_lane_bcast` disappears. Still generic.
- This changes the PWGB data format (upper bits no longer ignored), so it needs a line in the spec. Recommended.

### F16. What is identical across the 16 banks — **should-fix (report, do not move)**
- Bounds, config, the size decode and the 256-bit window enable are the same in all 16 PUs. The spec and the figure
  keep bound and config per bank, and the 256-bit bus cannot hold them during a scan, so per bank is right for RTL
  that "matches the spec".
- Change: keep them per bank, but give them their own hierarchy block (`pu_cfg`: bound + config + size / window
  decode) so the report can show "area that would move to the channel with a 134-wire bus". A reviewer will ask.
- The decoder is correctly per channel. Put in it: opcode decode, the bank-address one-hot for PRD, the one-slot
  control delay (F3), the PWGB capture strobe (F2). Keep in the PU only what depends on `size` and `addr`.

### F17. Headline area must be flattened — **should-fix**
- With hierarchy kept, Yosys does not optimize across module borders: unused `eq` outputs of A and B, the tripled
  sign flip and constant inputs stay.
- Change: headline area per configuration from a **flattened** run; the per-block breakdown from a hierarchical
  run; report both totals so the gap is visible.

---

## 3. Comparator

### F18. The segmented byte tree is correct and the right choice — **no change**, with notes
- Per byte `(lt, eq)`; combine `lt = lt_hi | (eq_hi & lt_lo)`, `eq = eq_hi & eq_lo`; levels 8 -> 16 -> 32 -> 64;
  28 combine nodes per comparator. Depth is log, which is what the 18-20 level estimate of notes/22 assumed.
- Alternatives: four separate comparators per width (about 4x the area); a ripple chain with cuts as the NOTES table
  literally words it ("carry links between slices": 64 levels at 64 b, misses the slot). The tree is the same
  function. Say in the plan that it implements the spec's "carry links cut at lane borders".
- A and B each need only one output: `x >= lo` is `!lt(x, lo)` and `x <= hi` is `!lt(hi, x)`. Only C needs `eq` at the
  lane root. Give `pu_cmp_seg` a parameter for it (or rely on the flattened run, F17).
- Write the byte compare structurally or check what Yosys infers from `<`; note the result in the report.

### F19. Signed pitfalls to test by name — **should-fix**
- Top-byte position per width (F10): a wrong mask passes every 8-bit test and fails only at 16 / 32 / 64.
- Sign applied to a byte that is the top of an 8-bit lane but the middle of a wider lane.
- Equal operands with the sign bit set; `lo = min, hi = max`; operands that differ only in the sign bit.
- PCC `=` and `!=` must not change with `signed`.

---

## 4. Verification

### F20. Random data does not test the comparator — **must-fix**
- Two random 64-bit lanes differ in the top byte with probability 255/256, so the lower seven bytes and the tree
  almost never decide the result (chance of reaching the lowest byte: 2^-56) [calc].
- Change, both:
  - **formal proof** of `pu_cmp_seg` against a plain per-lane `<` / `==` for all four widths, signed and unsigned
    (SymbiYosys is in the OSS CAD Suite; the problem is small);
  - random operands built to share a prefix: for every lane and every byte position k, operands equal above byte k
    and different at byte k; plus the cases of F19.

### F21. Nothing checks the synthesized netlist — **must-fix**
- The area and timing come from the netlist, after an open-source SystemVerilog front end (sv2v or slang) that is the
  least proven link in the flow.
- Change: run the random and replay tests on the **post-synthesis netlist** with the Nangate cell models, for all
  three configurations, or prove RTL = netlist with Yosys `equiv`. Add `verilator --lint-only`, a check for inferred
  latches, and `check -assert` in Yosys.

### F22. The reference model shares the plan's reading — **should-fix**
- `pu_ref.py` is written from section 4 by the same author, on 256-bit words. A wrong lane or slot rule would be
  wrong in both.
- Change: make the reference **per record**, like `bare.bitmap` (arrays of records in, mask of records out), and let
  the testbench pack records into words with the packer of F4. Then the word, lane and slot mapping is checked
  against an independent form. Keep the real-data replay as the anchor to DuckDB.

### F23. Coverage gaps of the real-data replay — **should-fix**
State them and cover each elsewhere:
- every real plan has `invert = 0`; all real columns are signed, 8 or 16 b; no 32 / 64 b filter; no `lo > hi`;
- add Q12 look-ahead (the only real use of OR) to the replay;
- add `pu_channel` tests: 16 banks with different data, PRD bank order, bank-to-record mapping;
- hazard sequences by name: `PLD j; PCC j; PLD j+1`; `PCMP; PRD`; `PCMP; PMC`; `PWGB; PCMP`; M, M1, V held across a
  row switch (NOP slots with random `x`);
- run the filter tests on `HAS_JOIN = 0`, and the full set on each configuration and each `HAS_XREG`;
- compare state with the fixed two-slot lag of F3, and say so;
- Icarus (4-state) for X-propagation from un-reset registers; Verilator alone hides it.

---

## 5. Synthesis method

### F24. "Meets 2.284 ns in Nangate45" proves nothing — **must-fix**
- Nangate45 is a logic process, 2-3 or more times faster than DRAM periphery (notes/22 uses 90-150 ps per gate
  level; UPMEM says about 3x slower [recalled]). Any PU meets 2.284 ns there.
- Change:
  - report the critical path as **logic depth and FO4 delays** (measure the library's FO4 with the same STA run);
  - convert with a stated DRAM FO4 range, the same 90-150 ps per level of notes/22 3.6, and show pass / fail per
    value, including the "split stage 2" fallback;
  - synthesize at two targets: relaxed (smallest area) and the **scaled period** `2.284 ns / k`, k = 2 and 3. Drop the
    arbitrary 1.0 ns. Add a period sweep to find the minimum;
  - report area at both targets (area grows with a tight target).

### F25. Cell area is not die area — **must-fix**
- `stat -liberty` gives the sum of cell areas: no routing, no utilization, and DRAM periphery has about 3 metal
  layers. notes/22 8.3 already says the set-select figure "leaves out wiring" and "is a lower bound".
- Change, either:
  - place and route `pu` (all three configurations) in OpenROAD with Nangate45 **limited to 3 routing layers**, and
    report the core area at the utilization that routes; or
  - at least apply a stated utilization (for example 50-70 %) and label set-select as cells only.
  The first is much stronger, and OpenROAD-flow-scripts is already the plan's source for the library.

### F26. How to convert to the DRAM process — **should-fix**
- Convert **gate-equivalents x µm² per gate-equivalent** (the 1 / 2 / 4.4 µm² range of notes/22 8.3), not
  "Nangate µm² x a factor". Gate-equivalent = cell area / NAND2_X1 area (0.798 µm² [recalled]). Give low / central /
  high, as AREA.md does.
- Add at least one outside check: per-bank logic area of a published DRAM-PIM chip (AiM ISSCC'22, FIMDRAM ISSCC'21;
  AREA.md lists both as "not yet obtained"), and the method the closest papers (Membrane, Darwin) used [recalled:
  check before citing].
- Drop the ASAP7 option: a 7 nm number makes the DRAM conversion harder to defend, not easier.

### F27. Is Yosys + ABC + Nangate45 + OpenSTA acceptable — **should-fix (report list)**
Acceptable for an architecture paper if stated plainly. Open tools give somewhat larger and slower results than
commercial ones, which is the safe direction. Report: tool versions, library and corner, clock targets, flattened or
not, gate-equivalents, cell area, flop / combinational split, critical path (start, end, levels, FO4), utilization,
routing layers. Use a timing-driven ABC script with a constraint file (the OpenROAD-flow-scripts synthesis script is
a good base); plain `abc -liberty -D` sizes poorly.

### F28. Flops at the I/O — **should-fix**
- `pu` synthesized alone: with `HAS_XREG = 1` every path is register to register except `gb -> V / bounds`,
  `M -> m_out`, and control in. Set input delay on `gb` and controls and output delay on `m_out` to stated shares of
  the slot (the 256-bit channel bus is long; suggest half the period each) instead of wrapping extra flops.
- Do not count wrapper flops in the PU area.

### F29. Power — **should-fix**
- Activity from the Q6 / Q19 replay is the right source, but it must come from simulating the **netlist** (VCD or
  SAIF with matching net names), not the RTL.
- Report **energy per command** (PCMP, PCC, PSEL, PMC, PRD), idle power in PIM mode, and power in normal mode (must be
  near zero: F11). Then total for 384 PUs running in lockstep, since that is the peak.
- Nangate45 leakage and voltage do not transfer to a DRAM process. Report dynamic energy, scale by C·V² with stated
  values, and mark leakage as not transferable. No clock tree exists before place and route; say so.

### F30. Die share formula — **nit**
Write it out: `(16 x PU + decoder + buffer) x 4 channels per die / die area`, die 45-75 mm², 64 banks per die
(AREA.md). "Banks per die from the GDDR7 organization" is vaguer than what AREA.md already fixes.

---

## 6. Over-engineered or missing

| # | Item | Severity | Change |
|---|---|---|---|
| F31 | ASAP7 option; fixed 1.0 ns target; "default activity" power run | nit | drop (F24, F26, F29 replace them) |
| F32 | `pu_lane_bcast` as a module | should-fix | remove if F15 is accepted |
| F33 | Normal-mode cost is missing | should-fix | report added load / delay on the read path (F1 mux) and normal-mode power (F11) |
| F34 | Buffer word layout (`lo`, `hi`, `cfg` bit positions) exists only in the plan | nit | copy it into `tpch/NOTES.md` once fixed; it is the host-visible format |
| F35 | Tool install has no version pin | nit | pin the OSS CAD Suite date and the OpenROAD / OpenSTA commit; put them in the report |
| F36 | No comparison row against the hand estimates | nit | final table: notes/22 8.3 estimate next to the synthesized gate-equivalents, per block |
| F37 | Set-select has no alternative costed | nit | its routed area (F25) decides whether it stays; say that the k-pass path needs none of it |

## Must-fix list

F1 (PRD per bank + read mux), F2 (LOAD_BOUNDS = PWGB), F3 (pipeline position of every command), F4 (lane / byte /
record order and the packer), F7 (PSEL geometry), F14 (Global Buffer in the die share), F20 (comparator proof and
directed operands), F21 (netlist check), F24 (timing through FO4 and a scaled period), F25 (routed or derated area).
