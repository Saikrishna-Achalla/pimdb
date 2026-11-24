// Per-channel PIM command decoder (rtl/PLAN.md F1, F3, F16). One instance drives the 16 PUs of a channel.
// Input: the PIM command at its issue slot (stage 1). Outputs: x_en now (a PIM array read is in stage 1) and the
// decoded command one slot later (stage 2), broadcast to all banks, plus a one-hot PRD bank select.
// The command word is provisional (rtl/PLAN.md F8): opcode, bank, word address, PCC operator, PMC fields.
module pu_decoder
  import pu_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,
  input  logic        cmd_valid,
  input  op_t         cmd_op,
  input  logic [3:0]  cmd_bank,
  input  logic [5:0]  cmd_addr,
  input  logic [2:0]  cmd_cc,
  input  logic        cmd_pmc_dst,
  input  logic [1:0]  cmd_pmc_src,
  input  logic        cmd_pmc_inv,
  input  logic [1:0]  cmd_pmc_op,
  input  logic [5:0]  cmd_gbidx,   // Global Buffer word of a PWGB / PLD GB
  output logic        x_en,
  output op_t         op,
  output logic [5:0]  addr,
  output logic [2:0]  cc,
  output logic        pmc_dst,
  output logic [1:0]  pmc_src,
  output logic        pmc_inv,
  output logic [1:0]  pmc_op,
  output logic [15:0] prd_sel,
  output logic        gb_w0        // stage 2: the PWGB writes buffer word 0 (bounds + config)
);
  op_t opi;
  // opcodes 9..15 are not defined and become NOP
  assign opi = op_t'((cmd_valid && cmd_op <= OP_PRD) ? cmd_op : OP_NOP);
  assign x_en = (opi == OP_PCMP) || (opi == OP_PLD_ROW) || (opi == OP_PCC) || (opi == OP_PSEL);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      op      <= OP_NOP;
      prd_sel <= 16'd0;
      gb_w0   <= 1'b0;
    end else begin
      op      <= opi;
      prd_sel <= (opi == OP_PRD) ? (16'd1 << cmd_bank) : 16'd0;
      gb_w0   <= (opi == OP_PWGB) && (cmd_gbidx == 6'd0);
    end
  end
  always_ff @(posedge clk) begin
    addr    <= cmd_addr;
    cc      <= cmd_cc;
    pmc_dst <= cmd_pmc_dst;
    pmc_src <= cmd_pmc_src;
    pmc_inv <= cmd_pmc_inv;
    pmc_op  <= cmd_pmc_op;
  end
endmodule
