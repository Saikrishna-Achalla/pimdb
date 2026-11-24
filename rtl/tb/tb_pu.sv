// Testbench for pu: drives the vectors of gen.py through the two-stage pipeline and compares with the golden model.
// Cycle t: x = X[t] (command t in stage 1; with HAS_XREG = 0, X[t-1]), control and gb = command t-1 (stage 2).
// After the edge that ends cycle t, the state equals the golden state after command t-1. rd_data during cycle t is
// checked when command t-1 is a PRD. CHECK_STATE = 0 (netlist runs) checks rd_data only.
`timescale 1ns/1ps
module tb_pu;
  import pu_pkg::*;
  parameter bit HAS_JOIN = 1, HAS_SETSEL = 1, HAS_XREG = 1, CHECK_STATE = 1;
  parameter int MAXN = 120000;

  logic clk = 0;
  logic [31:0]  C  [MAXN];
  logic [255:0] X  [MAXN], G [MAXN], EM [MAXN], EM1 [MAXN], EV [MAXN], ERD [MAXN];
  int n, errs = 0, prds = 0, cm = 0, cm1 = 0, cv = 0;
  string dir;

  logic         x_en;
  logic [255:0] x, gb, arr, rd;
  op_t          op;
  logic [5:0]   addr;
  logic [2:0]   cc;
  logic         pmc_dst, pmc_inv, prd_sel, gb_w0;
  logic [1:0]   pmc_src, pmc_op;

  pu #(.HAS_JOIN(HAS_JOIN), .HAS_SETSEL(HAS_SETSEL), .HAS_XREG(HAS_XREG)) dut (
    .clk(clk), .x_en(x_en), .x(x), .op(op), .addr(addr), .cc(cc), .pmc_dst(pmc_dst), .pmc_src(pmc_src),
    .pmc_inv(pmc_inv), .pmc_op(pmc_op), .prd_sel(prd_sel), .gb_w0(gb_w0), .gb(gb), .arr_data(arr),
    .rd_data(rd)
  );

  task automatic drive(input int t);
    logic [31:0] c;
    // stage 1: command t
    x_en = (t < n) ? C[t][20] : 1'b0;
    if (HAS_XREG) x = (t < n) ? X[t] : '0;
    else          x = (t >= 1) ? X[t-1] : '0;
    // stage 2: command t-1
    c = (t >= 1) ? C[t-1] : 32'd0;
    op = op_t'(c[3:0]);
    addr = c[9:4];
    cc = c[12:10];
    pmc_dst = c[13];
    pmc_src = c[15:14];
    pmc_inv = c[16];
    pmc_op = c[18:17];
    prd_sel = c[19];
    gb_w0 = c[24];
    gb = (t >= 1) ? G[t-1] : '0;
    arr = {8{32'hA5C3_0F01 ^ t}};
  endtask

  initial begin
    int fd, k;
    if (!$value$plusargs("VEC=%s", dir)) dir = "vec/rand_all";
    fd = $fopen({dir, "/n.txt"}, "r");
    k = $fscanf(fd, "%d", n);
    $fclose(fd);
    if (n > MAXN) $fatal(1, "too many commands");
    $readmemh({dir, "/ctrl.hex"}, C);
    $readmemh({dir, "/x.hex"}, X);
    $readmemh({dir, "/gb.hex"}, G);
    $readmemh({dir, "/m.hex"}, EM);
    $readmemh({dir, "/m1.hex"}, EM1);
    $readmemh({dir, "/v.hex"}, EV);
    $readmemh({dir, "/rd.hex"}, ERD);
    for (int t = 0; t <= n; t++) begin
      drive(t);
      #1;
      // rd_data in stage 2 of command t-1
      if (t >= 1) begin
        if (C[t-1][19]) begin
          prds++;
          if (rd !== ERD[t-1]) begin
            errs++;
            if (errs < 10) $display("PRD mismatch at cmd %0d: got %h want %h", t - 1, rd, ERD[t-1]);
          end
        end else if (rd !== arr) begin
          errs++;
          if (errs < 10) $display("read path not transparent at cmd %0d", t - 1);
        end
      end
      #4 clk = 1;
      #1;
      if (CHECK_STATE && t >= 1) begin
        logic [31:0] c;
        c = C[t-1];
        if (c[21]) cm++;
        if (c[21] && dut.m_q !== EM[t-1]) begin
          errs++;
          if (errs < 10) $display("M mismatch after cmd %0d (op %0d): got %h want %h", t - 1, c[3:0], dut.m_q, EM[t-1]);
        end
`ifndef NO_JOIN_STATE
        if (HAS_JOIN && c[22]) cm1++;
        if (HAS_JOIN && c[23]) cv++;
        if (HAS_JOIN && c[22] && dut.g_join.u_join.m1_q !== EM1[t-1]) begin
          errs++;
          if (errs < 10) $display("M1 mismatch after cmd %0d", t - 1);
        end
        if (HAS_JOIN && c[23] && dut.g_join.u_join.v_q !== EV[t-1]) begin
          errs++;
          if (errs < 10) $display("V mismatch after cmd %0d", t - 1);
        end
`endif
      end
      #4 clk = 0;
    end
    $display("RESULT %s: %0d commands, %0d PRDs, %0d M / %0d M1 / %0d V compares, %0d errors", dir, n, prds, cm, cm1,
             cv, errs);
    if (errs != 0) $fatal(1, "FAIL");
    $finish;
  end
endmodule
