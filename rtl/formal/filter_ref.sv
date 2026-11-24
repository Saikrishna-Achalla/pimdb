// Behavioural reference for pu_filter (review IMPL F7): (lo <= x <= hi) ^ invert per lane, signed or unsigned.
module filter_ref (input logic [255:0] x, lo256, hi256, input logic sgn, inv,
  output logic [31:0] r8, output logic [15:0] r16, output logic [7:0] r32, output logic [3:0] r64);
  for (genvar i = 0; i < 32; i++) assign r8[i] = (sgn ? ($signed(lo256[8*i+:8]) <= $signed(x[8*i+:8]) && $signed(x[8*i+:8]) <= $signed(hi256[8*i+:8])) : (lo256[8*i+:8] <= x[8*i+:8] && x[8*i+:8] <= hi256[8*i+:8])) ^ inv;
  for (genvar i = 0; i < 16; i++) assign r16[i] = (sgn ? ($signed(lo256[16*i+:16]) <= $signed(x[16*i+:16]) && $signed(x[16*i+:16]) <= $signed(hi256[16*i+:16])) : (lo256[16*i+:16] <= x[16*i+:16] && x[16*i+:16] <= hi256[16*i+:16])) ^ inv;
  for (genvar i = 0; i < 8; i++) assign r32[i] = (sgn ? ($signed(lo256[32*i+:32]) <= $signed(x[32*i+:32]) && $signed(x[32*i+:32]) <= $signed(hi256[32*i+:32])) : (lo256[32*i+:32] <= x[32*i+:32] && x[32*i+:32] <= hi256[32*i+:32])) ^ inv;
  for (genvar i = 0; i < 4; i++) assign r64[i] = (sgn ? ($signed(lo256[64*i+:64]) <= $signed(x[64*i+:64]) && $signed(x[64*i+:64]) <= $signed(hi256[64*i+:64])) : (lo256[64*i+:64] <= x[64*i+:64] && x[64*i+:64] <= hi256[64*i+:64])) ^ inv;
endmodule
