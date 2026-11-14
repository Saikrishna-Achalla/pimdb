# Independent review of the findings report

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

VERDICT: sound with corrections. The simulated chain and operator numbers reproduce exactly. Two problems are serious. First, the coverage and tier analysis uses Nsight Compute (ncu) time but labels it as nsys real-clock time. Second, several bottom-line statements claim more than the evidence supports: the sequencer requirement, the SF1-vs-SF10 idle share, the cause of the Q1 baseline gap, and "PIM gain = bandwidth gain".

I checked about 200 numbers, including table cells and derived ratios. 6 are wrong or on the wrong basis. About 12 I could only trace to a note, not to a data file (listed at the end). Scratch scripts are in /home/sai/cs254_project/pim_exploration/review/ (cov_realclock.py, e2e.txt).

FINDINGS (most severe first)

1. WRONG (time basis and label). §1.4, §3.4, §6.3, §7.4: "20.5 % of the kernel time", "at most 1.05×", "one sort kernel family alone is 28 %", "Excluding it ... 1.02×".
   - Evidence: coverage.py and tier_shares read launches_all.csv:nsys_dur_ns. That column comes from warm_kernel_list.json, where `dur_ns = gpu__time_duration.sum` from the ncu list passes (tpch_sf1_next/kernel_list.py:58; q2/warm_kernel_summary.txt says "serialized GPU time ... ncu, clocks locked, L2 flushed").
   - Per-query sums match ncu, not nsys. Q6: 973.0 vs ncu 974.9 vs nsys 722.0 µs. Total: 39.64 vs ncu 39.62 vs nsys 27.77 ms (summary_data.json).
   - coverage.py then subtracts this ncu time from the untraced wall time, which BRIEF_COMMON l.73-75 forbids.
   - I re-weighted with real-clock nsys per (query, function) from nsys_iteration_breakdown.json. Results: E 21.4 %, N 75.4 %, B 3.3 %; wall bound 1.038×; without the AST kernel 1.012×; AST share of E 68 %; block-sort family 31 %; total kernel time 27.8 ms.
   - Replace: "...it can execute about 21 % of the kernel time (ncu-serialized basis 20.5 %); even an infinitely fast unit would improve summed SF1 wall time by at most about 1.04× (kernel time only; host gaps not included)."
   - Also relabel the tier_shares.png row "Real-clock kernel time (nsys)" and the coverage_by_query.png y-axis and footnote as "ncu serialized kernel time".
   - The brief itself (BRIEF_COMMON l.46) mislabels warm_kernel_list.json as nsys; fix it there too.

2. WRONG CAUSE. §6.2: "The Q1 baseline runs at 17.7× its own floor: the simulator issues about 0.8 warp-instructions per cycle..."
   - Evidence: vortex chains_totals.csv, Q1 S1 SF0.1: 232.5 MB of DRAM traffic in 21.25 ms. That is 78 % of the 14 GB/s, or 387 B/row against a 28 B/row floor.
   - So the chain is bandwidth-bound on full-width intermediates, and caches are flushed at every launch (note 10 §8 says so). Issue rate is not the main cause.
   - Replace: "The Q1 baseline runs at 17.7× its own floor (28 B/row) mainly because its 42 kernels write and re-read full-width intermediates (387 B/row of DRAM traffic at 78 % of bandwidth), with caches emptied at every launch. Launch cost (385 µs of the 21.2 ms at S1) and string gathers (26 %) add to this; issue rate (0.8 vs 4 warp-instructions per cycle) matters for the latency-bound group-by."

3. OVERCLAIM. §1.2 "This needs an in-memory sequencer, which no shipping PIM part has"; §7.2 "it is also what makes host command pacing irrelevant".
   - Evidence: aim_pim/results/chains.csv, tile rows. t_hostpaced_post_us equals time_us (Q6 385.586, Q1 2344.596). The host-paced, tile-ordered schedule (11,732 / 199,470 commands) is as fast as the sequencer when commands are posted. Only under the 300 ns synchronous model does it become 10× / 26.5× slower.
   - Replace: "This needs commands issued in tile order: either an in-memory sequencer, or a host that can stream ~12k (Q6) / ~200k (Q1) commands per channel per SF1 as posted writes. If each command must wait a round trip, only the sequencer works. (HBM-PIM's instruction buffer still advances one step per host DRAM command.)"

