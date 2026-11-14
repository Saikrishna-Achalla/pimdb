#!/usr/bin/env python3
"""Builds pim_parameters.csv. Run: python3 -I build_pim_parameters.py  (writes next to this script).
Derived values are computed here so they are reproducible; 'derived' rows say from what."""
import csv, os

# ---- derived numbers (all inputs are published parameters listed in the rows below) ----
hbm_pcus = 4 * 4 * 8                     # 4 PIM dies x 4 pseudo-ch x 8 PCU/pc (AME-PIM CF'26 s2.1)
hbm_peak_tflops = hbm_pcus * 16 * 2 * 300e6 / 1e12      # 16 lanes, FMA=2 flop, 300 MHz
hbm_int_bw = hbm_pcus * 32 * 300e6 / 1e9                # 32 B (256 b) per PCU per 300 MHz step
aim_ch_int_bw = 16 * 32 * 1e9 / 1e9                     # 16 banks x 32 B x 1 GHz
aim_chip_tflops = 2 * 16 * 16 * 2 * 1e9 / 1e12          # 2 ch x 16 banks x 16 MAC x 2 flop x 1 GHz
ambit_and_ns = 4 * 49                                    # AND = 4 AAP, AAP=49 ns (DDR3-1600, optimized)
ambit_and_gbs_bank = 8192 / ambit_and_ns                 # 8 KB row result per op, bytes/ns = GB/s
upmem_mram_bw_total = 2556 * 700e6 / 1e12               # TB/s
upmem_dpu_per_gb = 1024 / 64
hbm4_bw = 2048 * 8 / 8 / 1000                            # TB/s

H = ["class", "device_or_paper", "parameter", "value", "unit", "conditions", "source", "confidence"]
R = []
def add(*r): assert len(r) == 8, r; R.append(r)

