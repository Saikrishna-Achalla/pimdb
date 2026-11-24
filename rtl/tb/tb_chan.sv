// Channel test (review IMPL F2): pu_decoder + 16 PUs. Commands are presented at issue time; each PRD goes to bank
// (t mod 16) and the other 15 banks must pass the normal read data through. All banks see the same row words, so all
// hold the same M; the test checks the decoder (x_en timing, one-slot control delay, PRD one-hot, PWGB word 0).
`timescale 1ns/1ps
module tb_chan;
  import pu_pkg::*;
  parameter bit HAS_JOIN = 1, HAS_SETSEL = 1, HAS_XREG = 1;
  parameter int MAXN = 120000;
  logic clk = 0, rst_n = 0;
  logic [31:0]  C [MAXN];
  logic [255:0] X [MAXN], G [MAXN], ERD [MAXN];
  int n, errs = 0, prds = 0;
  string dir;
  logic cmd_valid; op_t cmd_op; logic [3:0] cmd_bank; logic [5:0] cmd_addr, cmd_gbidx; logic [2:0] cmd_cc;
  logic cmd_pmc_dst, cmd_pmc_inv; logic [1:0] cmd_pmc_src, cmd_pmc_op;
  logic x_en; op_t op; logic [5:0] addr; logic [2:0] cc; logic pmc_dst, pmc_inv, gb_w0; logic [1:0] pmc_src, pmc_op;
  logic [15:0] prd_sel;
  logic [255:0] x, gb, arr;
  logic [255:0] rd [16];
  pu_decoder dec (.*);
  for (genvar b = 0; b < 16; b++) begin : g_b
    pu #(.HAS_JOIN(HAS_JOIN), .HAS_SETSEL(HAS_SETSEL), .HAS_XREG(HAS_XREG)) u (
      .clk(clk), .x_en(x_en), .x(x), .op(op), .addr(addr), .cc(cc), .pmc_dst(pmc_dst), .pmc_src(pmc_src),
      .pmc_inv(pmc_inv), .pmc_op(pmc_op), .prd_sel(prd_sel[b]), .gb_w0(gb_w0), .gb(gb), .arr_data(arr),
      .rd_data(rd[b]));
  end
  initial begin
    int fd, k;
    logic [31:0] c;
    if (!$value$plusargs("VEC=%s", dir)) dir = "vec/rand_all";
    fd = $fopen({dir, "/n.txt"}, "r");
    k = $fscanf(fd, "%d", n);
    $fclose(fd);
    $readmemh({dir, "/ctrl.hex"}, C);
    $readmemh({dir, "/x.hex"}, X);
    $readmemh({dir, "/gb.hex"}, G);
    $readmemh({dir, "/rd.hex"}, ERD);
    cmd_valid = 0;
    cmd_op = OP_NOP;
    #3 rst_n = 1;
    #2;
    for (int t = 0; t <= n; t++) begin
      c = (t < n) ? C[t] : 32'd0;
      cmd_valid = (t < n);
      cmd_op = op_t'(c[3:0]);
      cmd_addr = c[9:4];
      cmd_cc = c[12:10];
      cmd_pmc_dst = c[13];
      cmd_pmc_src = c[15:14];
      cmd_pmc_inv = c[16];
      cmd_pmc_op = c[18:17];
      cmd_bank = 4'(t);
      cmd_gbidx = c[24] ? 6'd0 : 6'd1;
      if (HAS_XREG) x = (t < n) ? X[t] : '0;
      else          x = (t >= 1) ? X[t-1] : '0;
      gb = (t >= 1) ? G[t-1] : '0;
      arr = {8{32'hA5C3_0F01 ^ t}};
      #1;
      if (t >= 1) begin
        for (int b = 0; b < 16; b++) begin
          if (C[t-1][19] && b == ((t - 1) % 16)) begin
            prds++;
            if (rd[b] !== ERD[t-1]) begin
              errs++;
              if (errs < 10) $display("PRD mismatch cmd %0d bank %0d", t - 1, b);
            end
          end else if (rd[b] !== arr) begin
            errs++;
            if (errs < 10) $display("read path not transparent cmd %0d bank %0d", t - 1, b);
          end
        end
      end
      #4 clk = 1;
      #5 clk = 0;
    end
    $display("RESULT chan %s: %0d commands, %0d PRDs, %0d errors", dir, n, prds, errs);
    if (errs != 0) $fatal(1, "FAIL");
    $finish;
  end
endmodule
