// Per-bank processing unit (rtl/PLAN.md sections 2-4, 9). One clock = one column-command slot (4 tCK).
// Stage 1: the array read puts the row word on x; with HAS_XREG it is captured at the end of the slot (x_en).
// Stage 2: the decoded command (op and fields, from pu_decoder, one slot after issue) and gb arrive; the result is
// computed and every state write happens at the end of the stage-2 slot. PRD drives rd_data = M in stage 2.
// With HAS_JOIN = 0 (or HAS_SETSEL = 0) the join commands (PSEL) are ignored: no state changes.
// x_en only gates the X register (power); it does not change results.
module pu
  import pu_pkg::*;
#(
  parameter bit HAS_JOIN   = 1,
  parameter bit HAS_SETSEL = 1,
  parameter bit HAS_XREG   = 1
) (
  input  logic         clk,
  // stage 1
  input  logic         x_en,        // a PIM array read is in stage 1 (captures X)
  input  logic [255:0] x,           // row word from the bank's I/O sense amplifiers
  // stage 2 (from pu_decoder, identical for all 16 banks except prd_sel)
  input  op_t          op,
  input  logic [5:0]   addr,
  input  logic [2:0]   cc,
  input  logic         pmc_dst,
  input  logic [1:0]   pmc_src,
  input  logic         pmc_inv,
  input  logic [1:0]   pmc_op,
  input  logic         prd_sel,     // PRD addressed to this bank (only asserted with op = PRD)
  input  logic         gb_w0,       // the PWGB writes Global Buffer word 0 (bounds + config)
  input  logic [255:0] gb,          // Global Buffer bus
  // bank read path
  input  logic [255:0] arr_data,    // normal read data from the array
  output logic [255:0] rd_data
);
  // ---- X in stage 2
  logic [255:0] xs;
  if (HAS_XREG) begin : g_xreg
    logic [255:0] x_q;
    always_ff @(posedge clk) if (x_en) x_q <= x;
    assign xs = x_q;
  end else begin : g_noxreg
    assign xs = x;
  end

  // ---- bound and config registers
  logic [255:0] lo256, hi256;
  cfg_t         cfg;
  logic ld_bounds;
  assign ld_bounds = (op == OP_PWGB) && gb_w0;   // a PWGB of a set word (words 1..63) leaves them alone
  pu_cfg u_cfg (.clk(clk), .ld(ld_bounds), .gb(gb), .lo256(lo256), .hi256(hi256), .cfg(cfg));

  // ---- filter unit
  logic [31:0] f8;
  logic [15:0] f16;
  logic [7:0]  f32;
  logic [3:0]  f64;
  pu_filter u_filter (
    .x(xs), .lo256(lo256), .hi256(hi256), .sgn(cfg.sgn), .inv(cfg.inv),
    .r8(f8), .r16(f16), .r32(f32), .r64(f64)
  );

  // ---- mask M
  logic [255:0] m_q;

  // ---- join unit
  logic [31:0]  c8, s8;
  logic [15:0]  c16;
  logic [7:0]   c32;
  logic [3:0]   c64;
  logic         pmc_m_we;
  logic [255:0] pmc_m_d;
  if (HAS_JOIN) begin : g_join
    pu_join #(.HAS_SETSEL(HAS_SETSEL)) u_join (
      .clk(clk), .op(op), .x(xs), .gb(gb), .sgn(cfg.sgn), .inv(cfg.inv), .cc(cc),
      .pmc_dst(pmc_dst), .pmc_src(pmc_src), .pmc_inv(pmc_inv), .pmc_op(pmc_op), .m(m_q),
      .c8(c8), .c16(c16), .c32(c32), .c64(c64), .s8(s8), .pmc_m_we(pmc_m_we), .pmc_m_d(pmc_m_d)
    );
  end else begin : g_nojoin
    assign {c8, c16, c32, c64, s8} = '0;
    assign pmc_m_we = 1'b0;
    assign pmc_m_d = '0;
  end

  // ---- result mux (filter / C / set-select); PSEL forces the 8-bit geometry
  logic [31:0] r8;
  logic [15:0] r16;
  logic [7:0]  r32;
  logic [3:0]  r64;
  logic [1:0]  geo, cfg_size, cfg_mop;
  assign cfg_size = cfg.size;
  assign cfg_mop  = cfg.mop;
  always_comb begin
    case (op)
      OP_PCC:  begin r8 = c8; r16 = c16; r32 = c32; r64 = c64; geo = cfg_size; end
      OP_PSEL: begin r8 = s8; r16 = '0;  r32 = '0;  r64 = '0;  geo = 2'd0; end
      default: begin r8 = f8; r16 = f16; r32 = f32; r64 = f64; geo = cfg_size; end
    endcase
  end

  // ---- slot placement + mask logic
  logic [255:0] slot_d;
  pu_slot u_slot (
    .size(geo), .addr(addr), .mop(cfg_mop), .r8(r8), .r16(r16), .r32(r32), .r64(r64), .m(m_q), .m_d(slot_d)
  );

  logic cmp_op;
  assign cmp_op = (op == OP_PCMP) || (HAS_JOIN && (op == OP_PCC || (HAS_SETSEL && op == OP_PSEL)));

  always_ff @(posedge clk) begin
    if (cmp_op)            m_q <= slot_d;     // mask op 11 returns M unchanged
    else if (pmc_m_we)     m_q <= pmc_m_d;
  end

  // ---- read path: M on a PRD to this bank, otherwise normal array data
  assign rd_data = prd_sel ? m_q : arr_data;
endmodule
