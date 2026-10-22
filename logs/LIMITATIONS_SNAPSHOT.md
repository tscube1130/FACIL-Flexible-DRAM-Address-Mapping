# FACIL Replication — Limitations Register

**Updated:** 21 October 2026

| ID | Limitation / risk | Status | Mitigation / reporting requirement |
|---|---|---|---|
| L1 | User verified `Config::GetDRAMProtocol` contains LPDDR4 but not LPDDR5; official DRAMsim3 lacks native LPDDR5 in this checkout | OPEN | User opted for LPDDR4-controller plus sourced LPDDR5 timing **approximation**; state explicitly in methodology. Instructor acceptance of non-native protocol is not verified |
| L2 | Changing tCK and timing fields alone does not emulate all LPDDR5 command and clock-domain behavior | OPEN | Separate **LPDDR5-timing approximation** from native LPDDR5 claims, cite parameter origins and validate bandwidth |
| L3 | 204.8 GB/s is theoretical Jetson LPDDR5-6400 256-bit peak, not guaranteed achieved throughput | TRACK | Validate calculated theoretical peak, completed bytes, elapsed time, and read/write mix; never force a fit |
| L4 | Fixed-cycle trace execution (`-c`) is not completed-workload latency | OPEN | Verify all transactions complete and implement end-of-workload drain/time collection if necessary |
| L5 | DRAMsim3 alone does not model near-bank PIM compute/reduction | OPEN | Use separately stated analytical GEMV model for TTLT, not fabricated measured end-to-end time |
| L6 | Reduced-scale setup differs from the paper's Jetson+DRAMsim PIM setup | EXPECTED | Document matrix shapes, timing/config, PIM assumptions, and compare qualitative trends, not identical headline ratios |
| L7 | Claimed original extension must preserve FACIL's PIM placement correctness | OPEN | Add correctness tests and benchmark baseline/FACIL/extension under comparable workloads |

| L8 | The inspected LPDDR4 sample has 8 banks/rank, 1 channel and 64-bit bus, not the paper's PIM configuration or Jetson bus | OPEN | Reconcile 16 banks/rank, paper's two-rank-per-channel assumption, and Jetson 256-bit aggregate bus; record valid geometry and assumptions |

**Latest evidence:** 21 Oct 2026, user pasted `configs/LPDDR4_8Gb_x16_2400.ini` and `Config::GetDRAMProtocol()` output. The original sample's 2400 MT/s × 64 bits implies 19.2 GB/s theoretical peak; the required Jetson reference is 6400 MT/s × 256 bits = 204.8 GB/s. Neither is a promised achieved rate. No LPDDR5 timings have yet been sourced/validated.

Keep this in the same repo as `FACIL_PROJECT_LOG.md`. Resolve or update each entry when new evidence arrives.

**Decision update (21 Oct 2026):** user chose timing-only approximation. Native LPDDR5 CK/WCK clock separation and commands remain unmodeled; matching theoretical bandwidth does not validate protocol fidelity. For a DDR-style 6400 MT/s effective simulator tick, `tCK_sim=0.3125 ns`, distinct from the real LPDDR5 CK=1.25 ns at 4:1 WCK:CK. LPDDR5 timing fields should be sourced, converted to simulator ticks and checked individually. Use a separate config and retain the untouched LPDDR4 sample.


## 21 October 2026 — Sequential bandwidth test interpretation

DRAMsim3's 16 MiB / 128 B sequential trace completed 131,072 reads across four channels evenly. At 500,000 fixed simulation cycles, stats reported 26.8435 GB/s per channel (107.374 GB/s total). Since the simulation continues for a fixed cycle budget, this average includes potential idle time after the last completion. It is not evidence of a sustained-bandwidth deficit relative to the theoretical LPDDR5-6400 / 256-bit limit of 204.8 GB/s. Next find the smallest cycle budget with all requests done (or implement callback-based stop condition), and distinguish completion time from reported aggregate throughput. The protocol remains LPDDR4 with an approximate LPDDR5 timing selection, not native LPDDR5.

**475k-run update (21 Oct 2026):** All 131,072 sequential-read requests completed (32,768/channel). Aggregate `average_bandwidth` across fixed 475,000 cycles = 113.0256 GB/s; this is *not* necessarily the drained-workload throughput. Completion time is bounded by 300,000 < T_complete <= 475,000 cycles from runs shared so far. Next test 450,000 cycles and narrow the boundary. Timing approximation remains uncalibrated.

## 2026-10-21: 450k/475k sequential-read validation

