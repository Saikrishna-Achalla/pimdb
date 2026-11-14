# Idle-time attribution: what happens while the GPU is idle

*Subagent findings, filed verbatim by the orchestrator; not yet independently reviewed.*

## idle_attribution: what the machine does while the GPU is idle in warm SF1 queries (Q2–Q22)

### Main findings

1. **Hypothesis 2 holds for wall time, but most of the idle time is not per-launch overhead.** Measured, sums over 21 queries, median of the 5 measured nsys iterations (`idle_buckets_table.txt`, `idle_buckets.json`):
   - Total DuckDB `.timer` wall: 259.0 ms. GPU active (at least one kernel, memcpy or memset running) is 11.1% of it.
   - The rest: 33.1% is before the engine starts (pre-engine: planning plus Sirius setup before the first CUDA call), 52.0% is GPU-idle time inside the engine span, and 3.8% comes after it.
   - Inside the engine span (163.5 ms), the GPU is idle 82.4% of the time. Of that idle time:
     - 67.9% has no thread in any CUDA call (pure host or blocked).
     - Inside CUDA calls: sync 10.8%, launch 6.6%, memcpy 6.4%, pool malloc/free 4.7%, event 2.1%, other 0.6%.

2. **The idle time is concentrated in a few long gaps** (`gap_stats.csv`).
   - There are 5,726 gaps per iteration summed over the queries; per-query median gap is 5.0–9.4 µs.
   - Gaps under 20 µs: 5,119 of them, 36.1 ms in total.
   - Gaps of 100 µs–1 ms: only 220 (3.8% of gaps), but they hold 72.1 ms of the 126.3 ms total gap time (57%).
   - Back-to-back kernels would leave 27.8 ms of the 163.5 ms engine time (17.0%; per query 3.7–48.3%). So removing all host involvement could save at most 83%.
   - A more honest bound (modeled: keeps all kernel+copy time, the lead-in, the tail, and one median gap per plan operator) leaves 39.4 ms (24.1%; per query 11.2–54.6%).

3. **Launch after readback** (`launch_after_readback.csv`).
   - 1,326 of the 2,730 launches per iteration (summed over queries) follow a blocking synchronize on the same thread.
   - None follows a blocking D2H copy: every D2H is `cudaMemcpyBatchAsync` followed by a stream synchronize.
   - Host time from the end of the GPU work to the next launch: per-query median 6.8–19.5 µs. The p90 is 15–962 µs (above 250 µs in Q8, Q9, Q13, Q21).
   - Gaps of 50 µs or less: 1,225 events, 13.6 ms in total.
   - Gaps over 50 µs: 101 events, 130 ms of thread time. These overlap across the 4 pipeline threads, so the sum exceeds the engine span (130 ms vs 163.5 ms).
   - 74.4 ms of the 134.8 ms GPU-idle wall time lies inside at least one thread's readback-to-launch gap.
   - Per iteration there are many tiny control copies: H2D copies of 16 B or less run 9–249 per query (Q19: 249). Each comes with pool malloc, a stream wait on an event, and two `cudaStreamSynchronize` calls (seen in the Q6 trace, pattern inferred to be scalar setup). There are 77–879 sync calls per iteration.

4. **Stable host cost per launch** (`regression.json`; the untraced engine time comes from the Sirius log at 1 ms resolution).
   - Untraced engine time ≈ 483 µs + **18.3 ± 1.8 µs per launch** + 1.28 × kernel time. R² = 0.971; leave-one-out slope range 16.8–19.9.
   - Launches alone explain R² 0.45; pinned MB explains R² 0.01–0.03 (no explanatory power).
   - Under nsys, idle time ≈ 1.8 ms + 13.9 µs per launch + 84 µs per plan operator, R² 0.906. Each plan operator therefore carries a fixed host cost beyond its launches.

5. **CPU sampling for Q6, Q3, Q9 and Q18** (150 measured iterations each; `partB_summary.txt`, `cpu_attrib_q*.json`, `cpu_samples_q*.csv`). GPU-idle engine time, summed over the 4 queries (20.0 ms), with shares after removing the profiler's own 18%:
   - **(i) CUDA runtime/driver: 32.4%.** Launch calls 6.6%; sync/copy/event/other 25.8%.
   - **(ii) Allocation: 12.3%.** Pool malloc/free calls, rmm, and Sirius's cucascade reservations/data-batch bookkeeping.
   - **(iii) Host code between launches: 16.1%.** cuDF host code 5.3%, Sirius operator host code 10.8%.
   - **(iv) Sirius scheduling and hand-off: 37.3%.**
     - 29.2% of the idle time is wall time with **no application thread on the CPU** (exact, from context switches): every pipeline thread is in `pthread_cond_wait` (osrt). That is 0.36 / 1.10 / 1.74 / 1.60 ms per iteration (Q6/Q3/Q9/Q18), in 11–119 episodes per iteration with p90 52–80 µs.
     - The rest is on-CPU polling in `task_scheduler::management_eventloop` and the task_creator / executor manager loops.
   - **(v) DuckDB result handling inside the engine: 1.3%.**
   - **(vi) Unattributed: 0.6%.**
   - The sampled runs give a waiting vs. working split of roughly 30–35% waiting (all threads off CPU plus polling loops) and 65–70% working.

