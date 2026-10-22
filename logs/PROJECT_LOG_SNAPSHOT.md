# FACIL Project — Running Log

**Started:** 21 October 2026  
**Last updated:** 21 October 2026  
**Project:** FACIL: Flexible DRAM Address Mapping for SoC–PIM Cooperative On-device LLM Inference (HPCA 2025)  
**Assignment:** Reduced-scale reproduction of the baseline and FACIL mapping; design, implement, and evaluate an original improvement.  
**Working arrangement:** Two collaborators. Mapping and workload/simulation tasks run in parallel; confirm who owns LPDDR5 modeling.  
**Status:** DRAMsim3 built; LPDDR4-protocol/LPDDR5-6400 timing proxy runs. Sequential 16 MiB trace and Person B DRAM-only serialized re-layout proxy are WSL-verified. Matrix-size sweep (0.5/1/2/4 MiB) completed; observed completion upper bounds 9.36/18.48/36.96/73.68 us. PIM-layout-to-SoC-layout conversion, calibrated LPDDR5 fidelity, full TTFT/TTLT model, and FACIL mapper integration remain pending.

> **Maintenance note:** This is a snapshot, not a live link to the WSL filesystem. Update the copy in the project repo as you work, and paste future logs/results in chat to produce revised snapshots. Do not mark a test complete without its output or corresponding artifact.

## 1. Overall objectives

1. Reproduce FACIL's mapping mechanism at reduced scale, including MapID selection and its placement implications.
2. Implement the paper's correct comparison: **SoC–PIM baseline with on-demand re-layout** versus **FACIL with no re-layout**, with otherwise comparable assumptions.
3. Simulate DRAM access/re-layout traffic, measure cycles and bandwidth, and estimate the impact on **time to first token (TTFT)**.
4. Include a separate analytical PIM GEMV model for decode and **time to last token (TTLT)** comparisons.
5. Add one independently implemented and evaluated mapping improvement, comparing baseline, FACIL, and extension.
6. Report the exact simulator/configuration assumptions and deviations from the paper.

## 2. Today's status (21 Oct 2026)

| Item | State | Evidence / next action |
|---|---|---|
| Ubuntu/WSL tooling | Complete | CMake, compiler, Git and Python present |
| GitHub `git clone` | Blocked, bypassed | HTTPS to github.com:443 timed out; source acquired as ZIP through Windows |
| DRAMsim3 source | Present | `~/DRAMsim3/DRAMsim3-master` |
| DRAMsim3 CMake build | **Complete** | Terminal showed `[100%] Built target dramsim3main`; compiler warnings but no fatal build error |
| DDR4 smoke test | Launched; result not yet verified | `./build/dramsim3main configs/DDR4_8Gb_x8_3200.ini --stream random -c 100000`; inspect `dramsim3.txt` / JSON and finished request counts |
| Python virtual environment | Activated | Shell prompt shows `(facil-venv)`; verify NumPy/Matplotlib installation if needed |
| LPDDR5 config in checked-in DRAMsim3 | **Absent** | Listing shows LPDDR3 and LPDDR4, but no LPDDR5; `grep -Ri 'LPDDR5' src configs` produced no matches |
| Native LPDDR5 controller/protocol support | **Confirmed absent in stock checkout** | User pasted `src/configuration.cc` `Config::GetDRAMProtocol()` showing `LPDDR4` but no `LPDDR5` entry; DRAMsim3 official README likewise omits LPDDR5 |
| FACIL mapper | Pending / teammate work | Decide integration contract and test expected MapIDs |
| Trace generation | **Sequential validation trace complete** | 16 MiB / 128 B = 131,072 reads; matrix-specific and re-layout traces remain pending |
| Baseline/FACIL comparison | Pending | Need identical logical accesses and explicit re-layout trace |
| Original extension | Proposed, not yet built | Test a valid alternative map/policy under background interference, with PIM placement constraints preserved |

## 2A. Confirmed local configuration inspection (21 Oct 2026)

The user ran `cat configs/LPDDR4_8Gb_x16_2400.ini` in WSL and pasted the results. This **is the local sample**, not the desired LPDDR5 setup:

