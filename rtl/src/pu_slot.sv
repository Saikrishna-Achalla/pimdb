// Slot placement + mask op on the window (rtl/PLAN.md F5, F6, F9).
// n = 256 / w lanes; slot = addr[2:0] / [3:0] / [4:0] / [5:0] for w = 8 / 16 / 32 / 64; mask bit b is in the window
// when b[7:k] == slot (k = 5, 4, 3, 2), and takes lane b mod n (one 4:1 mux per bit).
// Mask op 11: no change (m_d = m).
module pu_slot
  import pu_pkg::*;
(
  input  logic [1:0]   size,
  input  logic [5:0]   addr,
  input  logic [1:0]   mop,
  input  logic [31:0]  r8,
  input  logic [15:0]  r16,
  input  logic [7:0]   r32,
  input  logic [3:0]   r64,
  input  logic [255:0] m,
  output logic [255:0] m_d     // new M (window updated, other bits held)
);
  for (genvar b = 0; b < 256; b++) begin : g_bit
    logic r, win, upd;
    assign r   = (size == 2'd0) ? r8[b % 32] : (size == 2'd1) ? r16[b % 16] :
                 (size == 2'd2) ? r32[b % 8] : r64[b % 4];
    assign win = (size == 2'd0) ? (addr[2:0] == 3'(b / 32)) : (size == 2'd1) ? (addr[3:0] == 4'(b / 16)) :
                 (size == 2'd2) ? (addr[4:0] == 5'(b / 8))  : (addr[5:0] == 6'(b / 4));
    assign upd = (mop == MOP_SET) ? r : (mop == MOP_AND) ? (m[b] & r) : (mop == MOP_OR) ? (m[b] | r) : m[b];
    assign m_d[b] = win ? upd : m[b];
  end
endmodule