# ===== Class 1: bank-level PIM in commodity HBM/GDDR =====
S_AME = "AME-PIM: Can Memory be Your Next Tensor Accelerator? (CF 2026), s2.1-2.3 (secondary description of Aquabolt-XL)"
S_ISSCC21 = "Kwon et al., A 20nm 6GB Function-In-Memory DRAM ... 1.2TFLOPS PCU, ISSCC 2021 (via press/secondary summaries, paper not read)"
S_ISCA21 = "Lee et al., HW Architecture and SW Stack for PIM Based on Commercial DRAM Technology, ISCA 2021 (abstract only read, via aminer/semiengineering)"
S_AMD = "Alsop et al. (AMD), PIM-Potential, MEMSYS 2024, Table 1 + s4.4 (secondary)"
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "PIM units (PCU) sharing", "1 per even/odd bank pair", "-", "PCU can access one of the two banks at a time", S_AME, "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "PCUs per pseudo-channel / per PIM die", "8 / 32", "units", "PIM die = 4 pseudo-channels x 16 banks", S_AME + "; ISSCC21 summary says 32 PCUs/die", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "PCUs per 6 GB stack", hbm_pcus, "units", "4 PIM dies (4Gb each) + 4 plain 8Gb dies; derived 4 dies x 32", "derived from " + S_AME, "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "capacity penalty", "PIM die has half the capacity of an 8Gb HBM2 die (4Gb); stack 6GB vs 8GB", "-", "", "ISSCC 2021 summaries (Tom's Hardware, HPCwire)", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "datapath", "16-lane FP16 SIMD, mult+add per lane, 5-stage pipeline", "-", "FP16 only", S_AME, "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "PIM clock", "250-300", "MHz", "same as DRAM core clock", S_AME + "; ISSCC21: 300 MHz", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "native operations", "ADD, MUL, MAD, MAC (FP16); MOV, FILL (optional ReLU on move); NOP, JUMP, EXIT", "-", "no compare, no bitwise, no cross-lane reduction, no int, no data-type widening", S_AME + " s2.3.1-2.3.4", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "microkernel storage", "CRF 32 entries x 32-bit instr; GRF 16x256-bit (A/B per even/odd bank); SRF 2x8 scalar regs", "-", "JUMP: no nesting, max 255 iterations", S_AME + " s2.1,2.3.3", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "peak FP16 throughput per stack", round(hbm_peak_tflops, 2), "TFLOPS", "derived 128 PCU x 16 lanes x 2 x 300 MHz; matches published 1.2 TFLOPS", "derived; ISSCC21 summaries say 1.2 TFLOPS", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "internal (PIM data) bandwidth per stack", 1229, "GB/s", f"AMD table value; derived check 128 PCU x 32 B x 300 MHz = {hbm_int_bw:.0f} GB/s", S_AMD, "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "external bandwidth per stack", 307, "GB/s", "HBM2 Aquabolt; internal/external = 4x", S_AMD, "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "host command interface", "standard DRAM ACT/RD/WR; modes SB / AB / AB-PIM selected by command sequences to a reserved config region; in AB-PIM each column command (host-issued) advances the PIM program counter in lock step across all PCUs of a pseudo-channel", "-", "unmodified JEDEC controller", S_AME + " s2.2", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "command granularity", "1 column command = 1 PIM instruction step on 256 bit per bank per PCU (all banks of the pseudo-channel in lock step)", "-", "host (or FPGA) must issue one command per step, so PIM execution is paced by host command bandwidth", S_AME + "; " + S_AMD + " s4.4 (command bandwidth bottleneck)", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "inter-unit communication", "none between banks/PCUs; broadcast of one bank to all GRFs of a pseudo-channel only", "-", "", S_AME + " s2.3.2", "medium")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "published speedup", "11.2x (memory-bound NN kernels), 3.5x (applications); 3.5x energy/bit, 3.2x system energy", "x", "unmodified commercial processor, ML workloads only", S_ISCA21, "low")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "published system result (Alveo)", "~2.5x performance, >60% less energy (RNN-T speech)", "x", "vendor claim, Hot Chips 33 2021; computer vision ~10% gain", "IEEE Spectrum / BusinessWire Aug 2021 (press)", "low")
add("1 bank-level", "Samsung HBM-PIM / Aquabolt-XL", "area / power overhead", "not published in sources read (half-capacity PIM die is the observable cost)", "-", "", "-", "low")
S_AIM1 = "Kwon & Park (SK hynix), System Architecture and SW Stack for GDDR6-AiM, ASPLOS 2023 PIM tutorial slides (cites Lee et al. ISSCC 2022)"
S_AIM2 = "Kim et al. (SK hynix), AI-Specific Computing Memory Solution: AiM to AiMX, Hot Chips 2024, slide 5"
add("1 bank-level", "SK hynix GDDR6-AiM", "banks / MAC units", "16 banks per channel, one PU per bank, each PU = 16 BF16 MACs (one 32 B column access); 2 channels per chip", "-", "", S_AIM1 + "; " + S_AIM2, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "clock", 1, "GHz", "", S_AIM1 + "; " + S_AIM2, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "peak compute", f"{aim_chip_tflops:.2f} per chip (1 published: 1 TFLOPS/chip; 512 GFLOPS per channel)", "TFLOPS", "BF16; HC24 lists '512 GFLOPS per die' (die=channel pair ambiguity)", S_AIM1 + "; " + S_AIM2, "medium")
add("1 bank-level", "SK hynix GDDR6-AiM", "internal bandwidth", f"{aim_ch_int_bw:.0f} per channel (published 512); ~1 TB/s per chip", "GB/s", "all-bank MAC; 16 banks x 32 B x 1 GHz", S_AIM2, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "external bandwidth", "32 per channel; 64 per chip (16 Gb/s/pin)", "GB/s", "ratio internal/external = 16x", S_AIM1 + "; " + S_AIM2, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "native operations", "MAC (matrix-vector, weights from bank, vector from 2 KB global buffer), activation function by LUT interpolation (AF), EWMUL, bank<->global-buffer copy, RDMAC/WRMAC", "-", "BF16 only", S_AIM1, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "command interface", "new DRAM-level commands MACSB/MAC4B/MACAB (1/4/16 banks), activate 4/16 banks, EWMUL, copy, RDMAC/WRMAC (mode-register gated); a controller (FPGA in AiMX) expands host macro-instructions into micro-commands", "-", "", S_AIM1, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "supply / process", "1.25 V, 1ynm, 8 Gb die, 16 Gb/s/pin", "-", "", "ISSCC 2022 title via " + S_AIM1, "high")
add("1 bank-level", "SK hynix GDDR6-AiM", "published speedup", "up to 16x vs CPU/GPU on specific ML ops, -80% power (vendor claim)", "x", "preliminary", "SK hynix press release Feb 2022 via Tom's Hardware / Blocks&Files", "low")
add("1 bank-level", "SK hynix GDDR6-AiM", "inter-unit communication", "none between banks; results gathered via RDMAC and global buffer", "-", "", S_AIM1, "medium")
add("1 bank-level", "Newton (SK hynix HBM2E-like AiM)", "published speedup", "10x vs non-PIM with infinite compute, 54x vs realistic GPU (ML, GEMV)", "x", "simulated", "He et al., Newton, MICRO 2020 (abstract via search)", "medium")
add("1 bank-level", "AMD PIM-Potential (HBM-PIM-like strawman vs GPU)", "bound on PIM-over-GPU speedup", "4x upper bound (=internal/external BW); achieved 2.68x/3.17x/2.43x (sci/ML/graph) after proposed optimizations; avg 1.12x -> 2.49x", "x", "baseline = MI250 GPU, tightly-coupled bank PIM; command bandwidth & row activation are limiters", S_AMD + " abstract", "medium")

