"""Recompute and print every number quoted in the findings from the CSV/JSON outputs of this directory.
Run after: ncu_raw.py, sort_input_rows.py (pixi python), chains.py, gap_by_host.py, sensitivity.py, q1_sf10_groupby_sort.py."""
import csv, json, os, statistics as st

H = os.path.dirname(os.path.abspath(__file__))
rd = lambda n: list(csv.DictReader(open(f"{H}/{n}")))
f = float
RT = rd("roundtrip_bytes.csv")
print("== totals over 21 queries (roundtrip_bytes.csv)")
for k in ("base_table_pinned_B", "all_kernels_dram_rd_B", "all_kernels_sm_store_B", "all_kernels_atomic_B", "all_kernels_dram_wr_B",
          "roundtrip_B_same_thread", "roundtrip_B_intra_operator", "roundtrip_B_inter_operator", "roundtrip_B_cross_thread",
          "host_gap_us_same_thread_edges", "readback_edges", "nsys_kernel_us", "step_edges_same_thread"):
    print(f"  {k:34s} {sum(f(r[k]) for r in RT):,.0f}")
rat = sorted((f(r["roundtrip_B_same_thread"]) / f(r["base_table_pinned_B"]), int(r["q"])) for r in RT)
print("  roundtrip/base median %.3f min %.3f (Q%d) max %.3f (Q%d)" % (st.median(x for x, _ in rat), rat[0][0], rat[0][1], rat[-1][0], rat[-1][1]))
print("  roundtrip/base per query:", [(q, round(x, 2)) for x, q in rat])
print("  roundtrip/all dram_rd median %.3f" % st.median(f(r["roundtrip_B_same_thread"]) / f(r["all_kernels_dram_rd_B"]) for r in RT))
print("  per query (q, RT MB, base MB, readback edges, gap ms):",
      [(r["q"], round(f(r["roundtrip_B_same_thread"]) / 1e6, 1), round(f(r["base_table_pinned_B"]) / 1e6), r["readback_edges"],
        round(f(r["host_gap_us_same_thread_edges"]) / 1e3, 2)) for r in RT])
print("== gap by host activity (gap_by_host.csv)")
for r in rd("gap_by_host.csv"):
    print("  ", r)
print("== placement (sensitivity.json)")
S = json.load(open(f"{H}/sensitivity.json"))
s = S["300"]
print("  kernels %d by_name %d (%.1f%%) context %d (%.1f%%) weak %d unplaced %d; kernel time by name %.1f%%; unique plan instance %d (%.1f%%)" % (
    s["kernels"], s["placed_by_name"], 100 * s["placed_by_name"] / s["kernels"], s["placed_by_context"], 100 * s["placed_by_context"] / s["kernels"],
    s.get("placed_weak", 0), s["unplaced"], 100 * s["kernel_ns_by_name"] / s["kernel_ns"], s["launches_unique_plan_instance"],
    100 * s["launches_unique_plan_instance"] / s["kernels"]))
print("  segments %d isolated %d; TASK_GAP sensitivity RT MB:" % (s["segments"], s["segments_isolated"]),
      {k: round(v["roundtrip_B_same_thread"] / 1e6, 1) for k, v in S.items()})
print("== candidates (chain_candidates.csv)")
for r in rd("chain_candidates.csv"):
    if r.get("instances"):
        i = f(r["instances"])
        print(f"  {r['candidate']:34s} q={r['n_queries']:>2} inst={i:4.0f} L={f(r['launches']):5.0f} kt={f(r['kernel_us']):7.0f}us "
              f"RT={f(r['roundtrip_B'])/1e6:6.1f}MB maxinst={f(r['max_instance_rt_B'])/1e6:6.2f}MB gaps={f(r['gaps_us']):7.0f}us "
              f"readbacks={f(r['readbacks']):4.0f} syncs={f(r['syncs']):4.0f} gaps/inst={f(r['gaps_us'])/i:6.1f}us L/inst={f(r['launches'])/i:4.1f}")
print("== group-by -> sort (groupby_sort.csv)")
G = rd("groupby_sort.csv")
for r in G:
    print("  Q%-2s rows_in=%6s gb L=%3s %7.1fus | mid L=%s | sort L=%3s %7.1fus | gb_out_wr=%9.0fB chainRT=%9.0fB | gaps=%6.1fus gb->next=%6.1fus %s thr=%s rb=%s" % (
        r["q"], r["rows_into_sort_duckdb"], r["groupby_launches"], f(r["groupby_kernel_us_nsys"]), r["mid_projection_launches"],
        r["sort_launches"], f(r["sort_kernel_us_nsys"]), f(r["groupby_output_wr_B_ncu"]), f(r["chain_roundtrip_B_ncu"]),
        f(r["chain_gaps_us_nsys"]), f(r["groupby_to_next_gap_us"]), r["handoff"], r["threads"], r["readbacks_in_chain"]))
print("  sums: chain launches %d kernel %.0fus gaps %.0fus RT %.0fB; gb kernel %.0fus; sort kernel %.0fus; median gaps %.0fus median sort+gb kernel %.0fus" % (
    sum(int(r["chain_launches"]) for r in G), sum(f(r["chain_kernel_us_nsys"]) for r in G), sum(f(r["chain_gaps_us_nsys"]) for r in G),
    sum(f(r["chain_roundtrip_B_ncu"]) for r in G), sum(f(r["groupby_kernel_us_nsys"]) for r in G), sum(f(r["sort_kernel_us_nsys"]) for r in G),
    st.median(f(r["chain_gaps_us_nsys"]) for r in G), st.median(f(r["chain_kernel_us_nsys"]) for r in G)))
print("  Q1 SF10:", {k: v for k, v in json.load(open(f"{H}/q1_sf10_groupby_sort.json")).items() if not k.endswith("subs") and "grids" not in k})
print("== modeled upper bound (upper_bound.csv)")
U = rd("upper_bound.csv")
for r in U:
    print("  Q%-2s RT=%6.1fMB  dm@672=%6.1fus  dm_upper(reader kernels)=%7.1fus  gaps_union=%7.1fus  launches=%4s  engine=%5.0fus busy=%6.0fus  dm%%=%5.2f  dm+gaps%%=%5.1f" % (
        r["q"], f(r["chains_roundtrip_B_ncu"]) / 1e6, f(r["modeled_dm_time_us_at_672GBs"]), f(r["dm_time_upper_us_nsys_reader_kernels"]),
        f(r["chains_inner_gaps_us_nsys_wallclock_union"]), r["launches_inside_chains"], f(r["engine_ms_nsys_iter5"]) * 1e3,
        f(r["gpu_busy_ms_nsys_iter5"]) * 1e3, f(r["dm_share_of_engine_pct"]), f(r["dm_plus_gaps_share_of_engine_pct"])))
print("  median dm%% %.2f max %.2f; median dm+gaps%% %.1f range %.1f-%.1f; total launches in chains %d of %d" % (
    st.median(f(r["dm_share_of_engine_pct"]) for r in U), max(f(r["dm_share_of_engine_pct"]) for r in U),
    st.median(f(r["dm_plus_gaps_share_of_engine_pct"]) for r in U), min(f(r["dm_plus_gaps_share_of_engine_pct"]) for r in U),
    max(f(r["dm_plus_gaps_share_of_engine_pct"]) for r in U), sum(int(r["launches_inside_chains"]) for r in U), s["kernels"]))
print("  median dm_upper / engine %%: %.1f" % st.median(100 * f(r["dm_time_upper_us_nsys_reader_kernels"]) / (f(r["engine_ms_nsys_iter5"]) * 1e3) for r in U))
