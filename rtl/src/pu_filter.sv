// Filter unit: R = (lo <= x <= hi) ^ invert per lane, for every lane width (rtl/PLAN.md section 4, F18).
// Comparator A gives lt(x, lo), so x >= lo is !lt; comparator B gives lt(hi, x), so x <= hi is !lt.
module pu_filter (
  input  logic [255:0] x,
  input  logic [255:0] lo256,
  input  logic [255:0] hi256,
  input  logic         sgn,
  input  logic         inv,
  output logic [31:0]  r8,
  output logic [15:0]  r16,
  output logic [7:0]   r32,
  output logic [3:0]   r64
);
  logic [31:0] a8,  b8;
  logic [15:0] a16, b16;
  logic [7:0]  a32, b32;
  logic [3:0]  a64, b64;
  /* verilator lint_off UNUSEDSIGNAL */
  logic [59:0] eq_a, eq_b;  // equality outputs are not used by A and B (EQ_OUT = 0)
  /* verilator lint_on UNUSEDSIGNAL */

  pu_cmp_seg #(.EQ_OUT(0)) u_a (
    .a(x), .b(lo256), .sgn(sgn),
    .lt8(a8), .lt16(a16), .lt32(a32), .lt64(a64),
    .eq8(eq_a[31:0]), .eq16(eq_a[47:32]), .eq32(eq_a[55:48]), .eq64(eq_a[59:56])
  );
  pu_cmp_seg #(.EQ_OUT(0)) u_b (
    .a(hi256), .b(x), .sgn(sgn),
    .lt8(b8), .lt16(b16), .lt32(b32), .lt64(b64),
    .eq8(eq_b[31:0]), .eq16(eq_b[47:32]), .eq32(eq_b[55:48]), .eq64(eq_b[59:56])
  );

  assign r8  = ~(a8  | b8)  ^ {32{inv}};
  assign r16 = ~(a16 | b16) ^ {16{inv}};
  assign r32 = ~(a32 | b32) ^ {8{inv}};
  assign r64 = ~(a64 | b64) ^ {4{inv}};
endmodule