6. **Planning is a large, separate fixed cost that PIM cannot touch.** Measured: pre-engine time is 2.8 / 3.6 / 5.1 / 4.4 ms in the sampled runs, against engine time of 2.2 / 5.3 / 8.4 / 8.2 ms. Its samples split as follows:
   - Parquet footer reads through Thrift during bind: 19–25%. The SF1 SQL defines views over `read_parquet`, so each query re-reads the Parquet footers even though the data are pinned.
   - DuckDB plan/optimize 18–22%, bind 14–16%, parse 11–13%.
   - Sirius physical-plan construction 15–17%.

7. **Profiler perturbation** (measured `.timer` means, 1 ms resolution, `partB_summary.txt`):

   | Query | Plain | CUDA trace | Trace + osrt + sampling |
   |---|---|---|---|
   | Q6 | 4.15 ms | 5.01 ms (×1.21) | 5.13 ms (×1.23) |
   | Q3 | 7.48 ms | 8.85 ms | 9.31 ms (×1.25) |
   | Q9 | 11.18 ms | 12.42 ms | 13.84 ms (×1.24) |
   | Q18 | 10.15 ms | 11.57 ms | 12.81 ms (×1.26) |

   - The Part A traces (pipeline nsys run, which also collects unified-memory faults) inflate more: summed `.timer` 259 ms vs 163.5 ms untraced, and engine time ×1.71. That inferred overhead is about 2.0 µs per CUDA API call, so the Part A `api:*` buckets are overstated in absolute terms.
   - Residency is confirmed:
     - All 12 Part B runs pass the pipeline's `siriuslog.check_log` checks.
     - The delayed sampled runs (pin excluded) show no H2D copy over 612 B.

### Conclusion

GPU-idle time splits into a part that would disappear if a chain of general operators ran in memory without returning to the host, and a part that would remain.

**Would disappear (inferred upper bound ≈ 45–60% of GPU-idle engine time):**
- Per-launch runtime/driver work: (i), 32%.
- Most allocation of intermediates: (ii), 12%.
- cuDF/Sirius host code between kernels of one operator chain: (iii), 16%.
- Hand-offs *inside* a pipeline: part of (iv).

**Would remain:**
- Planning and binding: 33% of wall, plus Parquet metadata.
- Result handling.
- Sirius scheduling and thread wake-ups between pipelines: the 29% all-off-CPU share and the polling loops, unless a chain spans pipeline barriers.
- The modeled floor of about 24% of the engine span.

Two points argue against PIM:
- Much of the addressable part is software structure that a GPU-only change could also remove: scalar-setup syncs, thread hops, per-launch syncs. CUDA graphs or fewer thread hops are possible ways; I have not tested any of them.
- Planning alone (2.8–5.1 ms) is comparable to the whole engine span at SF1.

### Supporting tables
- Per-query wall decomposition, counts by direction and size class, per-thread times, and the regression tables: `idle_attribution/idle_buckets_table.txt`.
- Gap distribution and both bounds per query: `gap_stats.csv`.
- Launch-after-readback distribution: `launch_after_readback.csv`.
- Part B grouped table and run checks: `partB_summary.txt`.

### What I could not determine
- **No kernel-mode samples** (perf_event_paranoid = 2; nsys reports this). Time spent in the kernel is visible only as off-CPU intervals from context switches and osrt calls.
- **CPU time inside CUDA calls cannot be split** between the driver and CUPTI's own wrapping (pthread locks inside the API). It is reported as "cuda:*". Only samples whose leaf frame is in the injection libraries are labelled profiler.
- **The planning boundary is ±1 ms**: it rests on the 1 ms Sirius log stamp, and there are no NVTX ranges.
- **I could not identify which thread's signal ends each all-off-CPU episode**, i.e. whether it is pure wake-up latency or a timed wait expiring. The duckdb-named threads show `pthread_cond_timedwait` and `sem_timedwait` during those episodes.
- **Two classifications are name-based** (regex on symbol names) and could misfile some samples: the Sirius sub-areas and the DuckDB phases.

### What I would measure next
- Untraced runs with only the `-y` delay plus CPU sampling and context switches (no CUDA trace), to remove the CUPTI artifact.
- Wake-up latency per hand-off, from the pairing of the cond signal with the waiter's wake-up.
- The same breakdown at SF10, to see whether the fixed costs stay constant as kernel time grows.

### Files written (all under `pim_exploration/idle_attribution/`)
- Scripts in `scripts/`:
  - `idle_buckets.py` (Part A), `tables_regression.py`
  - `run_partB.sh`, `run_all_partB.sh`, plus copies of `run_sirius.sh`, `gen_sql.py`, `sirius.yaml` and `siriuslog.py`
  - `cpu_attrib.py`, `partB_summary.py`
- Data:
  - `idle_buckets.json`, `idle_buckets_table.txt`, `gap_stats.csv`, `launch_after_readback.csv`, `regression.json`
  - `cpu_samples_q{6,3,9,18}.csv`, `cpu_attrib_q{6,3,9,18}.json`
  - `partB_summary.json`, `partB_summary.txt`
- `runs/` holds the raw runs, 313 MB: nsys-rep/sqlite files and Sirius logs for q{6,3,9,18} × {plain, cudatrace, cpu}. The nsys sqlite files embed the full process environment, including the user's e-mail address and session tokens, so do not share them.