4. WRONG BASIS. §1.5 "idle 89 % ... shrinks to 20–50 % at SF10" and the H2 row "GPU active 11 % of wall at SF1; 50–80 % at SF10".
   - Evidence: the 11 % uses the nsys-traced wall (260.6 ms summed, wall_decomposition_table.csv). The SF10 shares use the untraced wall (scaling_table.csv).
   - On the same untraced basis, SF1 busy is 28.72/163.5 = 17.6 % (82 % idle) over Q2–Q22, and 15–47 % for the 8 SF10 queries (sf1_main).
   - Q3 at SF10 is still 71 % idle.
   - Replace: "Untraced, the GPU is idle about 82 % of SF1 wall time (Q2–Q22 summed); for the 8 queries rerun at SF10, busy share rises from 15–47 % to 50–80 % (Q3: 25 → 29 %)."

5. OVERCLAIM. §7.1 "...the scan kernels are bandwidth-bound (SF10 and up on this card)"; H3 "at SF10 the bandwidth-bound kernels are the simple streaming ones (64–81 %)".
   - Evidence: sf1_vs_sf10_bandwidth_table.csv. The ≥64 % kernels are Q18/Q9 gather, unique_copy, reduce_by_key and static_kernel (gather is T3 random access, and the bank unit cannot execute any of them).
   - The bank-executable scan kernel, Q6 AST, runs at 13 % at SF10. AST across queries runs at 3–17 % (8.3 % time-weighted; launches_all ncu_dram_bytes/ncu_dur).
   - Replace H3: "at SF10 the kernels near peak bandwidth (64–81 %) are gathers, unique-copy and reduce-by-key, which bank-level PIM cannot run; the scan/expression kernel PIM can run stays at 13 %."
   - Replace §7.1: "...needs data large enough that the GPU is busy; on the real GPU the scan kernels are latency-bound even at SF10, so part of the gap is closable by a better GPU kernel."

6. OVERCLAIM (a). §1.1 "PIM's gain ... is the internal-versus-external bandwidth gain".
   - Evidence: this holds by construction. (b)/(d) = (bytes ÷ 32 GB/s per channel) ÷ PIM time = achieved input rate ÷ 32. That is 218/32 = 6.8 and 51/32 = 1.6 (aim chains.csv eff_input_bw_GBs).
   - The internal peak is 512 GB/s, so Q6 reaches 43 % of it and Q1 10 %. Q1 is limited by in-bank compute and row capacity (T = 32), not by bandwidth.
   - Replace: "PIM's gain is the input rate the bank unit sustains relative to the 32 GB/s pins: 6.8× on Q6 (43 % of the 16× internal peak), 1.6× on Q1 (compute-bound in the bank)."

7. OVERCLAIM (d). Amdahl table, §6.3.
   - The "replaceable" share counts "removed" kernels (compaction, gathers, string gathers) as PIM gains. §6.2 says a GPU could make the same plan change. For Q1 SF10 that is 10.3 of 44.8 ms summed kernel time (end_to_end.csv amdahl rows); for Q6 SF1, 0.054 of 0.72 ms.
   - The table also applies s = (b)/(d) to real kernels that run far below the floor.
   - The basis column says "saved kernel time assumed on the critical path (upper bound)"; the report omits that.
   - Add to the caption: "upper bounds; the replaceable share includes kernels removed by the masked-aggregate plan, which a GPU plan could also drop."
   - Add the absolute-time column ("replace by projected PIM chain time"): 1.27× / 2.10× / 1.43× / 2.85×. This is higher than the s = (b)/(d) column (see 18).