# ===== Class 2: HBM base-die logic =====
add("2 base-die", "JEDEC HBM4 (JESD270-4)", "interface", "2048-bit, up to 8 Gb/s/pin, 32 channels (2 pseudo-ch each), 4/8/12/16-high, 24/32 Gb dies", "-", "April 2025", "JEDEC JESD270-4 press release via Tom's Hardware / EE News Europe (secondary)", "medium")
add("2 base-die", "JEDEC HBM4 (JESD270-4)", "external bandwidth per stack", hbm4_bw, "TB/s", "2048 b x 8 Gb/s / 8", "derived from above", "medium")
add("2 base-die", "HBM4 vendors", "base-die process", "Samsung: 4 nm in-house logic base die; SK hynix and Micron: TSMC logic nodes (12 nm-class cited for SK hynix; <=5 nm in AMMA)", "-", "sources disagree on node", "Utmel blog; Medium; AMMA arXiv 2604.26103 s2.B", "low")
add("2 base-die", "Custom HBM (cHBM)", "customer logic in base die", "customer-specific logic on base die expected broadly from HBM4E (2027); stated uses: pre-processing, custom I/O, power mgmt; no vendor-published compute spec found", "-", "", "TrendForce via secondary blogs", "low")
add("2 base-die", "HBM base die (general)", "internal vs external bandwidth", "Base-die logic sits behind the same TSV interface the PHY uses, so per-stack bandwidth available to it equals the external interface (PNM 'does not increase per-cube bandwidth'); bank-level PIM exposes the larger array bandwidth", "-", "authors' statement/inference", "AMMA (arXiv 2604.26103) s2.B; Stratum (arXiv 2510.05245) motivation", "medium")
add("2 base-die", "AMMA (proposal)", "logic-die budget assumed", "15 W per cube (30 W 'EC' variant); HBM4 cube+PHY 75 W; 121 mm2 logic die; D2D UCIe 1.5 TB/s", "W", "design assumptions, not vendor data", "AMMA arXiv 2604.26103 Table (parameters) and area/power breakdown", "low")
add("2 base-die", "Stratum (proposal)", "TSV limit", "TSV area and ~10 um pitch limit HBM internal bandwidth; base-die NMP limited by vertical TSV traffic", "-", "motivates monolithic 3D DRAM", "Stratum arXiv 2510.05245 s1/s2", "medium")
add("2 base-die", "Mondrian (HMC logic layer, simulated)", "per-vault budget", "8 GB/s per vault, 4.4 mm2, 312 mW logic budget; 32 B..256 B messages", "-", "HMC, 20 nm; ARM A35-class core + 1024-bit SIMD = 0.65 mm2 / 90 mW", "Drumond et al., Mondrian Data Engine, ISCA 2017, s3.2, s4, Table 3-4", "high")

