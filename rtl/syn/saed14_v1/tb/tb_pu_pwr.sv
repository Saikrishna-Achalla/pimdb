// Gate-level power testbench for the DC netlist of pu (derived from rtl/tb/tb_pu.sv, partner's vectors and timing).
// Differences from tb_pu.sv: clock period PER_NS (default 2.284 ns = one 4-tCK slot, the design's clock), no internal
// state checks (flattened netlist), VCD of the DUT scope between commands WIN0 and n (warm-up excluded).
// Checks kept: every PRD word = golden model, read path transparent otherwise -> RESULT line with the error count.
// Cycle t: inputs = command t (stage 1) / command t-1 (stage 2) applied right after the falling edge; rising edge at
// mid-period.
`timescale 1ns/1ps
module tb_pu;

  parameter bit HAS_XREG = 1;
  parameter real PER_NS = 2.284;
  parameter int MAXN = 120000;
  parameter int WIN0 = 100;     // first measured command (state defined after init_m / PLD / PMC of the generator)

  logic clk = 0;
  logic [31:0]  C  [MAXN];
  logic [255:0] X  [MAXN], G [MAXN], ERD [MAXN];
  int n, errs = 0, prds = 0;
  string dir, vcd;

  logic         x_en;
  logic [255:0] x, gb, arr, rd;
  logic [3:0]   op;
  logic [5:0]   addr;
  logic [2:0]   cc;
  logic         pmc_dst, pmc_inv, prd_sel, gb_w0;
  logic [1:0]   pmc_src, pmc_op;

  pu dut (
    .clk(clk), .x_en(x_en), .x(x), .op(op), .addr(addr), .cc(cc), .pmc_dst(pmc_dst), .pmc_src(pmc_src),
    .pmc_inv(pmc_inv), .pmc_op(pmc_op), .prd_sel(prd_sel), .gb_w0(gb_w0), .gb(gb), .arr_data(arr),
    .rd_data(rd)
  );

  task automatic drive(input int t);
    logic [31:0] c;
    x_en = (t < n) ? C[t][20] : 1'b0;
    if (HAS_XREG) x = (t < n) ? X[t] : '0;
    else          x = (t >= 1) ? X[t-1] : '0;
    c = (t >= 1) ? C[t-1] : 32'd0;
    op = c[3:0];
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
    if (!$value$plusargs("VCD=%s", vcd)) vcd = "pu.vcd";
    fd = $fopen({dir, "/n.txt"}, "r");
    k = $fscanf(fd, "%d", n);
    $fclose(fd);
    if (n > MAXN) $fatal(1, "too many commands");
    $readmemh({dir, "/ctrl.hex"}, C);
    $readmemh({dir, "/x.hex"}, X);
    $readmemh({dir, "/gb.hex"}, G);
    $readmemh({dir, "/rd.hex"}, ERD);
    for (int t = 0; t <= n; t++) begin
      if (t == WIN0) begin
        $dumpfile(vcd);
        $dumpvars(0, tb_pu.dut);
        $display("WINDOW_START %0d %0t", t, $realtime);
      end
      drive(t);
      #(0.25 * PER_NS);
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
      #(0.25 * PER_NS) clk = 1;
      #(0.5 * PER_NS) clk = 0;
    end
    $display("WINDOW_END %0d %0t", n + 1, $realtime);
    $dumpflush;
    $display("RESULT %s: %0d commands, %0d PRDs, %0d errors", dir, n, prds, errs);
    if (errs != 0) $fatal(1, "FAIL");
    $finish;
  end
endmodule
