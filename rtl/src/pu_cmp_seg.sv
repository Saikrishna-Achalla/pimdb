// Segmented magnitude comparator over a 256-bit word (rtl/PLAN.md F6, F10, F18).
// Implements the spec's "carry links cut at lane borders" as a byte tree: per byte (lt, eq), combined
// 8 -> 16 -> 32 -> 64 b. Output: one compact vector per lane width; lane i at width w = bits [i*w+w-1 : i*w].
// Signed: the tree compares unsigned; at each lane root lt ^= sgn & (a_msb ^ b_msb). eq does not depend on sign.
module pu_cmp_seg #(
  parameter bit EQ_OUT = 1  // 0: eq outputs unused (comparators A and B need only lt)
) (
  input  logic [255:0] a,
  input  logic [255:0] b,
  input  logic         sgn,
  output logic [31:0]  lt8,
  output logic [15:0]  lt16,
  output logic [7:0]   lt32,
  output logic [3:0]   lt64,
  output logic [31:0]  eq8,
  output logic [15:0]  eq16,
  output logic [7:0]   eq32,
  output logic [3:0]   eq64
);
  logic [31:0] ul8,  ue8;
  logic [15:0] ul16, ue16;
  logic [7:0]  ul32, ue32;
  logic [3:0]  ul64, ue64;

  // per-byte unsigned compare
  for (genvar k = 0; k < 32; k++) begin : g_byte
    assign ul8[k] = a[8*k +: 8] < b[8*k +: 8];
    assign ue8[k] = a[8*k +: 8] == b[8*k +: 8];
  end
  // tree: the upper half decides unless equal
  for (genvar k = 0; k < 16; k++) begin : g_16
    assign ul16[k] = ul8[2*k+1] | (ue8[2*k+1] & ul8[2*k]);
    assign ue16[k] = ue8[2*k+1] & ue8[2*k];
  end
  for (genvar k = 0; k < 8; k++) begin : g_32
    assign ul32[k] = ul16[2*k+1] | (ue16[2*k+1] & ul16[2*k]);
    assign ue32[k] = ue16[2*k+1] & ue16[2*k];
  end
  for (genvar k = 0; k < 4; k++) begin : g_64
    assign ul64[k] = ul32[2*k+1] | (ue32[2*k+1] & ul32[2*k]);
    assign ue64[k] = ue32[2*k+1] & ue32[2*k];
  end

  // signed correction at the lane root: the lane's top bit is bit w*i + w - 1
  for (genvar i = 0; i < 32; i++) begin : g_s8
    assign lt8[i] = ul8[i] ^ (sgn & (a[8*i+7] ^ b[8*i+7]));
  end
  for (genvar i = 0; i < 16; i++) begin : g_s16
    assign lt16[i] = ul16[i] ^ (sgn & (a[16*i+15] ^ b[16*i+15]));
  end
  for (genvar i = 0; i < 8; i++) begin : g_s32
    assign lt32[i] = ul32[i] ^ (sgn & (a[32*i+31] ^ b[32*i+31]));
  end
  for (genvar i = 0; i < 4; i++) begin : g_s64
    assign lt64[i] = ul64[i] ^ (sgn & (a[64*i+63] ^ b[64*i+63]));
  end

  if (EQ_OUT) begin : g_eq
    assign eq8 = ue8;
    assign eq16 = ue16;
    assign eq32 = ue32;
    assign eq64 = ue64;
  end else begin : g_noeq
    assign eq8 = '0;
    assign eq16 = '0;
    assign eq32 = '0;
    assign eq64 = '0;
  end
endmodule
