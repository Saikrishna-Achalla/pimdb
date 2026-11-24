// Shared types of the per-bank PU (rtl/PLAN.md sections 3, 9).
package pu_pkg;
  // Decoded command, as it reaches the PU in stage 2 (one slot after issue).
  typedef enum logic [3:0] {
    OP_NOP     = 4'd0,
    OP_PWGB    = 4'd1,  // Global Buffer word on the bus -> bound lo / hi + config
    OP_PCMP    = 4'd2,  // filter compare of the row word X, into M through slot placement
    OP_PLD_ROW = 4'd3,  // V <- X
    OP_PLD_GB  = 4'd4,  // V <- Global Buffer word
    OP_PCC     = 4'd5,  // compare X with V, 3-bit operator, into M
    OP_PSEL    = 4'd6,  // set-select: bit V[byte i of X], 32 lanes, into M
    OP_PMC     = 4'd7,  // whole-register mask combine
    OP_PRD     = 4'd8   // read M out (selected bank only)
  } op_t;

  // Mask operations (config mask_op, PMC op). 2'b11: no write.
  localparam logic [1:0] MOP_SET = 2'd0, MOP_AND = 2'd1, MOP_OR = 2'd2;

  // Config register, loaded from gb[133:128] by PWGB.
  typedef struct packed {
    logic [1:0] mop;    // gb[133:132]
    logic       inv;    // gb[131]
    logic       sgn;    // gb[130]
    logic [1:0] size;   // gb[129:128]: 0 = 8 b, 1 = 16 b, 2 = 32 b, 3 = 64 b
  } cfg_t;
endpackage
