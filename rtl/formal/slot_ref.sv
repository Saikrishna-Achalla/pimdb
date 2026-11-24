// Behavioural reference for pu_slot, written from rtl/PLAN.md section 4 (review IMPL F7): mask bit slot*n + r takes
// lane r of the n lanes; SET / AND / OR on that window, other bits held; mask op 11 changes nothing.
module slot_ref (
  input  logic [1:0] size, input logic [5:0] addr, input logic [1:0] mop,
  input  logic [31:0] r8, input logic [15:0] r16, input logic [7:0] r32, input logic [3:0] r64,
  input  logic [255:0] m, output logic [255:0] m_d);
  always_comb begin
    int n, slot; logic rb;
    n = 32 >> size;                    // lanes
    slot = addr % (256 / n);
    m_d = m;
    for (int r = 0; r < 32; r++) if (r < n) begin
      rb = (size == 0) ? r8[r] : (size == 1) ? r16[r % 16] : (size == 2) ? r32[r % 8] : r64[r % 4];
      case (mop)
        2'd0: m_d[slot * n + r] = rb;
        2'd1: m_d[slot * n + r] = m[slot * n + r] & rb;
        2'd2: m_d[slot * n + r] = m[slot * n + r] | rb;
        default: ;
      endcase
    end
  end
endmodule