# ===== Class 3: in-DRAM bulk-bitwise / subarray =====
add("3 in-DRAM", "Ambit", "native operations", "bulk AND/OR (triple-row activation), NOT (dual-contact cell), copy (RowClone); XOR/NAND composed", "-", "operands must be in the same subarray; row-wide (8 KB)", "Seshadri et al., Ambit, arXiv 1905.09822 (journal version of MICRO'17), s3-4", "high")
add("3 in-DRAM", "Ambit", "AAP latency", "49 (optimized) / 80 (naive)", "ns", "DDR3-1600; AND = 4 AAP", "Ambit s4.3", "high")
add("3 in-DRAM", "Ambit", "AND throughput per bank", f"{ambit_and_gbs_bank:.1f}", "GB/s", f"derived: 8 KB / (4 x 49 ns)={ambit_and_ns} ns", "derived from Ambit s4", "medium")
add("3 in-DRAM", "Ambit", "throughput vs baselines (bulk bitwise)", "44.9x Skylake, 32.0x GTX 745, 2.4x HMC 2.0 (8 banks); Ambit-3D 9.7x over HMC 2.0", "x", "bandwidth-bound baselines", "Ambit s8 (throughput)", "high")
add("3 in-DRAM", "Ambit", "area overhead", "<1", "% of DRAM chip", "", "Ambit s6/s10", "high")
add("3 in-DRAM", "Ambit", "database result", "BitWeaving column scan 1.8x-11.8x (avg 7.0x) vs SIMD CPU", "x", "needs vertical bit layout", "Ambit s8.2", "high")
add("3 in-DRAM", "SIMDRAM", "SIMD lanes", "65,536 per bank (8 KB row = 1 lane per bit-column); 16 banks -> 1,048,576", "lanes", "vertical data layout; per-bank parallel", "Hajinazar et al., SIMDRAM, ASPLOS 2021, s7", "high")
add("3 in-DRAM", "SIMDRAM", "operations", "16 ops: AND/OR/XOR-reduce, equality, greater/greater-equal, max/min, add, sub, mul, div, if-then-else (predication), bitcount, ReLU; 8/16/32/64-bit ints", "-", "no floating point; latency linear (add), logarithmic or quadratic (mul/div) in bit width", "SIMDRAM s6, s9 limitations", "high")
add("3 in-DRAM", "SIMDRAM", "throughput", "16 banks: 88x CPU, 5.8x Titan V GPU (avg over 16 ops); apps 21x CPU, 2.1x GPU; CPU/GPU win only for mul and div", "x", "GPU = Titan V HBM; DDR4-2400 1 channel", "SIMDRAM abstract, s7", "high")
add("3 in-DRAM", "SIMDRAM", "area / extras", "0.2% of high-end CPU die; needs memory-controller control unit + data transposition unit (horizontal<->vertical)", "-", "transposition-unit latency overhead reported in s7.8 (see paper)", "SIMDRAM s5, s7.8", "high")
add("3 in-DRAM", "SIMDRAM", "inter-lane communication", "only via row-copy shifts (vertical layout makes bit-shift cheap); no arbitrary lane permutation, no cross-column reduction except AND/OR/XOR across inputs", "-", "", "SIMDRAM s3-4, s5.6", "medium")
add("3 in-DRAM", "pLUTo", "operation / results", "LUT query by row sweeping; 713x CPU, 1.2x GPU avg over 11 workloads; area overhead 10.2%-23.1% (3 variants)", "x / %", "", "Ferreira et al., pLUTo, arXiv 2104.07699 abstract", "high")
add("3 in-DRAM", "DRISA", "area overhead", ">=77% over standard DRAM (patent characterization)", "%", "3T1C NOR variant; secondary", "USPTO 11669302 text via search; DRISA MICRO 2017 not read", "low")
add("3 in-DRAM", "ComputeDRAM", "operations", "not verified from a primary source (in-memory compute on off-the-shelf DDR3 chips via violated timing)", "-", "", "title only: Gao et al., MICRO 2019", "low")
add("3 in-DRAM", "Fulcrum (via PIMeval model)", "organization", "32-bit integer ALU at ~164-167 MHz shared by two subarrays, three 8192-bit walkers, controller steps column select by value/predicate; no FP", "-", "1,024 rows x 8,192 cols per subarray, 32 subarrays/bank in the model", "Siddique et al., PIMeval/PIMbench, IISWC 2024 s4 + Table II (secondary for Fulcrum; Lenjani et al. HPCA 2020 not read)", "medium")
add("3 in-DRAM", "Fulcrum / bank-level / bit-serial (PIMeval)", "filter-by-key & radix sort", "Fulcrum beats CPU on filter-by-key only if data-movement latency excluded; radix sort: reshuffling unsupported, only counting phase in PIM", "-", "32 GB DDR4 model vs EPYC 9124 and A100", "PIMeval s6 (Filter-By-Key, Radix Sort paragraphs)", "high")
add("3 in-DRAM", "PIMeval bank-level model", "inter-bank communication", "banks cannot communicate; any inter-bank step goes through the host", "-", "128-bit GDL, 64-bit Fulcrum-style ALPU per bank", "PIMeval s4, Table II", "high")