- Latest observed 450k-cycle run completed 124,679 of 131,072 reads, leaving 6,393 in flight/not completed. The 475k-cycle run completed all requests. The completion boundary is bracketed within (450k, 475k] ticks, not exactly measured.
- Approximately 113 GB/s of *reported average bandwidth* was observed in a specific 16 MiB sequential-read trace with one request arriving per simulator cycle and fixed-duration runs. This is about 55% of the 204.8 GB/s theoretical interface reference; neither number proves native LPDDR5 validity.
- `average_bandwidth` from fixed-cycle runs can reflect uncompleted requests or an idle tail. For final results, stop on EOF plus drained transactions and explicitly report the measurement window and traffic count.
- Do not modify timing parameters simply to fit 204.8 GB/s. DRAMsim3 still uses an LPDDR4 command/protocol model with LPDDR5-like timing parameters.

## 2026-10-21 — Re-layout trace prototype limitation

Two new Python scripts model **read source DRAM transactions** and **write scratch-buffer DRAM transactions** in separate simulation stages. They do not yet physically rearrange matrix data according to FACIL mapping, and therefore cannot establish functional equivalence or paper-level re-layout latency. Serialized two-stage DRAM timing can overestimate costs by ignoring overlap; omitting CPU/GPU rearrangement, cache and transfer mechanisms can underestimate costs; the net bias is undetermined. The scripts bound completion cycles to a resolution (default 256 ticks) via repeat runs, rather than implementing DRAMsim3 end-of-trace callback logic. Report results solely as a *DRAM-only serialized data-copy proxy* until mapped data and operations are verified.

## 2026-10-21 — Initial re-layout experiment limitations confirmed
- Completed initial 512 × 1024 FP16 two-stage read/write simulation: 9.36 μs read + 9.12 μs write = 18.48 μs serialized proxy (256-cycle completion search resolution). Both 8,192-request stages completed.
- Traces model streaming full-array reads and writes to distinct address ranges, NOT actual intra-page permutation nor FACIL MapID-controlled translation.
- Two *separate* simulations imply no read/write overlap and omit CPU/GPU data rearrangement, cache/timing effects, and memory-controller contention. 18.48 μs bounds the sum of simulated stage completion windows only, not real end-to-end re-layout latency.
- Keep timing proxy distinguished from native LPDDR5 and do not derive a true TTFT speedup solely from this DRAM copy estimate.


## 2026-10-21 — Four-size sweep qualification

The user executed DRAM-only serialized source-read and scratch-write tests for FP16 matrices with 0.5, 1, 2 and 4 MiB weights; times bounded by (9.36, 18.48, 36.96, 73.68) microseconds, respectively, with 256-cycle completion-search resolution. Linear scaling is credible for the *proxy* but is not validation of an actual FACIL mapping, full CPU/GPU weight reordering, a native LPDDR5 simulator, or end-to-end TTFT. Keep full mapping integration and separate compute/PIM models pending.

## 2026-10-21 — New reference mapper and TTFT scenario limitations

- The Person A mapper implements a standalone Figure-8/9/10-inspired AiM physical bit permutation and a MapID selector. It has NOT been installed into DRAMsim3 or verified against DRAMsim3's `address_mapping` parser/decoder. No DRAMsim3 performance comparison can be attributed to it until that bridge is validated.
- Figure 10's example geometry (2 channels, 1 rank, 16 banks/channel) is intentionally different from Person B's simulation proxy geometry (4 channels, nominal 2 ranks, 16 banks/rank). MapID is geometry-dependent. MapID=5 in one is not necessarily MapID=5 in the other.
- Paper illustrations use 32B DRAM transfers/2KiB AiM chunks; Person B's DRAMsim3 trace granularity is 128B. Mapper maintains distinct granularity. Actual decoder correspondence still pending.
- Figure 9 rounds non-power-of-two matrix widths upward for MapID selection. A compact virtual row-major tensor width such as 14336 might not guarantee bank confinement without padding or an explicit legal stride and kernel compatibility assessment.
- The new TTFT model reads a **measured** serialized DRAM-only copy proxy (upper-bound estimate on serialized transfer time) and adds an **assumed analytical** SoC GEMM roofline cost. The resulting times and speedups are *scenario calculations, not measured end-to-end TTFT and not rigorous performance bounds*. Default GPU efficiency 100% is idealized; cache and mapping side effects are not simulated; decode GEMV correctly excluded.
- Included offline preview fixture transcribes user-provided 1MiB result, rather than rerunning DRAMsim3 here. Final report figures should be reproduced in the user's WSL environment using their `summary.json`.
