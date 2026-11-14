#!/usr/bin/env python3
"""Applies the 'database PU' source edits to sim/aim_simulator (on top of 0001-owner-db-isrs.patch).
Used once to author sim/patches/aim/0002-db-pu-isrs-refresh.patch; setup_aim.sh applies the .patch file, not this."""
import re, sys, os
S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "aim_simulator", "src")
def edit(path, old, new, count=1):
    p = os.path.join(S, path); t = rd(p)
    if t.count(old) != count:
        sys.exit(f"{path}: expected {count} x {old[:60]!r}, found {t.count(old)}")
    wr(p, t.replace(old, new))
def rd(p):  # sources use CRLF line ends: edit in LF, write back CRLF
    raw = open(p, newline="").read(); assert raw.count("\r\n") == raw.count("\n"), p
    return raw.replace("\r\n", "\n")
def wr(p, t):
    open(p, "w", newline="").write(t.replace("\n", "\r\n"))

NEW = [("PCMP", "CMP16", "compare-class all-bank column read into the PU (range/equality compare -> mask register)"),
       ("PALU", "ALU16", "ALU-class all-bank column read (add/sub/shift/widen/select/sum/compaction source)"),
       ("PMUL", "MUL16", "multiply-class all-bank column read/slot (32x32 partial products; MAC, MUL)"),
       ("PGAG", "GAG16", "group-aggregate-class all-bank column read (key decode + 8 group accumulators)"),
       ("PWB",  "PUWR16", "all-bank internal write of one 256-bit PU result word into the open row")]

# ---------------- request.h ----------------
enum = "".join(f"    ISR_{n}_ABK = {21+i},  // dbpu: {d}\n" for i, (n, c, d) in enumerate(NEW))
edit("base/request.h", "    ISR_RD_MASK = 20,  // Read per-bank predicate masks of [channel_mask] channels to GPR\n    MAX = 21\n",
     "    ISR_RD_MASK = 20,  // Read per-bank predicate masks of [channel_mask] channels to GPR\n" + enum + f"    MAX = {21+len(NEW)}\n")
reg = ""
for n, c, d in NEW:
    reg += f'''
        aim_opcode_to_str[Opcode::ISR_{n}_ABK] = "ISR_{n}_ABK";
        opcode_str_to_aim_ISR["ISR_{n}_ABK"] = AiMISR(Opcode::ISR_{n}_ABK,
                                                      {{AiMISR::Field::opsize,
                                                       AiMISR::Field::channel_mask,
                                                       AiMISR::Field::row_addr}},
                                                      false, false, false, "bank");
'''
edit("base/request.h", '        str_to_type["R"] = Type::Read;\n', reg + '\n        str_to_type["R"] = Type::Read;\n')

# ---------------- aim_DRAM_system.cpp ----------------
edit("memory_system/impl/aim_DRAM_system.cpp", "                    case Opcode::ISR_RD_MASK:\n",
     "                    case Opcode::ISR_RD_MASK:\n" + "".join(f"                    case Opcode::ISR_{n}_ABK:\n" for n, c, d in NEW))

# ---------------- all_bank_refresh.cpp ----------------
R = "dram_controller/impl/refresh/all_bank_refresh.cpp"
edit(R, "    Clk_t m_next_refresh_cycle = -1;\n",
     "    Clk_t m_next_refresh_cycle = -1;\n    bool m_no_rank_fix = false;  // dbpu: GDDR6 has no rank level -> upstream never refreshes\n")
edit(R, "        m_ctrl = cast_parent<IDRAMController>();\n",
     "        m_ctrl = cast_parent<IDRAMController>();\n"
     "        m_no_rank_fix = param<bool>(\"refresh_without_rank\").desc(\"dbpu: issue one REFab per channel when the DRAM has no rank level\").default_val(false);\n")
edit(R, "        m_next_refresh_cycle = m_nrefi;\n",
     "        m_next_refresh_cycle = m_nrefi;\n        m_has_rank = (m_num_ranks > 0);\n"
     "        if (!m_has_rank && m_no_rank_fix) m_num_ranks = 1;\n")