```ini
[dram_structure]
protocol = LPDDR4
bankgroups = 2
banks_per_group = 4
rows = 65536
columns = 1024
device_width = 16
BL = 16

[timing]
tCK = 0.83
CL = 17
CWL = 14
tRCD = 15
tRP = 15
tRAS = 32

[system]
channel_size = 8192
channels = 1
bus_width = 64
address_mapping = rochrababgco
```

The complete source config includes further timing and power fields. The parser output confirms allowed names `LPDDR`, `LPDDR3`, `LPDDR4` but **not** `LPDDR5` (also no `DDR5`; the file names `GDDR5` and `GDDR5X` are distinct protocols). `LPDDR5` in the INI would be rejected by this checkout.

**Calculated check:** LPDDR4-2400 × 64-bit total interface = 19.2 GB/s *nominal peak* for the sample. Target Jetson reference LPDDR5-6400 × 256-bit = 204.8 GB/s *nominal peak*. Neither is a required measured sustained bandwidth. The current config also describes 8 banks per rank (`2 × 4`), whereas the FACIL paper's PIM experiments assume 16 banks per rank, and 2 ranks per channel; reconcile organization before claiming paper match.

**Decision as of 21 Oct 2026:** user chose DRAMsim3 LPDDR4-controller plus a clearly labeled LPDDR5-6400 **timing approximation** for the project. Professor approval for this departure from native protocol modeling is not independently confirmed. Both options need documentation; do **not** present the approximation as native LPDDR5. Until resolved, continue independent workload/trace-generation and parser inspection, without collecting final DRAM performance figures.

## 2B. Verified LPDDR5-6400 timing-proxy smoke test and sequential read (21 Oct 2026)

**User-provided commands and configuration**

- `python3 create_lpddr5_config.py` generated `configs/LPDDR5_6400_APPROX.ini` with `protocol = LPDDR4`, `tCK = 0.3125 ns`, four 64-bit modeled channels, and an LPDDR5-style selected timing set. Its printed `204.8 GB/s` is a **theoretical arithmetic figure**, not an observed measurement.
- `./build/dramsim3main configs/LPDDR5_6400_APPROX.ini --stream random -c 100000 -o personB/results/lpddr5_smoke` returned to shell without an evident error. Statistics not yet inspected.
- Cloned into `configs/LPDDR5_6400_APPROX_v1.ini` and corrected `AL = 0`, `channel_size = 16384` (MB), and `address_mapping = rorabgbacoch` for the channel-interleaved bandwidth check. User verified `bankgroups = 4`, `banks_per_group = 4`, `BL = 16`, `tCK = 0.3125`, `channels = 4`, `bus_width = 64`, and `protocol = LPDDR4`. Source code derives two ranks per channel from this capacity/geometry: 8192 MiB per rank; 16384 MiB per channel.
- Wrote `personB/traces/sequential_16MiB.trace`, with exactly **131,072 `READ` transactions**, each 128 bytes, arriving at simulation cycles `0` through `131071`.
- Simulation: `./build/dramsim3main configs/LPDDR5_6400_APPROX_v1.ini -t personB/traces/sequential_16MiB.trace -c 500000 -o personB/results/sequential_v1`.

**Measured results (user terminal output)**

| Channel | Completed reads | Row-buffer hits | Reported average BW (GB/s) |
|---|---:|---:|---:|
| 0 | 32768 | 32177 | 26.8435 |
| 1 | 32768 | 32177 | 26.8435 |
| 2 | 32768 | 32177 | 26.8435 |
| 3 | 32768 | 32177 | 26.8435 |
| **Total** | **131072** | **128708** | **107.374** |