# ===== Class 4: UPMEM =====
S_PRIM = "Gomez-Luna et al., Benchmarking a New Paradigm (PrIM), arXiv 2105.03814 (IEEE Access 2022)"
add("4 general core", "UPMEM DPU", "clock / pipeline", "350 MHz (2,556-DPU system), 267 MHz (640-DPU); in-order pipeline saturates at >=11 tasklets", "MHz", "in-order, fine-grained multithreading", S_PRIM + " s2, s3.1", "high")
add("4 general core", "UPMEM DPU", "memory per DPU", "MRAM 64 MB, WRAM 64 KB, IRAM 24 KB (4,096 instr)", "-", f"= {upmem_dpu_per_gb:.0f} DPUs per GB", S_PRIM + " s2.2", "high")
add("4 general core", "UPMEM DPU", "INT32 add throughput", 58.56, "MOPS/DPU", "streaming loop; INT64 add 50.16; mul/div and FP much slower (no HW multiplier/FPU)", S_PRIM + " s3.1.2 Key Obs. 1-3", "high")
add("4 general core", "UPMEM DPU", "MRAM->WRAM bandwidth per DPU", "700 peak (534 at 267 MHz); ~622 sustained streaming", "MB/s", f"aggregate 2,556 DPUs: {upmem_mram_bw_total:.2f} TB/s peak, 1.6 TB/s sustained", S_PRIM + " s2.2, s3.2", "high")
add("4 general core", "UPMEM system", "host transfers", "CPU-DPU 0.33 GB/s, DPU-CPU 0.12 GB/s per DPU (32 MB); broadcast up to 16.88 GB/s; < 19.2 GB/s per rank", "GB/s", "", S_PRIM + " s3.4 Key Obs. 7-8", "high")
add("4 general core", "UPMEM system", "inter-DPU communication", "none direct; all via host CPU", "-", "BFS, NW and scan-type kernels pay this", S_PRIM + " s1, s2", "high")
add("4 general core", "UPMEM system", "launch / sync overhead", "dpu_launch ~398 us in one 1,274-DPU trace; setup/allocation dominates (>99% of PIM latency per poster)", "us", "single trace, not a controlled study", "Friesel, CCMCC 2025 poster (via search snippet)", "low")
add("4 general core", "UPMEM", "PrIM vs CPU/GPU", "13 benchmarks 93.0x (2,556 DPU) and 27.9x (640 DPU) over CPU; faster than GPU by 2.54x for 10 streaming benchmarks without inter-DPU sync", "x", "", S_PRIM + " abstract/s1", "high")

