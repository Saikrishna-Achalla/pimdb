// Bound and config registers of one PU, plus the size / window decode (rtl/PLAN.md F2, F15, F16).
// Loaded by PWGB from the 256-bit Global Buffer bus: lo = gb[63:0], hi = gb[127:64], cfg = gb[133:128].
// The host writes each bound already repeated across its 64 bits, so the 256-bit bound is wiring.
// Everything here is identical in the 16 PUs of a channel; it is a separate block so its area can be reported.
module pu_cfg
  import pu_pkg::*;
(
  input  logic         clk,
  input  logic         ld,         // PWGB in stage 2
  input  logic [255:0] gb,
  output logic [255:0] lo256,
  output logic [255:0] hi256,
  output cfg_t         cfg
);
  logic [63:0] lo_q, hi_q;
  cfg_t        cfg_q;

  always_ff @(posedge clk) begin
    if (ld) begin
      lo_q  <= gb[63:0];
      hi_q  <= gb[127:64];
      cfg_q <= cfg_t'(gb[133:128]);
    end
  end

  assign lo256 = {4{lo_q}};
  assign hi256 = {4{hi_q}};
  assign cfg = cfg_q;
endmodule