8. OVERCLAIM and MISSING CAVEAT (i). §6.3 "**14×**".
   - The report says vs-baseline ratios "should not be quoted as the PIM effect", yet it puts 14× in bold.
   - Lead with: "5.0× against the GPU floor plus one launch gap (4.6× with synchronous commands); 14× / 12× against the simulated Sirius-structured baseline."
   - The layout transform is 250 µs, which is 2× the 125 µs GPU floor (normalization.csv; it reads and writes every input byte once). If paid per query, PIM Q6 end-to-end is 26.4 + 250 = 276 µs, against 132 µs for the floor plus one gap (0.48×).
   - Add to §1: "Every PIM gain assumes tables stay in the row-tile layout; converting Q6's columns costs 2× the GPU's whole floor time."

9. WRONG. §3.1 "with the default it launches 873".
   - 873 is measured with the 0.85-pool SF10 configuration (262 MB batches). The Sirius default (no usage limit, 512 MiB batches) is modeled at 6 batches (note 05 §3). The 3,865 is measured, not hypothetical (scaling_table.csv sf10_b77).
   - Replace: "With the SF1 profiling configuration Q1 at SF10 launches 3,865 kernels (measured); with the 0.85-pool configuration used for SF10, 873; with no usage limit the batch model predicts 6 batches."

10. MISSING CAVEAT (c). Coverage classification (coverage_families.csv, coverage.py).
    - The AST kernel is E in every query, but in join queries it runs on gathered join outputs (not row-tile layout). This is the same optimism the code flags only for group-by. Q19's AST (1.71 ms) alone is 21 % of all E.
    - CASE/select inside AST counts as E, while copy_if_else counts as N "select not in ISA". These are inconsistent.
    - IN-list ≤ 8 keys is not checked.
    - Compaction counts as E although with GPU read-out its gain is 1.0× and its output order differs.
    - Q1, the second-best case (77 % replaceable), is outside "Q2–Q22".
    - The bound covers kernel time only. "∞ + chain host gaps removed" gives 1.54× (Q6 SF1) and 3.50× (Q1 SF1, weak).
    - Add one sentence listing these, and say "SF1, untraced summed wall, kernel time only".

11. WRONG LABELS. §6.1, §6.2, §1.1.
    - §6.1: the compaction baseline (407.0 µs) is modeled (interpolated between compact_1/25/49), not simulated. Its "stays in memory" row uses the sequencer variant; host-paced is 39.5 µs, 1.75× vs floor (operators_speedup.csv).
    - §6.2 row (a) is labelled *simulated* but is modeled (S1 × 1/48). The simx launch cost scales to ≈0.2 µs per launch; with 2.5 µs real launches it is 252.4 / 539.6 µs (a_launchfix).
    - Rows (c) and (d) carry no label; they are modeled (simulated 1 channel ÷ 21; the direct 1/21 run agrees within 0.4 %).
    - §1.1 "*simulated* PIM": replace with "PIM simulated on one channel, scaled ÷ 21 (*modeled*)".

12. WRONG. §6.1 "the two speedups agree within 5–25 %".
    - Recomputed for the table's rows: 8.5–11 %. Across all memory-bound rows it is 8.5–29 % (int32 sum 10.5 vs 8.1, at 80 % of bandwidth).
    - Replace: "agree within 8–11 % for these rows (29 % for int32 sum)".

13. MISSING CAVEAT and WRONG. §8 "floors are given at both widths".
    - The report gives only the 20 B/row floor (17.9 µs), yet "17.7× its own floor" uses the 28 B/row floor (25.0 µs).
    - At cuDF widths: (b)/(d) = 2.24×, (b)/(c) = 0.79×. Operator-at-a-time is still slower than the floor, so the 0.57× conclusion holds, and it is computed on the PIM's own 20 B/row.
    - At SF0.1 on the full card, Q1's 12 MB input fits in the 48 MB L2, so a DRAM floor is questionable there. PIM Q1 at SF1 is simulated (111.6 µs at 5070 scale vs a 178.7 µs floor: 1.60×). Quote SF1.
    - Add row (b2) "floor at cuDF widths (28 B/row): 25.0 µs, (b2)/(d) 2.2×, (b2)/(c) 0.79×".

