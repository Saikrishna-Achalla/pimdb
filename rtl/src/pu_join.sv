// Join unit (pim_exploration/notes/22 3.1): V register, comparator C with a 3-bit operator, optional set-select,
// second mask M1 and the whole-register mask combine (PMC). The PMC result for M leaves through pmc_m_*; M itself
// lives in pu (it is shared with the filter path).
module pu_join
  import pu_pkg::*;
#(
  parameter bit HAS_SETSEL = 1
) (
  input  logic         clk,
  input  op_t          op,          // stage-2 command
  input  logic [255:0] x,           // row word (stage 2)
  input  logic [255:0] gb,          // Global Buffer bus (stage 2)
  input  logic         sgn,         // config
  input  logic         inv,         // config (PSEL only)
  input  logic [2:0]   cc,          // PCC operator {L, E, G}
  input  logic         pmc_dst,     // 0: M, 1: M1
  input  logic [1:0]   pmc_src,     // 0: M, 1: M1, 2: V, 3: none (no write)
  input  logic         pmc_inv,
  input  logic [1:0]   pmc_op,      // SET / AND / OR; 3: no write
  input  logic [255:0] m,           // current M
  // C results per width
  output logic [31:0]  c8,
  output logic [15:0]  c16,
  output logic [7:0]   c32,
  output logic [3:0]   c64,
  // set-select result (8-bit lanes)
  output logic [31:0]  s8,
  // PMC write of M
  output logic         pmc_m_we,
  output logic [255:0] pmc_m_d
);
  logic [255:0] v_q, m1_q;

  // ---- V: from the row word (PLD ROW) or the Global Buffer (PLD GB)
  always_ff @(posedge clk) begin
    if (op == OP_PLD_ROW) v_q <= x;
    else if (op == OP_PLD_GB) v_q <= gb;
  end

  // ---- comparator C: x vs V
  logic [31:0] l8,  e8;
  logic [15:0] l16, e16;
  logic [7:0]  l32, e32;
  logic [3:0]  l64, e64;
  pu_cmp_seg #(.EQ_OUT(1)) u_c (
    .a(x), .b(v_q), .sgn(sgn),
    .lt8(l8), .lt16(l16), .lt32(l32), .lt64(l64),
    .eq8(e8), .eq16(e16), .eq32(e32), .eq64(e64)
  );
  // operator select: (L & lt) | (E & eq) | (G & gt), gt = !lt & !eq
  function automatic logic opsel(input logic lt, input logic eq, input logic [2:0] c);
    return (c[2] & lt) | (c[1] & eq) | (c[0] & ~lt & ~eq);
  endfunction
  for (genvar i = 0; i < 32; i++) begin : g_c8
    assign c8[i] = opsel(l8[i], e8[i], cc);
  end
  for (genvar i = 0; i < 16; i++) begin : g_c16
    assign c16[i] = opsel(l16[i], e16[i], cc);
  end
  for (genvar i = 0; i < 8; i++) begin : g_c32
    assign c32[i] = opsel(l32[i], e32[i], cc);
  end
  for (genvar i = 0; i < 4; i++) begin : g_c64
    assign c64[i] = opsel(l64[i], e64[i], cc);
  end

  // ---- set-select: lane i (byte i of x) picks bit V[byte]; optional invert
  if (HAS_SETSEL) begin : g_sel
    for (genvar i = 0; i < 32; i++) begin : g_s
      assign s8[i] = v_q[x[8*i +: 8]] ^ inv;
    end
  end else begin : g_nosel
    assign s8 = '0;
  end

  // ---- mask combine: dst = op(dst, src ^ inv), whole 256 bits
  logic [255:0] src, dst_old, dst_new;
  logic         pmc_ok;
  always_comb begin
    unique case (pmc_src)
      2'd0:    src = m;
      2'd1:    src = m1_q;
      2'd2:    src = v_q;
      default: src = '0;
    endcase
    src = src ^ {256{pmc_inv}};
    dst_old = pmc_dst ? m1_q : m;
    unique case (pmc_op)
      MOP_SET: dst_new = src;
      MOP_AND: dst_new = dst_old & src;
      MOP_OR:  dst_new = dst_old | src;
      default: dst_new = dst_old;
    endcase
    pmc_ok = (op == OP_PMC) && (pmc_src != 2'd3) && (pmc_op != 2'd3);
  end

  always_ff @(posedge clk) begin
    if (pmc_ok && pmc_dst) m1_q <= dst_new;
  end
  assign pmc_m_we = pmc_ok && !pmc_dst;
  assign pmc_m_d  = dst_new;
endmodule