- **100% completed**, exactly matching submitted trace; DRAMsim3 `Controller::ReturnDoneTrans` increments `num_reads_done` as a transaction completes (despite stats description saying “issued”).
- Mean per-channel row-hit fraction: 32177/32768 = **98.20%**, consistent with sequential locality. All four channels carry equal reads.
- At fixed `500000` cycles and `tCK = 0.3125 ns`, total simulated time = **156.25 us**. Thus 16 MiB / 156.25 us = **107.374 GB/s**, only **52.43%** of the nominal 204.8 GB/s reference. **This is not evidence of a 107 GB/s sustainable ceiling:** extra cycles after trace completion are included. DRAMsim3 `SimpleStats::UpdateFinalStats` computes BW using `num_cycles*tCK`.
- Theoretical minimum full-transfer time: `16 MiB / 204.8 GB/s = 81.92 us = 262144 cycles`; actual completed-workload time is >= this but **not yet measured**.
- `main.cc` stops after exactly `-c` cycles. **Next:** rerun `-c 300000` (and adjust up/down based on completion counts), then establish the earliest fully complete cycle and measure corresponding BW. Preserve separate results directories per candidate cycle budget.
- This is a bandwidth-validation **test mapping**, not the final FACIL mapping. Full LPDDR5 protocol fidelity remains unsupported; continue to label as an approximation.


## 2C. Follow-up sequential read: 300,000-cycle run (21 Oct 2026)

**User-supplied results** for the same `LPDDR5_6400_APPROX_v1.ini` and `personB/traces/sequential_16MiB.trace`, command:

```bash
./build/dramsim3main configs/LPDDR5_6400_APPROX_v1.ini \
  -t personB/traces/sequential_16MiB.trace -c 300000 \
  -o personB/results/sequential_300k
```

| Channel | Completed reads | Average bandwidth (GB/s) |
|---|---:|---:|
| 0 | 20,819 | 28.4249 |
| 1 | 20,819 | 28.4249 |
| 2 | 20,819 | 28.4249 |
| 3 | 20,818 | 28.4235 |
| **Total** | **83,275** | **113.6982** |

- **63.53%** of 131,072 submitted read transactions completed at 300,000 cycles; **47,797 still incomplete**. The near-equal four-channel distribution persists.
- This aggregate 113.6982 GB/s is **throughput over a truncated 300,000-cycle interval**, not the bandwidth for the completed 16 MiB workload.
- Previously at 500,000 cycles all 131,072 reads had completed, with 107.374 GB/s averaged over the full fixed 500,000-cycle interval. Hence the first full completion cycle is somewhere **after 300,000 and at or before 500,000**. No exact completion latency has yet been measured.
- **Next experiment:** test `-c 450000`, recording all channels' `num_reads_done`. If all complete, reduce to 400,000; otherwise test 475,000; continue bisection to find the shortest interval with all 131,072 done, ideally implementing an auto-draining trace runner later. Preserve result directories for each run.
- Still **not validated LPDDR5 bandwidth**: present configuration is an LPDDR4 protocol approximation with selected LPDDR5-style timing settings, and effective bandwidth must not be force-fit to the Jetson 204.8 GB/s theoretical peak.

## 3. Key corrections and decisions

**D1. DDR4 is a smoke test only.** Its output is not an LPDDR5 performance result.

**D2. Agreed modeling mode: timing approximation, not native LPDDR5.** Native LPDDR5 cannot be obtained just by copying an `.ini`. `configs/LPDDR4_8Gb_x16_2400.ini` has `protocol = LPDDR4`. Changing that to `LPDDR5` will trigger the unsupported-protocol path in stock DRAMsim3. Keeping `LPDDR4` while changing numbers is a **LPDDR4-protocol timing approximation**, not verified LPDDR5. To claim native LPDDR5, add/validate the necessary C++ protocol/timing/command behavior or adopt an approved LPDDR5-capable implementation. The user has chosen the approximation; check instructor expectations before claiming compliance with any strict protocol requirement.

**D3. The 204.8 GB/s value is an upper bound/reference, not an optimization target to force.** Jetson reference: 6400 MT/s × 256 bits / 8 = 204.8 GB/s theoretical peak external bandwidth. A long sequential read may approach some fraction of this depending on request stream, protocol/controller assumptions, bank balance, efficiency, and refresh. Measure transaction bytes / completed elapsed time and verify it does not exceed the appropriately configured peak.