edit(R, "    Clk_t m_next_refresh_cycle = -1;\n", "    Clk_t m_next_refresh_cycle = -1;\n    bool m_has_rank = true;\n")
edit(R, "                addr_vec[1] = r;\n", "                if (m_has_rank) addr_vec[1] = r;\n")

# ---------------- GDDR6.cpp ----------------
G = "dram/impl/GDDR6.cpp"
# new timings appended before tCK_ps in every preset (5 presets)
NT = [("nCCDCMP", 2), ("nCCDALU", 2), ("nCCDMUL", 2), ("nCCDGAG", 2), ("nPULAT", 2), ("nPULATMUL", 6), ("nPUWTR", 11), ("nPUWR", 33)]
t = rd(os.path.join(S, G))
ins = "".join(f"             {v},   // {k} (dbpu)\n" for k, v in NT)
t, k = re.subn(r"(             32,   // nMODCH\n)(             \d+ +// tCK_ps)", lambda m: m.group(1) + ins + m.group(2), t)
assert k == 5, k
wr(os.path.join(S, G), t)
# timing name list: fix the nRFC/nREFI/nRREFD/nRFCpb order to match the presets, add new names
edit(G, '        "nRFC",\n        "nREFI",\n        "nRREFD",\n        "nRFCpb",\n',
        '        "nRFC",     // dbpu: order fixed to match the presets (upstream had nREFI/nRFCpb swapped)\n        "nRFCpb",\n        "nRREFD",\n        "nREFI",\n')
edit(G, '        "nMODCH",\n        "tCK_ps"};', '        "nMODCH",\n' + "".join(f'        "{k}",\n' for k, v in NT) + '        "tCK_ps"};')
# commands
edit(G, '        "EOC",\n        "UNKNOWN"};', '        "EOC",\n' + "".join(f'        "{c}",\n' for n, c, d in NEW) + '        "UNKNOWN"};')
edit(G, '                                  {"EOC", "channel"},\n',
     '                                  {"EOC", "channel"},\n' + "".join(f'                                  {{"{c}", "channel"}},\n' for n, c, d in NEW))
edit(G, '                        {"EOC", {false, false, false, false}},\n',
     '                        {"EOC", {false, false, false, false}},\n' + "".join(f'                        {{"{c}", {{false, false, true, false}}}},\n' for n, c, d in NEW))
edit(G, '        "ISR_RD_MASK",\n        "MAX"};', '        "ISR_RD_MASK",\n' + "".join(f'        "ISR_{n}_ABK",\n' for n, c, d in NEW) + '        "MAX"};')
edit(G, '                                        {"ISR_RD_MASK", "RDMAC16"},  // 20 - aimdb: read predicate masks (RDMAC16 timing)\n',
     '                                        {"ISR_RD_MASK", "RDMAC16"},  // 20 - aimdb: read predicate masks (RDMAC16 timing)\n' +
     "".join(f'                                        {{"ISR_{n}_ABK", "{c}"}},  // dbpu\n' for n, c, d in NEW))
# do not overwrite tRFC/tREFI from the JEDEC DDR4 tables when the density is not in them (AiM: 128 Gb -> index -1, UB)
edit(G, '        m_timing_vals("nRFC") = JEDEC_rounding(tRFC_TABLE[0][density_id], tCK_ps);\n        m_timing_vals("nREFI") = JEDEC_rounding(tREFI_BASE, tCK_ps);\n',
        '        if (density_id != -1) {  // dbpu: upstream indexed tRFC_TABLE[0][-1] for the AiM density\n'
        '            m_timing_vals("nRFC") = JEDEC_rounding(tRFC_TABLE[0][density_id], tCK_ps);\n'
        '            m_timing_vals("nREFI") = JEDEC_rounding(tREFI_BASE, tCK_ps);\n        }\n')
edit(G, '        m_command_latencies("EOC") = 1;\n',
     '        m_command_latencies("EOC") = 1;\n        m_command_latencies("REFab") = 1;  // dbpu: refresh can now fire\n' +
     "".join(f'        m_command_latencies("{c}") = 1;\n' for n, c, d in NEW))