14. MISSING CAVEAT. §6.3 "drop it to 0.32× of the GPU floor".
    - That is at SF0.1. At SF1 the same model gives 1.04× (end_to_end.csv Q1 1.0 sync), because the 197 commands are per query.
    - The 11,732 / 199,470 command counts are per channel at SF1. Say so.

15. MISSING CAVEAT (g). The normalization (B ÷ 32; 0.4375 / 1.75 / 21 channels) is applied consistently to operators, chains and end-to-end; I found no inconsistency.
    - However, it carries GDDR6-AiM's 16:1 internal/external ratio over to a GDDR7 card. GDDR7's higher per-pin rate means fewer banks per GB/s, so this likely favours PIM.
    - Add to §8: "...assumes the 16:1 ratio carries over; for GDDR7 it would likely be lower."

16. OVERCLAIM (f). §1.6 "The chains that carry data are filter → compaction → gather and the scan → filter → aggregate path."
    - chain_candidates.csv, round-trip bytes:
      - dynamic-filter probe → compaction → gather: 189 MB (its head is a hash membership, which the bank unit cannot run);
      - group-by internal: 160 MB;
      - predicate → compaction → gather: 73 MB;
      - expression → aggregate: 40 MB.
    - Replace with these four, in this order.
    - The 2–37,922 groups and 2.2 MB figures are correct.

17. OVERCLAIM. §7.4 "Gather, hash probe and sort are 75 % of SF1 kernel time"; §9.1 "where 75 % of kernel time is".
    - 75 % is all non-executable kernels: it includes strings (about 11 %), joins and scans. Sort alone is 35 % (ncu basis) or 39 % (real-clock), and a base-die gather/hash unit would not cover sort or strings.
    - Replace: "Kernels the bank unit cannot run are 75 % of SF1 kernel time: sort about 35–39 %, hash/membership about 17 %, strings about 11 %, gather about 6 %."

18. UNDERSTATED, PIM-favourable.
    - (i) §4 omits PIMDAL's TPC-H SF40 result: PIM beats an A6000 running cuDF 2.2× on Q1 and 3.3× on Q6 (note 01 l.34).
    - (ii) The GPU floor assumes 100 % of 672 GB/s. The best measured kernel reaches 81 %, the measured stream 637 GB/s, and the PIM side pays 7–9 % refresh. Ratios against the floor are therefore conservative.
    - (iii) Vortex's Q6 (222 µs) is 3.2× faster than real Sirius Q6 (722 µs nsys; note 10's "973 µs nsys" is actually the ncu time).
    - (iv) Amdahl at absolute PIM time is higher than shown (item 7).
    - (v) Vortex's 4 narrow GDDR6 channels give 64 banks per 14 GB/s, more than the real card per unit bandwidth, and the L2 bank serves 64 B/cycle vs the faithful 23.7. Both favour the baseline.
    - Add a bullet to §8.

19. UNCLEAR for the owner.
    - "AST", "row tile", "T", "tile-at-a-time", "Sirius-structured", "omitted launches" and "software-improved baseline" are undefined.
    - AST is T5 ("worst fit") in §3.4 but "executable" in §6.3; explain why.
    - The §6.2 table labels (c)/(d) differently from the plot ("op-at-a-time" / "tile-at-a-time").
    - pim_time_composition.png shows Q1 at SF1 (314.8 / 111.6 µs) while the §6.2 table is Q1 at SF0.1 (31.5 / 11.2 µs); say so in the caption.
    - H1 "smallest cause (14 %)": distinct work (9.8 %) is smaller. Say "smallest repeat cause".

