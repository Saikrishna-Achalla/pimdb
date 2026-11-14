# PIM hardware landscape for GPU memory

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## PIM hardware landscape for a GPU's memory: parameters, SQL-primitive capability, placement assessment

Files written: `/home/sai/cs254_project/pim_exploration/hardware/pim_parameters.csv` (74 rows) and `/home/sai/cs254_project/pim_exploration/hardware/build_pim_parameters.py`. The script regenerates the CSV with `python3 -I`, and every derived number in it is computed there.

Source limits:
- Most PDFs were read as text: PrIM, Mondrian, SIMDRAM, Ambit, PIMeval, pLUTo, AMMA, Stratum, the AiM slides, AME-PIM and PIM-Potential.
- Not read, so confidence is low or medium: the Samsung ISSCC'21 and ISCA'21 papers, the Fulcrum paper, DRISA, ComputeDRAM, JAFAR, PID-Join, SPID-Join, PIM-tree, Polynesia and Newton. I only saw their abstracts or secondary summaries.
- The CSV "confidence" column reflects this. Cells below are marked **P** (published) or **I** (my inference).

### 1. Key findings

1. **Commercial bank-level PIM cannot run even the first SQL step.**
   - HBM-PIM (Aquabolt-XL) executes only FP16 ADD, MUL, MAD, MAC, MOV, FILL, NOP, JUMP and EXIT. It has no compare, no bitwise operations, no cross-lane reduction and no integers. (P: AME-PIM, CF'26, s2.3; secondary but detailed.)
   - GDDR6-AiM executes only BF16 MAC (16 MACs per bank), an activation-function LUT, EWMUL and copies. (P: SK hynix ASPLOS'23 tutorial.)
   - Neither can produce a predicate bitmap. A filter, compact, gather chain is impossible on today's parts without a redesign. (I)
2. **Bank-level PIM has a bounded gain over a GPU.**
   - HBM-PIM: internal bandwidth is 1229 GB/s against 307 GB/s external, 4×. Peak is 1.2 TFLOPS per 6 GB stack, and I checked that 128 PCUs × 16 lanes × 2 × 300 MHz = 1.23 TFLOPS.
   - AiM: 512 GB/s internal against 32 GB/s external per channel, 16×.
   - AMD's PIM-Potential study (MEMSYS'24) puts the PIM-over-GPU upper bound at 4×, and the best they reach is 2.4–3.2×. Their limiters are row-activation overhead and command bandwidth.
   - The RTX 5070's GDDR7 has no PIM, so everything here is a projection.
3. **Host commands pace PIM, so "no host round trip" does not hold for current parts.**
   - In HBM-PIM's AB-PIM mode, every PIM instruction step is triggered by a host DRAM column command (P).
   - The microkernel can loop (CRF of 32 entries, JUMP up to 255 iterations, no nesting), but the host still issues one command per step.
   - PIM-Potential identifies command bandwidth as a new bottleneck (P).
   - AiM is similar: a controller in the FPGA or controller expands macro-instructions into micro-commands.
   - SIMDRAM's control unit does sequence a stored AAP/AP microprogram without the CPU (P), but it sits in the memory controller, not in the DRAM.
   - UPMEM runs full programs on the DPU, but host launch and sync are costly. One trace shows `dpu_launch` at about 398 µs for 1,274 DPUs (low confidence; poster, single trace).
4. **Base-die logic is the only placement that is flexible and full-stack, but it gets no bandwidth gain.**
   - HBM4 (JESD270-4) is 2048-bit at up to 8 Gb/s, about 2 TB/s per stack, 32 channels (secondary sources).
   - AMMA states that base-die processing "does not increase per-cube bandwidth". It only avoids the GPU SM and L2 path, and it keeps the full DRAM capacity.
   - It is limited by power and thermal budget. AMMA assumes 15 W per cube, which is their assumption and not vendor data.
   - I found no vendor-published compute specification for custom base dies. Customer logic in the base die is stated as expected from HBM4E (2027), from secondary sources only (low confidence).
5. **In-DRAM bulk-bitwise approaches are strong on scans and weak on everything needing data movement.**
   - Ambit does AND/OR/NOT on whole 8 KB rows. An AAP takes 49 ns, and AND is 4 AAPs, so I derive about 42 GB/s per bank. (I, from P parameters.)
   - Ambit reports 44.9× over a Skylake CPU and 32× over a GTX 745 for bulk bitwise throughput, with under 1% area. BitWeaving scans run 1.8–11.8× faster.
   - SIMDRAM adds integer add, subtract, multiply, divide, compare, if-else and bitcount, with 65,536 lanes per bank. At 16 banks it reaches 5.8× a Titan V on average across 16 operations. The GPU wins on multiply and divide.
   - Both need a vertical bit layout. SIMDRAM adds a transposition unit in the memory controller. Neither has floating point.
   - Neither can permute lanes arbitrarily. PIMeval states that radix-sort reshuffling is unsupported and that inter-bank communication goes through the host.
6. **Operators that move data between units are where prior DB-on-PIM work hits its limit.**
   - Mondrian (simulated HMC logic layer): up to 49× over CPU and 5× over a baseline near-memory system. Partitioning improves 273× over CPU. Its key trick is data permutability, which turns random partition writes into streaming writes. Its limiter is SerDes bandwidth (4.5 of 8 GB/s per vault).
   - UPMEM joins (PID-Join, SPID-Join) are limited by skew and host-mediated redistribution. SPID-Join gets up to 10.38× over PID-Join under heavy skew.
   - JAFAR (simulated DDR3 module) gets up to 9× on select only.
   - The supplied PIMDAL paper (not covered here) separately reports that a GPU beats PIM on join queries.
7. **UPMEM is a reference point only.**
   - 350 MHz and 58.56 MOPS INT32 add per DPU. 64 MB MRAM, 64 KB WRAM, no direct DPU-to-DPU communication.
   - About 700 MB/s per DPU peak, 1.6–1.7 TB/s aggregate over 2,556 DPUs.
   - Host transfer is 0.33 GB/s (CPU to DPU) and 0.12 GB/s (DPU to CPU) per DPU, and under 19.2 GB/s per rank.

### 2. Primitive capability matrix

Columns:
- C1: bank-level SIMD (HBM-PIM / AiM).
- C2: HBM base-die logic.
- C3a: in-DRAM bit-serial (Ambit / SIMDRAM).
- C3b: subarray ALU (Fulcrum).
- C4: UPMEM-class core.

Cell entries are verdict plus basis. Y = yes, L = limited, N = no.

| Sub-operator | C1 | C2 | C3a | C3b | C4 |
|---|---|---|---|---|---|
| Predicate scan → bitmap | N, P: no compare (AME-PIM s2.3.4). AiM could threshold via the activation LUT: L, I | Y, I: arbitrary logic | Y, P: compare ops (SIMDRAM), BitWeaving (Ambit) | Y, P: less/eq ops (PIMeval) | Y, P: PrIM SEL |
| Bitmap AND/OR | N, I: ISA lists no bitwise ops | Y, I | Y, P: Ambit native | Y, P: PIMeval and/or/xor | Y, P |
| Stream compaction | N, I: no variable-length output | Y, I: sequential in/out streams | N, I: no lane permutation | L, I: walker shifts by predicate, within a subarray only | L, P: local per DPU, host concatenates (PrIM SEL/UNI) |
| Gather by index | N, I: operand address comes from the command column | Y, I: random access limited by DRAM row cycle | N, I | L, I: column select within subarray | L, I: own 64 MB bank only |
| Scatter | N, I | Y, I | N, I | L, I: within subarray | L, I: own bank only |
| Hash computation | N, I: FP16 only, no int/bitwise | Y, I | L, I: xor/shift cheap, multiply quadratic (P: mul slower than GPU) | Y, I: 32-bit int ALU | L, P: int multiply slow |
| Hash insert/probe, whole-table random access | N, I: banks isolated | L, I: reaches all banks of its own stack only; atomics need logic | N, I | N, I: neighbor-subarray communication only | L, P: PID-Join partitions by hash first, host moves data |
| Group-by, small group count | N for HBM-PIM (P: no cross-lane reduction). L for AiM via MAC with a mask, bf16 only, I | Y, I | L, I: lane-local partials, host reduces | L, P: PIMeval reduction with subarray/bank accumulators or host | Y, P: histogram (PrIM HST), host merge |
| Group-by, large group count | N, I | L, I: hash table must fit base-die SRAM or use DRAM random access | N, I | N, I | L, I: partition then local (Mondrian sort-based, group size about 4 in their model) |
| Radix partition | N, I | Y, I; Mondrian simulates 273× over CPU on a logic layer (P) | N, I | N, P: reshuffle unsupported (PIMeval) | L, P: host-mediated redistribution |
| Sort / merge | N, I | L, I; Mondrian simulates it in logic-layer SIMD (P) | N, I | L, I | L, I: local sort only, host merges |
| Prefix sum | N, I: no cross-lane | Y, I | L, I: shifts via row copy (P: bit-shift cheap in SIMDRAM) | L, P: PIMeval has prefix sum, needs inter-unit step | L, P: PrIM scan needs inter-DPU sync via host |
| Integer / decimal multiply | N, I: FP16 only | Y, I | L, P: SIMDRAM multiply is quadratic, slower than GPU | Y, P: 32-bit int ALU | L, P: add 58.56 MOPS, multiply/divide much slower |
| Floating point | L, P: FP16/BF16 only, no FP32/64 | Y, I | N, P: SIMDRAM has no FP | N, P: integer ALU | L, P: emulated, slow |
| String compare / LIKE | N, I | L, I: fixed-width compare; variable length needs pointer chasing | L, I: fixed-width equality, no LIKE | L, I | Y, I: general core; slow variable-length handling |

### 3. Assessment (inference)

For a GPU with HBM:

- **Bank-level unit (HBM-PIM / AiM class, as shipped):** it cannot run filter → compact → gather or group-by → sort.
  - Main obstacle: the ISA has no compare, bitwise or integer operations, no cross-bank movement and no data-dependent addressing.
  - Even if those were added, the host still issues one command per PIM step (P). The 4× or 16× internal bandwidth would need extra commands, with command bandwidth as a bottleneck.
  - Still unmeasured: how much per-step host command traffic a chained filter, compact, gather would need. The CSV "chaining" rows only record the mechanism.
  - A redesigned bank unit with compare and predicate-output instructions could plausibly do the filter step alone, since scans are bandwidth-bound and Ambit and SIMDRAM show scans map well. Compaction and gather still fail.
- **Base-die logic:** it could plausibly run filter → compact → gather, because it needs only sequential streams plus random reads within its own stack. It could also run group-by → sort (Mondrian-style partition then sort) within a stack.
  - Main obstacle 1: it gets no bandwidth gain. Its ceiling is the stack's external interface (about 2 TB/s for HBM4). The benefits are avoiding SM and L2 traffic and kernel launches, plus capacity kept intact. This only helps if the GPU kernels are not already near that ceiling, which the owner's Q1 study has not shown.
  - Main obstacle 2: the GPU interleaves cache lines across channels and stacks, so one base die sees fragments of a column and cannot see a whole table. (I)
  - Main obstacle 3: power and thermal budget. AMMA assumes about 15 W per cube, but there is no vendor spec.
  - Main obstacle 4: coherence with GPU L2 and a command path from the SMs. I found no published design for it.
- **What would falsify this:** a vendor or paper showing a base-die command queue with a per-stack address map, or measurements showing the Sirius kernels are far below HBM peak, which would make the interface ceiling irrelevant.

### 4. Could not determine

- Primary text of the Samsung ISSCC'21 and ISCA'21 papers, so area and power overhead are not published in what I read.
- The Fulcrum paper itself. Its clock appears as 164 MHz and as 167 MHz in different PIMeval text.
- Per-operator numbers for PID-Join and JAFAR. I also did not verify the DRISA numbers.
- Any published measurement of host-side command latency for HBM-PIM. The only launch-overhead number I found is the UPMEM trace above.
- Any published design that runs a database operator chain on HBM base-die logic. AMMA and similar proposals are LLM attention.

### 5. What I would measure next

- Count the PIM commands a filter → compact → gather chain would need on a PIM-Potential-style model, and compare to the Sirius kernel count per operator.
- Check how much of the per-kernel time in the Sirius traces sits below HBM-class bandwidth, to size the base-die benefit.
- Obtain the Fulcrum and Samsung primary papers to fix the low-confidence rows.

### Files written
- `/home/sai/cs254_project/pim_exploration/hardware/pim_parameters.csv`
- `/home/sai/cs254_project/pim_exploration/hardware/build_pim_parameters.py`