PURD = '"CMP16", "ALU16", "MUL16", "GAG16"'
COLS = '"RD", "RDA", "MAC", "RDCP", "RDMAC16", "RDAF16", "MAC16", "EWMUL16", "CMP16", "ALU16", "MUL16", "GAG16", "PUWR16"'
cons = f'''
                                      /****** dbpu: database processing-unit commands (all-bank, lockstep) ******/
                                      // ACT16 -> first PU column access (same row-to-column delays as MAC16 / write)
                                      {{.level = "channel", .preceding = {{"ACT", "ACT4", "ACT16"}}, .following = {{{PURD}}}, .latency = V("nRCDRDMAC")}},
                                      {{.level = "channel", .preceding = {{"ACT", "ACT4", "ACT16"}}, .following = {{"PUWR16"}}, .latency = V("nRCDWR")}},
                                      // each PU command occupies the bank column path for its class interval
                                      {{.level = "channel", .preceding = {{"CMP16"}}, .following = {{{COLS}}}, .latency = V("nCCDCMP")}},
                                      {{.level = "channel", .preceding = {{"ALU16"}}, .following = {{{COLS}}}, .latency = V("nCCDALU")}},
                                      {{.level = "channel", .preceding = {{"MUL16"}}, .following = {{{COLS}}}, .latency = V("nCCDMUL")}},
                                      {{.level = "channel", .preceding = {{"GAG16"}}, .following = {{{COLS}}}, .latency = V("nCCDGAG")}},
                                      {{.level = "channel", .preceding = {{"MAC16", "EWMUL16", "RDMAC16", "RDAF16", "PUWR16"}}, .following = {{{PURD}, "PUWR16"}}, .latency = V("nCCDL")}},
                                      // result write-back waits for the PU pipeline; next read after a write waits tWTR-like turnaround
                                      {{.level = "channel", .preceding = {{"CMP16", "ALU16", "GAG16"}}, .following = {{"PUWR16"}}, .latency = V("nPULAT")}},
                                      {{.level = "channel", .preceding = {{"MUL16"}}, .following = {{"PUWR16"}}, .latency = V("nPULATMUL")}},
                                      {{.level = "channel", .preceding = {{"PUWR16"}}, .following = {{{PURD}, "MAC16", "EWMUL16", "RD", "RDA", "RDCP"}}, .latency = V("nPUWTR")}},
                                      // register read-out waits for the deepest pipeline to drain
                                      {{.level = "channel", .preceding = {{{PURD}}}, .following = {{"RDMAC16", "RDAF16"}}, .latency = V("nPULATMUL")}},
                                      // column access -> precharge (read: tRTP, internal write: write recovery)
                                      {{.level = "channel", .preceding = {{{PURD}}}, .following = {{"PRE", "PRE4", "PREA"}}, .latency = V("nRTP")}},
                                      {{.level = "channel", .preceding = {{"PUWR16"}}, .following = {{"PRE", "PRE4", "PREA"}}, .latency = V("nPUWR")}},
'''
edit(G, '                                      /****************************************************** Bank Group ******************************************************/\n',
     cons + '\n                                      /****************************************************** Bank Group ******************************************************/\n')
edit(G, '"RDCP", "WRCP", "WRGB", "RDMAC16", "RDAF16", "WRMAC16", "WRA16", "SYNC", "EOC"}, .latency = V("nMODCH")},',
        '"RDCP", "WRCP", "WRGB", "RDMAC16", "RDAF16", "WRMAC16", "WRA16", "SYNC", "EOC", "CMP16", "ALU16", "MUL16", "GAG16", "PUWR16"}, .latency = V("nMODCH")},')
edit(G, '        m_preqs[m_levels["channel"]][m_commands["EWMUL16"]] = Lambdas::Preq::Channel::RequireAllRowsOpen<GDDR6>;\n',
     '        m_preqs[m_levels["channel"]][m_commands["EWMUL16"]] = Lambdas::Preq::Channel::RequireAllRowsOpen<GDDR6>;\n' +
     "".join(f'        m_preqs[m_levels["channel"]][m_commands["{c}"]] = Lambdas::Preq::Channel::RequireAllRowsOpen<GDDR6>;\n' for n, c, d in NEW))
print("ok")