**D4. Exact simulator stop condition matters.** DRAMsim3's CLI `-c` sets a fixed number of cycles. Benchmark latency requires confirming completion of all requests and capturing total cycles; if stock trace runner does not drain all submitted traffic, modify/wrap it carefully and record the exact method. Don't treat `-c` as execution latency.

**D5. TTFT is a prefill metric.** For the static hybrid: `TTFT_baseline ≈ T_prefill_GEMM + T_relayout` (plus common overheads). For FACIL: `TTFT_FACIL ≈ T_prefill_GEMM_under_FACIL` (plus common overheads). Do not add ordinary **decode** PIM GEMV to TTFT. Decode PIM GEMV belongs in the separate TTLT model; prefill dynamically offloaded to PIM is a different case.

**D6. Do not treat a DRAM memory trace as full PIM inference execution.** DRAMsim3 alone doesn't model all near-bank PIM compute, communication, or reduction costs. Disclose analytical assumptions.

## 4. Source anchors / validation targets

| Check | Reference | Interpretation |
|---|---|---|
| Jetson memory | LPDDR5-6400; 256-bit interface; 204.8 GB/s | FACIL paper Table II (PDF p. 9); theoretical peak |
| Model | Llama3-8B FP16 (~16.2 GB weights in the paper's model-size discussion) | Full-scale reference; reduced tests use stated dimensions |
| Weight matrix dimensions | e.g. 4096×4096 and 4096×14336, plus paper Figure 10 MapID test shapes | Verify bytes, mapping, partition cases |
| Relative latency | Paper Figure 6: roughly 100 ms without re-layout vs 300 ms with re-layout for Jetson in shown cases | Historical paper result, **not** an unconditional target for reduced-scale model |
| TTFT trend | Paper Figure 13: FACIL benefit generally declines as prefill length grows | Explain departures |
| TTLT trend | Paper Figure 14: decode length increasingly amortizes prefill saving | Requires explicit decode/PIM model |
| Expected MapIDs | PDF Figure 10: 2K×8K FP16 → 3; 2K×64K FP16 → 5 | Person A's mapping selector tests |

## 5. Immediate next actions

### Memory configuration / validation owner (coordinate with Person A/B)
- [ ] Inspect the local LPDDR4 config as a **reference**: `sed -n '1,120p' configs/LPDDR4_8Gb_x16_2400.ini`.
- [ ] Verify source-level protocol support: `sed -n '/DRAMProtocol Config::GetDRAMProtocol/,/^}/p' src/configuration.cc`.
- [x] User selected (A): LPDDR4-protocol + *LPDDR5-6400 timing approximation*, clearly labeled; professor protocol-compliance approval still unverified.
- [ ] Gather timing values from trustworthy JEDEC/manufacturer documentation, and document units, tCK/clock-domain assumptions, burst lengths, geometry and source for every change.
- [ ] Create a **copy** of the reference config only when the modeling method is decided; preserve stock config.
- [x] Derive the 204.8 GB/s reference and verify all 131,072 reads completed evenly across channels in the 500,000-cycle run.
- [ ] Determine earliest actual completion cycle and measure completed-workload throughput; do not force peak match through undocumented parameter tweaking.

### Person B — workload + evaluation
- [ ] Inspect DDR4 smoke test stats and verify requests completed.
- [x] Generate and run a 16 MiB 128-byte-aligned *sequential validation* read trace (131072/131072 reads completed).
- [ ] Generate small FP16 matrix read traces and a matched re-layout read/write trace; count expected transaction bytes.
- [ ] Implement accurate completed-workload duration measurement and throughput checks.
- [ ] Apply the approved memory timing/configuration (native or explicitly approximate).
- [ ] Integrate Person A's mapper: identical logical addresses → layout-specific DRAM addresses; validate no aliases/out-of-bounds.
- [ ] Run baseline, FACIL, and extension with matched hardware and comparable workloads.
- [ ] Produce re-layout cost, TTFT vs prefill, and TTLT trend plots with assumptions.

### Person A — mapping + correctness
- [ ] Implement FACIL MapID selector from paper Figure 9 and address translation from Figure 8.
- [ ] Test MapID 3 and 5 examples in Figure 10, chunk locality, bank/row distribution, reversibility/no collisions.
- [ ] Define the mapping interface used by Person B's trace generator.
- [ ] Implement a legal, evaluated extension—not just a proposal.

## 6. Future experiment log template

Copy this mini-record for each run:

```text
### YYYY-MM-DD — Experiment <name>
Owner:
Git/source version:
Config file + hash:
Model type: native LPDDR5 / approximation / smoke test
Workload (matrix, dtype, prefill/decode lengths):
Trace: transaction size, reads, writes, arrival policy
Command:
Request count submitted / completed:
Elapsed cycles, clock assumption, effective bandwidth:
Row hits/conflicts, ACT/PRE counts:
Result and comparison:
Unexpected issues:
Next action:
```

## 7. Limitations and open questions

- Stock DRAMsim3 checkout does not directly support `protocol = LPDDR5`. **Open, high priority.**
- LPDDR5 CK/WCK and burst behavior must be distinguished from copying LPDDR4 timing numbers. **Open.**
- Full Jetson bandwidth depends on correctly representing channels and aggregate width; do not assume a single 256-bit `bus_width` setting means correct architecture. **Open.**
- Paper uses a modified DRAMsim-based PIM simulator; normal DRAMsim3 misses near-bank compute. **Declare analytical model.**
- Actual completed-workload cycle methodology remains to be verified. **Open.**
- Original mapping extension may not improve every workload; choose held-out workload mixes and report negative results honestly.

## 8. References

- FACIL paper supplied in project chat: Figures 6, 8–10, 13–14; Table II.
- Official DRAMsim3: https://github.com/umd-memsys/DRAMsim3
- DRAMsim3 LPDDR4 sample config: https://github.com/umd-memsys/DRAMsim3/blob/master/configs/LPDDR4_8Gb_x16_2400.ini
- DRAMsim3 protocol parser: https://github.com/umd-memsys/DRAMsim3/blob/master/src/configuration.cc

---
*Project log v1.1 — milestones remain unverified until results are shared.*

## 9. Decision update — 21 October 2026 (latest)

**User decision:** proceed with an approximation instead of implementing a native LPDDR5 protocol.

**Model name for reports:** `DRAMsim3 LPDDR4-protocol proxy calibrated to selected LPDDR5-6400 timing parameters` (not native LPDDR5). Preserve the original sample `.ini`.

**Next steps:**
1. Build a *separate* config with LPDDR4 protocol still selected, and distinguish effective simulator tick from true LPDDR5 CK/WCK. For 6400 MT/s using DRAMsim3's DDR-style two transfers per tick, the effective tick is 0.3125 ns, which is NOT LPDDR5 command clock (1.25 ns at 4:1 WCK:CK).
2. Convert documented LPDDR5 timings (in ns) into *effective simulator cycles*, separately identifying unsupported/approximated fields. Representative source: gem5's `LPDDR5_6400_1x16_BG_BL16`, and its inherited LPDDR5 timings; inspect correspondence before transfer.
3. Aim for 256 bits aggregate modeled interface, e.g. 4 × 64-bit DRAMsim3 channels for a simplified 204.8 GB/s theoretical peak. Confirm mapping and DRAMsim3 geometry rather than forcing a measured 204.8 GB/s.
4. Run a smoke test, count completed read/write transactions, inspect rates for physical plausibility; instrument a drain-to-completion run for final timing.
5. Add limitations: no native LPDDR5 WCK/CK separation, no complete LPDDR5 protocol command behavior, approximated timing parameters, reduced hardware scale.

**Evidence in this chat:** user-provided `configs/LPDDR4_8Gb_x16_2400.ini` and local parser confirmed absent LPDDR5 protocol; user explicitly selected approximation. No validated converted config or benchmarking result yet.

**Source:** https://github.com/gem5/gem5/blob/stable/src/python/gem5/components/memory/dram_interfaces/lpddr5.py

## 21 October 2026 — Person B: 475k-cycle sequential run (user-verified output)

**Configuration:** `configs/LPDDR5_6400_APPROX_v1.ini` (LPDDR4-protocol proxy with selected LPDDR5-style timings; 4 modeled channels x 64-bit; 128-byte transaction; `tCK=0.3125 ns`). **Trace:** `personB/traces/sequential_16MiB.trace`, 131,072 reads (16 MiB), read arrival cycle = transaction index.

**Observed (user reports this is the 475,000-cycle run; screenshot shows results directory `sequential_475k`):**

| Channel | `num_reads_done` | `average_bandwidth` |
|---|---:|---:|
| 0 | 32,768 | 28.2564 GB/s |
| 1 | 32,768 | 28.2564 GB/s |
| 2 | 32,768 | 28.2564 GB/s |
| 3 | 32,768 | 28.2564 GB/s |
| **Total** | **131,072 (all)** | **113.0256 GB/s** |

**Interpretation:** at or before 475,000 simulated ticks, all read requests have completed; 475k is **an upper bound**, not the exact last-request completion cycle. The 113.03 GB/s estimate still averages over the entire fixed-cycle window and may include an idle tail. Earlier 300k run was incomplete (20,819/20,819/20,819/20,818 per channel; 83,275 total), and 500k was complete. Need further bracket (next check: 450k, then narrow) or implement stop-on-trace-drained measurement. Do **not** tune timings to force measured bandwidth to 204.8 GB/s; 204.8 is theoretical peak and protocol remains approximate. No proof of full LPDDR5 correctness.

**Next:** (1) test 450k cycles; (2) bracket completion cycle and/or add callback-driven termination; (3) verify delivered bytes and effective bandwidth; (4) begin baseline read/write re-layout trace generation after timing validation.

## 21 October 2026 — Person B: 450k result; stop manual cycle search

**Latest user-provided result, same config and 16 MiB sequential READ trace:**

| Budget (cycles) | Reads completed ch0/ch1/ch2/ch3 | Total reads | Status | Aggregate `average_bandwidth` |
|---|---|---:|---|---:|
| 300,000 | 20,819 / 20,819 / 20,819 / 20,818 | 83,275 | Incomplete | ~113.698 GB/s |
| 450,000 | 31,170 / 31,170 / 31,170 / 31,169 | 124,679 | **Incomplete: 6,393 remain** | ~113.485 GB/s |
| 475,000 | 32,768 each | 131,072 | **All completed** | 113.0256 GB/s |

**Verified:** 450k run was successfully executed but did *not* finish all memory requests; all requests were complete by 475k. Therefore true last-read completion lies within (450,000, 475,000] simulation ticks. At a modeled `tCK=0.3125 ns`, that is (140.625, 148.4375] microseconds, before accounting for any trace-injection conventions. The average bandwidth is ~113 GB/s in this trace/config, approximately 55% of the 204.8 GB/s theoretical interface limit. Changing `-c` alone will **not** improve physical DRAM throughput; the ~0.5% variation reflects the counting window and how many requests have completed.

**Decision:** Stop manually sweeping cycle limits just to chase a higher bandwidth. Save these values as preliminary saturation sanity-check evidence. Build repeatable instrumentation to stop once trace EOF has been reached *and* outstanding transactions have completed before final publication. Investigate protocol proxy timing and scheduling separately if needed; do not tune arbitrary timings to make measured throughput equal theoretical peak.

**Next substantive task for Person B:** Generate and verify a paired read + write re-layout workload (one copy of PIM-layout weights read and a separate conventional-layout buffer written, no aliasing); validate number of bursts and moved bytes. Compare with FACIL case with no on-demand re-layout. Get mapping/physical address conventions from Person A. Label this as copy-traffic estimate, not full measured SoC/GPU/GEMV performance. Preserve the LPDDR4-protocol proxy limitation.

## 2026-10-21 — Person B baseline copy-traffic scripts prepared (not yet WSL-verified)

**New source files (assistant-created, syntax-tested):** `personB/generate_relayout_trace.py`, `personB/measure_relayout.py` (distributed as `facil_personB_starter.zip`). User still needs to place them inside WSL repo and run actual DRAMsim3.

**Default experimental workload:** 512 × 1024 × FP16 = 1,048,576 B (1 MiB); DRAM transaction 128 B. Generated source read trace = 8,192 READs from `0x0`, scratch write trace = 8,192 WRITEs from `0x10000000`; nonoverlapping aligned addresses; total nominal copy traffic 2,097,152 B (2 MiB). Each trace has its own arrivals (0..8191 cycles) and simulation.

**Timing method:** independent DRAMsim3 runs for the read stage and the write stage, with automated bracketing/binary-search of first cycle budget at which all transactions finish (256-cycle resolution). Sum stage times to obtain a **serialized DRAM-only copy proxy**. The source scripts passed Python compilation and a local synthetic simulator test; this is **not** a verified result from the user's DRAMsim3.

**Scientific caveats:** NOT a full matrix element layout conversion: Person A must provide actual logical→physical mapping. Separate stages omit read/write pipelining and CPU/GPU shuffle, so combined time is not generally a reliable upper or lower bound for true re-layout. Do not infer paper's headline TTFT speedup or full-end-to-end latency from this number alone. Memory model remains LPDDR4 protocol with LPDDR5-style selected timing values, not native LPDDR5.

**Next user action:** copy two scripts into `personB/`, run generator and automated benchmark, paste terminal output plus `summary.json`. Next integration: Person A's mapper makes read and destination write addresses represent genuinely different placements for the same logical matrix values, test permutations/no aliasing, then compare actual baseline with FACIL under consistent SoC access assumptions.

## 2026-10-21 — Person B: re-layout traffic proxy executed successfully in WSL

**User-confirmed command outputs:**
- `python3 personB/generate_relayout_trace.py` generated a 512 × 1024 FP16 matrix workload: 1,048,576 bytes of weights; 128-byte modeled memory transactions; 8,192 READ requests and 8,192 WRITE requests in separate traces, for total nominal copy traffic of 2,097,152 bytes (2 MiB).
- `python3 personB/measure_relayout.py` successfully executed both stages with `configs/LPDDR5_6400_APPROX_v1.ini` (`tCK = 0.3125 ns`).
- **READ:** 8,192/8,192 completed; completion <=29,952 cycles (256-cycle bracket); elapsed <=9.360 μs; average effective bandwidth >=112.027 GB/s.
- **WRITE:** 8,192/8,192 completed; completion <=29,184 cycles (256-cycle bracket); elapsed <=9.120 μs; average effective bandwidth >=114.975 GB/s.
- **Sum of independent serialized DRAM stages:** <=18.480 μs. Raw user result at `personB/results/relayout_v1/summary.json`; statistics for `read/` and `write/`.

**Validation status:** PASS (script runs and transaction accounting matches expected), but **not yet a faithful physical PIM-layout-to-SoC-layout conversion**, FACIL controller measurement, LPDDR5 protocol implementation, TTFT measurement, or measured end-to-end re-layout. The sum is an upper bound **only for the separate simulated stage completion windows**; it is neither a guaranteed upper nor lower bound for real CPU/GPU-mediated re-layout because compute/rearrangement and read/write overlap are both absent. The reported tCK is a chosen equivalent proxy tick, not native LPDDR5 command-clock behavior.

**Next Person B actions:**
1. Freeze baseline run and validate source/destination addresses from `personB/traces/relayout/manifest.json` and transaction counts from stats.
2. Sweep several matrix sizes (0.5, 1, 2, 4 MiB) under the same config and script; produce copy-time-versus-weight-size graph. Keep completion-bound and bandwidth numbers together.
3. Person A integration contract: per logical tensor element/transaction, map the same data consistently to physical DRAM coordinates for PIM and conventional views; validate no collisions and that PIM mapping preserves required chunk/bank placement before running the comparison.
4. For a fair FACIL comparison, use identical GEMM access/workload and charge baseline for re-layout while FACIL uses original weights; model layout-induced GEMM penalty explicitly if claimed. Keep PIM decode GEMV outside TTFT; include it in TTLT model.
5. Retain 204.8 GB/s LPDDR5-6400 (256-bit) as theoretical Jetson benchmark, **not** as measured throughput or target to tune until matched.


## 2026-10-21 — Person B: four-size serialized copy proxy sweep (user-verified)

**Command:** For `256x1024`, `1024x1024`, `2048x1024`, run `generate_relayout_trace.py --rows ... --cols ... --output personB/traces/relayout_<shape>` followed by `measure_relayout.py --trace-dir ... --results personB/results/relayout_<shape>`. Initial `512x1024` run already recorded above.

**Fixed setup:** FP16, 128-byte transactions, four simulated channels, DRAMsim3 LPDDR4-protocol/selected-LPDDR5-timing proxy `LPDDR5_6400_APPROX_v1.ini`; separate complete-read then complete-write traces, with 256-cycle resolution on each completion upper bound.

| Matrix shape | Weight MiB | Read requests | Write requests | READ upper bound (us) | WRITE upper bound (us) | Sum (us) |
|---|---:|---:|---:|---:|---:|---:|
| 256x1024 | 0.5 | 4,096 | 4,096 | 4.800 | 4.560 | 9.360 |
| 512x1024 | 1 | 8,192 | 8,192 | 9.360 | 9.120 | 18.480 |
| 1024x1024 | 2 | 16,384 | 16,384 | 18.800 | 18.160 | 36.960 |
| 2048x1024 | 4 | 32,768 | 32,768 | 37.360 | 36.320 | 73.680 |

**Traffic:** total read+write bytes = 1,048,576 / 2,097,152 / 4,194,304 / 8,388,608, respectively. User's terminal shows complete request accounting for every stage and the `summary.json` output paths.

**Interpretation:** approximately linear scaling (doubling weight doubles serialized DRAM-only copy-time bound); read-stage bandwidth approximately 109–112 GB/s and write-stage approximately 115 GB/s under this configuration. Both read/write streams are synthetic and do not model the actual intra-page weight permutation or SoC GPU shuffle. This is **not** yet a quantitative FACIL speedup or native LPDDR5 fidelity validation.

**Person B next actions:** (1) save copy-time-vs-matrix-size plot from `summary.json`, (2) implement a separate prefill-only TTFT analytical framework using the 204.8 GB/s Jetson theoretical limit as a sanity reference, and (3) align trace/geometry contract with Person A's tested MapID mapping. Preserve source config, output directories and manifests.

## 2026-10-21 — Person A mapper + Person B TTFT scenario starter prepared (assistant-side, not yet run in user's WSL)

**Prepared artifacts:** `FACIL_A_B_Implementation_Kit.zip` containing `personA/facil_mapper.py`, `personA/visualize_mapper.py`, `personB/ttft_model.py`, mapper/TTFT unit tests, and reference figures/analytical preview. Existing DRAMsim3 config/trace scripts are preserved; only new files are added when extracted.

**Assistant-side verification:** 13 Python unit tests passed, including MapID=3 (2K×8K) and MapID=5 (2K×64K) under Fig. 10 geometry; physical bit-field decode/encode round-trip and no alias at 128-byte trace granularity for one and two huge pages using different MapIDs; 2 KiB chunk row confinement; row splitting for oversize matrices; Fig. 8's 32B transfer decomposition. Not verified against the user's DRAMsim3 decoder. The Kit's TTFT preview was calculated using **user-reported actual copy proxy** 18.48 µs from 1 MiB 512×1024 FP16, and **analytical (not measured) Jetson reference** 204.8 GB/s / 42.5 TFLOPS. It deliberately excludes decode GEMV from TTFT.

**Needs user confirmation:** Extract ZIP into WSL repo, run test suite, inspect output of `personA/facil_mapper.py`, run `personB/ttft_model.py` against the *actual* `personB/results/relayout_v1/summary.json`, then paste result table. Person A/Person B integration is **not** complete yet: no verified DRAMsim3 MapID-aware mapping or PIM compute. Extension unimplemented.
