// Behavioural reference for pu_cmp_seg: a plain per-lane compare at each width (rtl/PLAN.md F20).
module cmp_ref (
  input  logic [255:0] a, b,
  input  logic         sgn,
  output logic [31:0]  lt8,  eq8,
  output logic [15:0]  lt16, eq16,
  output logic [7:0]   lt32, eq32,
  output logic [3:0]   lt64, eq64
);
  for (genvar i = 0; i < 32; i++) begin : g8
    assign lt8[i] = sgn ? ($signed(a[8*i +: 8]) < $signed(b[8*i +: 8])) : (a[8*i +: 8] < b[8*i +: 8]);
    assign eq8[i] = a[8*i +: 8] == b[8*i +: 8];
  end
  for (genvar i = 0; i < 16; i++) begin : g16
    assign lt16[i] = sgn ? ($signed(a[16*i +: 16]) < $signed(b[16*i +: 16])) : (a[16*i +: 16] < b[16*i +: 16]);
    assign eq16[i] = a[16*i +: 16] == b[16*i +: 16];
  end
  for (genvar i = 0; i < 8; i++) begin : g32
    assign lt32[i] = sgn ? ($signed(a[32*i +: 32]) < $signed(b[32*i +: 32])) : (a[32*i +: 32] < b[32*i +: 32]);
    assign eq32[i] = a[32*i +: 32] == b[32*i +: 32];
  end
  for (genvar i = 0; i < 4; i++) begin : g64
    assign lt64[i] = sgn ? ($signed(a[64*i +: 64]) < $signed(b[64*i +: 64])) : (a[64*i +: 64] < b[64*i +: 64]);
    assign eq64[i] = a[64*i +: 64] == b[64*i +: 64];
  end
endmodule