# ===== Prior DB-on-PIM work =====
add("DB on PIM", "JAFAR (DRAM-module select accelerator)", "speedup", "up to 9x select operator", "x", "simulated DDR3 module, column-store select; CPU baseline; limit: only select (no other operators)", "Xi et al., Beyond the Wall: NDP for Databases, DaMoN 2015 (abstract via search)", "medium")
add("DB on PIM", "Mondrian Data Engine", "operators / speedup", "scan, group-by, join, sort; up to 49x perf & 28x efficiency vs CPU-centric, 5x / 5x vs baseline NMP; partitioning 273x vs CPU", "x", "HMC-based simulation (Flexus); limiter on CPU: random access; on NMP: SerDes link (4.5 GB/s/vault vs 8 peak); key trick = data permutability to make partition writes sequential", "Drumond et al., ISCA 2017, s6 (Table 5), abstract", "high")
add("DB on PIM", "Polynesia (HTAP, PIM analytics islands)", "speedup", "analytical throughput 3.74x mean over 3 HTAP systems; transactional 1.70x; -48% energy", "x", "simulated 3D-stacked PIM, HTAP; limiter: update propagation/consistency", "Boroumand et al., ICDE 2022 / arXiv 2103.00798 (2021 abstract numbers)", "medium")
add("DB on PIM", "PID-Join (UPMEM)", "operators / speedup", "hash/sort-merge/nested-loop join on 8 DIMMs (1,024 DPUs); 'greatly outperforms' CPU joins (number not retrieved)", "x", "limiter: skew and inter-DPU redistribution via host", "Lim et al., SIGMOD 2023 (abstract via search)", "low")
add("DB on PIM", "SPID-Join (UPMEM)", "speedup", "up to 10.38x over PID-Join under heavy skew", "x", "replicates join keys across banks/ranks; limiter: skew", "SIGMOD 2024 (abstract via search)", "medium")
add("DB on PIM", "PIM-tree (UPMEM)", "speedup", "59.1x / 69.7x throughput over best two prior PIM indexes", "x", "2,048 PIM nodes, 500M keys, batches of 1M; ordered index not SQL operator; limiter: skew / CPU-PIM traffic", "Kang et al., PVLDB 16(4) 2022 (abstract via search)", "medium")
add("DB on PIM", "Pattnaik et al. PIM-enabled GPU", "speedup", "+25% / +42% perf (two scheduling schemes), +28% / +27% energy efficiency over 25 GPU apps", "%", "GPU + logic-layer cores of 3D-stacked memory, kernel-offload scheduling; not DB-specific", "PACT 2016 (abstract via search)", "medium")
add("DB on PIM", "Kepe et al. Database PIM study", "scope", "hash join and sort-merge join on PIM simulation incl. HBM; PIM best on energy", "-", "no GPU", "Database Processing-in-Memory: An Experimental Study (VLDB 2019, via search snippet)", "low")

# ===== Chaining / host overhead =====
add("chaining", "HBM-PIM microkernel", "multi-step in-memory chain", "up to 32 instructions in CRF, zero-cycle JUMP up to 255 iterations; but every step is triggered by a host column command", "-", "so no host-free chaining; sequencing is host-paced", S_AME + " s2.3.3", "medium")
add("chaining", "SIMDRAM control unit", "uProgram sequencing", "one bbop instruction expands to a stored AAP/AP sequence (uProgram sizes are bytes-scale, s5.3); control unit loops over elements without CPU", "-", "control unit is in the memory controller, not in DRAM", "SIMDRAM s5.1-5.3", "high")
add("chaining", "PIM command bandwidth", "bottleneck", "all PIM commands use the command bus; push-style in-place update becomes command-bound; modeling 4x command bandwidth relieves it", "-", "", S_AMD + " s4.4", "medium")
add("chaining", "AESPA (MICRO 2023)", "asynchronous per-bank commands", "33.5% and 59.5% over two synchronous PIM designs", "%", "hides activation latency; abstract only", "AESPA abstract via aminer", "low")

if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pim_parameters.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(H); w.writerows(R)
    print(len(R), "rows ->", out)