20. CONFIG CHECK (h). The rules are satisfied (configs/S1.json, S4.json):
    - 32 warps × 32 threads, issue 4;
    - 14 / 56 GB/s;
    - L2 at 1/48 and 1/12 (1 MB, 4 MB);
    - L1 128 KB (labelled an inference);
    - L3 off;
    - 13 / 42 separate kernels.

    Calibration: S1 13.80 GB/s = 98.6 %, S4 52.6 GB/s = 93.9 % (16 MB stream; the 4 MB S4 run reached only 84.8 %). Latency 752.7 cycles = 299.6 ns. 115/115 PASS.

    Unstated deviations:
    - 32 warps vs the SM's 48;
    - the rule-3 experiment shows 2 cores at the same DRAM speed up the latency-bound kernels: pred_i16 1.44×, group-by 1.45×, compaction 1.34× (rule3.csv; not applied to the chains, which is defensible);
    - L2 hit bandwidth is 2.7× the scaled value.

PLOTS: all 10 open, and the relative paths resolve (plots/*.png; ../sim/combined/plots/*.png).
- Correct and readable: launch_causes, idle_composition, busy_share, bandwidth, operator_speedups, chain_time_breakdown.
- tier_shares and coverage_by_query: wrong time label (item 1).
- wall_decomposition: its title "busy about a tenth" is on the traced basis (stated in the subtitle). §1.5 drops that qualifier (item 4).
- pim_time_composition: SF1 vs the SF0.1 text (item 19).
- sf1_vs_sf10_bandwidth: its footnote (Q9/Q18 SF10 cover only the first 40 launches) is not mentioned in §3.3.

VERIFIED CORRECT
- §6.1 table: all values except the compaction label (Vortex µs, % bandwidth, PIM µs, both speedups for the 7 rows).
- §6.2 table: every cell, including 12.1 / 39.6 / 6.8 / 1.6 / 2.7 / 0.57 and 17.3.
- 2.5–2.8× (46.2/18.4 = 2.51; 31.5/11.2 = 2.82).
- Row overhead 69 → 37 % and 73 → 38 %; refresh 8 %.
- 6–9 % generality cost (385.6 / 362.9; 12.13 / 11.18). Note the fused command reads 16 B/row vs 14.
- Refresh 7–9 %; 20,865 cycles; direct 1/21 run within 0.4 %; multiply 8-cycle sensitivity 1.78×.
- End to end: 371 = 222 + 141 + 7.5; 319; 26.4 / 29.1; 14.07 / 12.09 / 5.02; 11,732 / 199,470; 10× / 26.5× (report says 27×); 197 / 192; 0.32×.
- Amdahl cells 91/98/77/87 %, 1.23/1.85/1.13/1.34, 1.28/2.17/1.46/3.14.
- Coverage per-query values as computed on the ncu basis: 16.1 %, 75.1 %, 4.4 %, Q6 92, Q19 71, Q16 1, Q2 4, AST 64.7 %, 1.018×.
- Launch causes 9.8/31.5/23.3/21.9/13.6 %; 78 %; 37 %; 1,207; 0.40 per launch; 407.
- Wall decomposition 33/11/52/4 %; idle composition 37/32/16/12 %; 29 %; regression 483 + 18.3 + 1.28, R² 0.971; planning 2.8–5.1 ms (4 sampled queries).
- SF10 busy shares; 2.8 µs per launch; 15 launches per batch; 65×; bandwidth 64–81 %, 13/21/28/25 %, 11–22 %; 67 % unroll.
- Tiers 35 % / 16 % (ncu basis); sort bytes 0.17 %; median 1.34 %.
- Chains 632 MB, 0.72 %, 81 %, 37.9 / 27.8 ms, 350/886, 33.6 µs; 2–37,922 groups, 2.2 MB.
- PIMDAL 0.9× / 0.3×; layout 250 µs.

COULD NOT VERIFY FROM DATA (note only)
- "45–60 %" removable idle (inferred).
- ISA statements for HBM-PIM / AiM; Membrane's 4× power.
- Sequencer state of about 16 entries.
- 300 ns / 1 ns per-command costs (assumptions).
- 6–9 µs simx launch cost and the 0.8 IPC figure (note 10 only).
- "≈ 90 % of 873" per-batch share for Q1 SF10 (inferred from name counts).
- 4,404 vs the fused command's ISR count.
- Which AST launches run on base-table scans vs join outputs (item 10).
