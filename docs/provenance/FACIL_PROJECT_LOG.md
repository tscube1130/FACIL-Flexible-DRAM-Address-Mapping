# FACIL Project — Running Log

**Current verified baseline (2026-10-23):** K/V 1024×4096 FP16; corrected 2-KiB aggregate bank rows (`rows=262144`, `columns=256`), LPDDR4-protocol / LPDDR5-style timing proxy, trace-reader EOF fix verified. Mapped PIM source READ: **65,536/65,536, ≤184.560 µs**; conventional destination WRITE: **65,536/65,536, ≤41.120 µs**; serialized DRAM-only copy completion upper-bracket sum: **≤225.680 µs**. Exactly zero unintended opposite-type transactions reported. **All older 8-KiB-geometry timing figures are superseded as current baseline evidence and must not be aggregated with this run.** Q/O and both FFN categories under this final configuration: **PENDING**. FACIL mapped SoC read timing on this revised config: **PENDING**. End-to-end TTFT: **PENDING**.

**Source of current result:** user's terminal output pasted in chat, 23 Oct 2026. The original `summary.json`, `manifest.json`, hashes and raw simulator statistics are in the user's WSL repository and have **not been uploaded in this turn**. This log is a working copy and does **not automatically update the user's WSL files or live Overleaf project**.

---


**Started:** 21 October 2026  
**Last updated:** 22 October 2026 (K/V baseline functional verification + traffic run)  
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


## 2026-10-21 — Baseline-versus-FACIL extra-copy CSV generated (user-confirmed)

**User terminal evidence:** `python3` created `personB/results/baseline_vs_facil_copy.csv`. Console printed four records and `Saved: personB/results/baseline_vs_facil_copy.csv`; screenshot saved in `06_Screenshots_Evidence/14_baseline_vs_facil_copy_csv.png`.

| Matrix MiB | baseline_copy_upper_us | facil_extra_copy_us | avoided_copy_upper_us |
|---:|---:|---:|---:|
| 0.5 | 9.36 | 0.0 | 9.36 |
| 1.0 | 18.48 | 0.0 | 18.48 |
| 2.0 | 36.96 | 0.0 | 36.96 |
| 4.0 | 73.68 | 0.0 | 73.68 |

The nonzero baseline column is transcribed from DRAMsim3-derived serialized read/write estimates, which are **completion-window upper bounds for the synthetic trace stages**, not actual full PIM-to-SoC data permutation. FACIL's zero extra copy is **a design assumption**, not a DRAMsim3 measurement. The avoided-copy numbers are scenario estimates, NOT actual FACIL memory-system speedups. No second end-to-end FACIL run took place.

**Next task:** parameterize an analytical AiM-style PIM GEMV model for one small FP16 workload and run sensitivity to unspecified per-chunk latency. Use output for explicitly modeled one-token prefill linear-component time or decode/TTLT, not as a measured full LLM TTFT. The assistant created a **demonstration-only** model `07_Source_Snapshots/personB/pim_gemv_analytical.py` with assumed timing scenarios; user has not run it in WSL yet.

## 2026-10-21 — User-confirmed PIM GEMV run and Person A paper audit

**User WSL execution:** `python3 personB/pim_gemv_analytical.py --chunk-ns 50 100 200 --out personB/results/pim_gemv_analytical` completed, generating CSV and JSON under `personB/results/pim_gemv_analytical/`. Screenshot saved in `06_Screenshots_Evidence/15_pim_gemv_user_terminal_2026-10-21.png`.

| Hypothetical chunk service | Linear-only modeled time | Waves | Assumed PUs |
|---:|---:|---:|---:|
| 50 ns | 0.735 μs | 12 | 128 |
| 100 ns | 1.335 μs | 12 | 128 |
| 200 ns | 2.535 μs | 12 | 128 |

Workload: 1024→512→1024 FP16 two-layer MLP, one token; total weights 2 MiB. The vector-transfer term is ~0.135 μs, modeled at theoretical external peak 204.8 GB/s; PUs = 4 channels × 2 ranks × 16 banks. **These are analytical sensitivity values, NOT measured PIM performance or model TTFT.** Timings (50, 100, 200 ns) hypothetical; missing command/control, input-register contention, reduction, nonlinear operations and other inference components.

**Person A cross-check with paper Figs. 8–10:** Figure 10 geometry (2 channels, 1 rank, 16 banks/channel, chunk 1×1024 FP16, 2 MiB huge page, 32B physical transfer): 2K×8K→MapID 3 (row remains in one PU), 2K×64K→MapID 5 (128 KiB row splits across two PUs). User-uploaded figures and source mapping match paper examples; previously 13 WSL unit tests passed. Paper-style 32B transfers are distinct from the 128B trace transactions of Person B's DRAMsim3 proxy. This is independent source/model review, not actual hardware validation.

**Cross-track limitation:** The current Person A `choose_mapid()` raises for `cols < 1024`, but the second PIM-model layer has K=512; the PIM time estimator accepts 512 as a partial chunk and bills one wave. Before treating these as one consistent mapping/performance experiment, ask user whether to (a) add explicit padding/partial-chunk support or (b) choose matrices with K≥1024. No change decided yet.

## 2026-10-21 — Person A full-chunk placement audit (assistant-side dry run)

- Built `personA/validate_placement.py` against the user-uploaded `facil_mapper.py` without editing the original.
- Anchored Fig. 10 MapIDs 3 and 5 and tested Llama3-8B shapes against 4 channels, 2 ranks/channel, 16 banks/rank and 2 MiB huge pages.
- All 135,168 checked chunks passed 2 KiB row/PU confinement per chunk, 128-byte transaction containment, round trip, and uniqueness checks. Nonpartitioned rows each use one PU.
- For 4096x14336 (MapID=3) with compact 28 KiB logical rows: 2048 rows touch 2 PUs; 2048 rows touch 3 PUs; 48 rows cross a 2 MiB huge-page boundary.
- This **does not** establish lock-step PIM execution or native LPDDR5; the treatment of a 28 KiB row vs 32 KiB rounded selector length remains open.
- The user still needs to run the delivered validator on their WSL copy and share output. Audit note in `STEP1_AUDIT_NOTES.md`.

---

## 2026-10-22 — Verified map placement and candidate row-alignment study

Evidence: user's WSL terminal and uploaded `summary.json`, `terminal_output.txt`, `sampled_row_placement.csv` (snapshots included under `evidence/`). **Original source not modified by reported tests.**

### Person A full-shape placement audit

- Geometry: 4 channels x 2 ranks/channel x 16 banks/rank, 2MiB huge page, FP16, AiM chunk (1,1024).
- Paper Figure 10 anchors: MapID 3 for 2Kx8K and MapID 5 for 2Kx64K, under 2 channels / 1 rank / 16 banks.
- Four evaluated shapes: Q/O 4096x4096 -> MapID2; K/V 1024x4096 -> MapID2; FFN gate/up 14336x4096 -> MapID2; FFN down 4096x14336 -> MapID3 partition=True.
- PIM chunks verified 16,384 + 4,096 + 57,344 + 57,344 = **135,168**; WSL unit tests: **13 passed**.
- Down-projection compact FFN shape: 2,048 logical rows touch 2 PUs, 2,048 rows touch 3; 48 rows cross 2MiB huge pages. Sampled numerical chunk-local GEMV reduction matched normal dot products for 8 rows.

### Original tested extension: optional power-of-two row-stride alignment

- Original mapper hash as recorded in uploaded results: `c7c4969a8f60220bffdfa79ac2f288016366c3da2ecb32385be1f877e46ba000`.
- Matrix: 4096x14336 FP16, MapID3. Compact stride 14336 elements = 28KiB; padded candidate stride 16384 elements = 32KiB.
- Compact footprint **112MiB**; padded footprint **128MiB** (+16MiB; +14.2857%).
- Compact rows start at within-PU chunk offsets 0/2/4/6, 1024 rows each; padded rows start at offset 0 for all 4096 rows.
- Compact PU/row histogram `{2:2048, 3:2048}`, padded `{2:4096}`; compact rows crossing pages 48, padded 0; compact rows spanning multiple ranks/banks 1536, padded 0.
- 57,344 PIM chunks checked per layout, all PASS. NumPy strided numerical check PASS on 16 rows; standard `libblas.so.3` FP32 SGEMM with `lda=16384`, sample M=16, N=1, K=14336 reported `max_abs_error=0.0`; using compact `lda` on padded memory fails expected negative-control compatibility check.
- **Inference and limitation:** alignment regularity improves but full SoC transparency of FACIL is not proved, because padded access requires a non-default leading dimension. PIM scheduling speedup unmeasured. Paper does not explicitly mandate padding.

### Overleaf paper milestone

- Authored four-page IEEEtran PDF and complete compilable LaTeX source with verified method, evidence-backed tables and figures; red pending markers for missing full-sized simulations and calibrated TTFT.
- Created single Overleaf ZIP and command/evidence files for updating the manuscript as new WSL runs arrive.
- Paper methodology clearly discloses LPDDR4-protocol LPDDR5-style timing proxy, 32B vs 128B granularity, lack of MapID integration into DRAMsim3, serialized traffic limitation, and no real PIM GEMV performance.

### Next

1. Run DRAMsim3 baseline traffic proxy for **real** Llama3-8B Q/O shape 4096x4096 (32MiB), then K/V and both FFN shapes.
2. Archive each `summary.json`, `input_manifest.json`, `terminal_output.txt`, `.ini` hash, and completion evidence.
3. Resolve full baseline data conversion cost rather than calling the copy proxy a complete re-layout; specify actual address layout if adding a permutation-aware trace.
4. Ground analytical PIM GEMV timing with paper hardware parameters and documented missing timing variables, and calculate full prefill TTFT for baseline and FACIL with sensitivity.
5. Evaluate extension tradeoff against validated mapping baseline and clearly separate performance from placement metrics.


## 2026-10-22 — Manuscript packaging, model-scale accounting, and next run

- Verified existing IEEEtran Overleaf manuscript source at `main.tex` and locally compiled `main.pdf`; present draft is not yet on the user's Overleaf account. Explicitly pending results remain marked red, and final author/contribution lines remain placeholders.
- Added reproducible `tools/llama3_workload_accounting.py`; for the standard Llama3-8B 32-block configuration and the four previously validated FP16 shapes, each block has 7 dense linear matrices: Q/O 2x32 MiB, K/V 2x8 MiB, FFN gate/up 2x112 MiB, FFN down 1x112 MiB; total **416 MiB per block, 13.0 GiB** of enumerated linear weights (excluding embeddings, output head, cache and other tensors). The read+write baseline transaction volume for one conversion of each of those matrices is **26 GiB**. At paper Table II's 204.8 GB/s reference external theoretical peak, the ideal bus-only transfer service floor is **136.315 ms**; it is explicitly NOT a DRAMsim3 result or TTFT prediction. These numbers are derived from shapes; script results in `evidence/llama3_workload_accounting.json` and `.csv`.
- Added report subsection on the full-size byte budget and clarified that the *original paper itself* estimates baseline re-layout using DRAM-only read/write accesses and excludes in-page reordering. Our serialized stages are a separately disclosed approximation; not the original simulator.
- Next measured result required from user WSL: execute Q/O 4096x4096 under the existing DRAMsim3 binary and `configs/LPDDR5_6400_APPROX_v1.ini` via `tools/RUN_LLAMAx_DRAMSIM3.sh` (using `personB` scripts), and return `summary.json` plus manifest and terminal output. When Q/O completes, repeat K/V, gate/up, down. The assistant does not possess live WSL DRAMsim3 execution evidence and will not fabricate measurement numbers.
- `records/FACIL_PROJECT_LOG.md` is maintained as a versioned artifact; it is NOT automatically synced with WSL or Overleaf. Append or bring back each new result for the next update.


## 2026-10-22 — First user-run full-sized Llama3-8B baseline DRAMsim3 result: Q/O

**Source files received:** `terminal_output(1).txt`, `input_manifest.json`, `summary(1).json`, copied into the canonical draft under `evidence/fullsize_runs/llama3_q_o/` using unmodified contents. Cross-validated all byte counts, stage-completion counts, 0.3125-ns clock conversion, and serialized sum. This is **the user's WSL run**, not an assistant-side simulation.

- Actual workload: Q/O projection weight matrix 4096x4096 FP16, exactly 33,554,432 bytes (**32 MiB**); sequential read from `[0x0, 0x2000000)`, sequential write to `[0x10000000,0x12000000)`; **64 MiB** of combined read/write traffic.
- Trace granularity **128 B**, exactly **262,144** completed transactions per stage (524,288 combined).
- DRAMsim3 configuration reported: `configs/LPDDR5_6400_APPROX_v1.ini`, LPDDR4 protocol with LPDDR5-6400-style timing proxy; **tCK = 0.3125 ns**. This is not native LPDDR5.
- READ: 944,640 cycle completion **upper bound**, **<= 295.200 us**, effective bandwidth **>= 113.6668 GB/s**.
- WRITE: 930,304 cycle completion **upper bound**, **<= 290.720 us**, effective bandwidth **>= 115.4184 GB/s**.
- Serialized READ + WRITE proxy: **<= 585.920 us** (256-cycle completion-search resolution, 0.080 us per stage). This is *not* an actual per-page permutation, CPU/GPU conversion kernel, overlapping pipeline, full model inference, TTFT or native LPDDR5 measurement. The zero extra FACIL relayout term is mechanistic, not another measured run.
- Source/config SHA256 and DRAMsim3 raw simulator statistics files **not yet received**; user should preserve `source_sha256.txt`, `read/dramsim3.txt`, `write/dramsim3.txt` in WSL.
- **Manuscript updated:** the abstract, full-sized Q/O result paragraph, and `tables/llama3_copy_rows.tex` now contain only this verified result. The K/V, gate/up and down timing cells remain missing (`--`).
- **Next:** run K/V 1024x4096 (8 MiB), then FFN gate/up 14336x4096 (112 MiB) and FFN down 4096x14336 (112 MiB), with the same scripts/config; archive output triad and hashes for each. Then paper-grounded analytical PIM GEMV and prefill TTFT with sensitivity.
- **Maintenance:** Keep `records/FACIL_PROJECT_LOG.md` as the one canonical chronology and continue revising `main.tex` as evidence arrives. No new final-paper ZIP is required at this stage.


## 2026-10-22 — K/V baseline traffic and first functional on-demand re-layout test

**Measured baseline copy-traffic (user WSL).** The uploaded files `summary(4).json`, `terminal_output(2).txt`, `input_manifest(3).json` have been archived, unmodified, at `evidence/fullsize_runs/llama3_k_v/`. Actual Llama3-8B K/V shape: 1024x4096 FP16, 8,388,608 B (8 MiB), two separate sequential read/write stages; 65,536 completed 128-B transactions per stage; 16 MiB total transaction bytes. READ: <=237,312 cycles = **<=74.160 us**, bandwidth >=113.115 GB/s. WRITE: <=232,448 cycles = **<=72.640 us**, bandwidth >=115.482 GB/s. Sum of completion upper bounds: **<=146.800 us**, `tCK=0.3125 ns`, completion search resolution 256 cycles, LPDDR4 controller with LPDDR5-6400-style timing proxy. These are *memory-only traffic completion time* values, not complete application re-layout, SoC GEMM, PIM inference or TTFT. Compare prior Q/O 32-MiB <=585.920 us; no extrapolation to model TTFT without the remaining experiments.

**Functional baseline (user terminal output, 22 Oct).** User ran `personB/verify_baseline_relayout.py` and reported `BASELINE RE-LAYOUT CORRECTNESS: PASS` for K/V 1024x4096 FP16, MapID2, source and destination each 8,388,608 bytes; exactly **262,144 individual 32-byte fragments** checked; original conventional row-major matrix byte sequence recovered exactly from a separately permuted software storage representation. This test uses a fixed reference `ROW:RANK:COLUMN:BANK:CHANNEL:OFFSET` physical-storage permutation with PIM coordinate generation supplied by the stand-alone FACIL mapper. This proves functional invertibility and lossless recovery within that *software reference model*. It does not establish that the stock DRAMsim3 decoder implements either proposed hardware mapping or that the simulator executed the permutation, and does not verify PIM cycles. User only supplied terminal text for this functional run; an unmodified script snapshot and raw run log from WSL are not yet in this artifact store.

**Methodological decision.** Finish *baseline* first. To connect the independent functional baseline and sequential copy-traffic proxy, created `personB/generate_baseline_permutation_trace.py` as a separate **permutation-aware first-touch traffic sensitivity experiment**. It visits 32B fragments in logical order, checks a lossless reference PIM-storage permutation, and issues each distinct 128B source storage block once at first touch (an ideal-cache/coalescing assumption); destination scratch writes are sequential. It uses existing `measure_relayout.py` for the same DRAMsim3 run configuration. It DOES NOT install MapID support in DRAMsim3 nor claim its PIM-storage reference permutation is the configured DRAMsim3 decoder. Source order is a demonstrable alternative to the earlier sequential-source trace, not a real hardware baseline latency. No user-run timing for the new trace yet. Previous FACIL selector/placement work remains complete but must not be confused with measured baseline data.

**Next user step.** Copy the new generator into WSL `personB/`, generate K/V trace under `personB/traces/llama3_k_v_permutation`, then run unchanged `personB/measure_relayout.py` to obtain a controlled sequential-versus-first-touch pattern comparison. Archive the new manifest, summary, terminal, simulator output and config hash. The FFN 112-MiB runs, analytical PIM GEMV, full prefill TTFT and extension-performance claims remain pending.


## 2026-10-22 — Baseline K/V permutation-aware DRAMsim3 result (HP desktop)

**User-run success:** `personB/measure_relayout.py --trace-dir personB/traces/llama3_k_v_permutation --results personB/results/llama3_k_v_permutation` completed all read and write requests on the desktop. The uploaded `summary(5).json` is preserved as `evidence/fullsize_runs/llama3_k_v_permutation/summary.json`. Terminal output was pasted in chat and transcribed to an evidence note; the original file and input manifest have not been uploaded.

- Matrix: Llama3-8B K/V projection **1024x4096 FP16 = 8 MiB**. **65,536 128B READs** and **65,536 128B WRITEs**, 16 MiB modeled total traffic.
- Timing proxy: **READ <=480,768 cycles=150.240 us** (BW >=55.835 GB/s); **WRITE <=232,448 cycles=72.640 us** (BW >=115.482 GB/s); **serialized sum <=222.880 us**. Completion-window search has 256-cycle resolution.
- Reference sequential K/V **laptop** report: READ <=74.160 us, WRITE <=72.640 us, serialized sum <=146.800 us. The difference of **+76.080 us / +51.83%** is a comparison of reported completion-window bounds across host workflows, **not yet a controlled same-machine attribution or real copy speedup**. The memory simulation should be deterministic for fixed simulator build/config/traces; request build/config/traces fingerprint and re-run sequential on desktop.
- The permutation-aware reference generator first maps individual 32B logical fragments to standalone PIM-oriented storage positions via Person A's mapper, then emits one READ per unique **128B storage block on first touch** (idealized reuse/coalescing); it emits sequential destination WRITEs. The configured DRAMsim3 decoder has not been verified to implement the standalone PIM/SoC mapping. This is a **baseline traffic-pattern sensitivity experiment**, not a FACIL run, not a true timed data permutation or PIM GEMV.
- Native LPDDR5 remains unsupported by this custom run: configured LPDDR4 protocol with LPDDR5-style timing proxy (`configs/LPDDR5_6400_APPROX_v1.ini`, `tCK=0.3125 ns`).
- Missing provenance: permutation input `manifest.json`, generator/source hashes, exact source traces, original desktop terminal log, simulator binary/config hash. The two earlier FFN 112-MiB baseline traffic cases and final calibrated analytical model remain pending.
- **Next action**: Run the existing sequential K/V trace under the *same desktop build/config*, preserving its original results. Compare times and collect manifest + hashes, then proceed to FFN gate/up and FFN down baseline runs.

## 2026-10-23 — Corrected K/V baseline re-layout traffic (user WSL)

**Decision:** Treat this as the first current baseline measurement. Do **not** combine it with Oct 21--22 timing gathered under `rows=65536`, `columns=1024`, aggregate bank row 8 KiB, or runs made before the EOF trace-reader repair. Those runs remain in this chronology only as historical diagnostics.

**Configuration and prerequisite test evidence (reported by user):**
- Existing `configs/LPDDR5_6400_APPROX_v1.ini` edited in place to `rows=262144`, `columns=256`, `tCK=0.3125 ns`; four 64-bit channels, two ranks/channel, 16 banks/rank, 128B requests, **2 KiB aggregate bank rows** by calculation. Memory capacity unchanged. This is a **synthetic row organization**, not independently verified JEDEC LPDDR5 implementation; DRAMsim3 still executes LPDDR4 protocol commands with selected LPDDR5-style timings.
- The standalone mapper's FACIL/SoC views and baseline PIM-to-conventional byte rearrangement were validated for all four distinct Llama3-8B FP16 layer shapes by a separate software-storage test. This is not hardware PIM compute or installed MapID controller behavior.
- User ran `generate_verified_baseline_traces_2k.py --rows 1024 --cols 4096 --output personB/traces/verified_baseline_k_v_2k`: **PASS**, 65,536 unique source 128B reads and 65,536 conventional writes, 262,144 32B fragments checked; 16,384 source reads in each of 4 channels. Trace generator contains static MapID-to-fixed-decoder encoding, not a dynamically programmable FACIL controller.
- One-WRITE DRAMsim3 EOF regression test initially reported 1 unexpected READ. User applied previously verified trace-reader patch, rebuilt DRAMsim3 and confirmed **0 READ, 1 WRITE**.

**K/V source simulation command (run in user's repo):**

```bash
python3 personB/measure_relayout.py \
  --trace-dir personB/traces/verified_baseline_k_v_2k \
  --results personB/results/verified_baseline_k_v_2k \
  | tee personB/results/verified_baseline_k_v_2k/terminal_output.txt
```

**Observed output (user-supplied terminal text):**

| Stage | Correct transactions | Completion upper bound | Time upper bound | Effective bandwidth lower bound |
|---|---:|---:|---:|---:|
| PIM mapped source READ | 65,536/65,536 | 590,592 cycles | **184.560 µs** | ≥45.45 GB/s |
| Conventional destination WRITE | 65,536/65,536 | 131,584 cycles | **41.120 µs** | ≥204.00 GB/s |
| Serialized sum | 131,072 total operations | stage sums | **225.680 µs** | not defined |

Independent `awk` scan of `personB/results/verified_baseline_k_v_2k/{read,write}/dramsim3.txt` produced: `read: READ=65536 WRITE=0`; `write: READ=0 WRITE=65536`. The `measure_relayout.py` completion-search window is 256 cycles per stage (0.080 µs at 0.3125 ns/cycle), and the serialized sum is **a sum of upper brackets**, not a measured callback timestamp or a rigorous upper bound on CPU-mediated byte permutation. No CPU/GPU data shuffle, GEMM, PIM GEMV, actual MapID controller, or full model inference was measured here.

**Action for paper:** Revised the single evolving IEEE draft `main.tex` to place the corrected K/V result in the current baseline table, mark Q/O and FFN as pending, explicitly describe synthetic 2KiB bank rows and fixed trace decoder, identify the EOF fix, and remove obsolete 8-KiB timing plots/figures from the active manuscript narrative. Historical figures remain in this project log and source archive for provenance, not in the current results section.

**Next technical steps:** Generate corrected-geometry traces for Q/O 4096×4096, FFN gate/up 14336×4096, and FFN down 4096×14336; run each with the fixed executable; verify counts and configs, then run FACIL matched SoC-weight accesses with same logical workload. Keep re-layout cost separate from modeled GEMM/GEMV TTFT and from structural extension results.

**Missing artifacts not to invent:** Full manifest, raw per-stage `dramsim3.txt`, current `summary.json` file, simulator and config hashes from WSL. Terminal values above are traceable to the pasted user output, but the unuploaded files have not been inspected here.

---

## 2026-10-23 — Corrected-geometry baseline completed for Q/O, K/V, FFN gate/up, FFN down (user WSL)

**Status:** Four individual baseline read/write DRAMsim3 traffic experiments completed with the user's corrected `LPDDR5_6400_APPROX_v1.ini` (`rows=262144`, `columns=256`, `tCK=0.3125 ns`), 2-KiB aggregate bank row, LPDDR4 protocol + selected LPDDR5-style timings. All stage-specific completion counts matched trace transaction counts, according to terminal outputs. K/V additionally had independently parsed zero opposite-direction requests. Runs use an EOF-corrected DRAMsim3 trace reader. Synthetic memory organization remains an explicit modeling choice; not native LPDDR5 or installed per-page MapID hardware.

| Shape | Bytes/weight | MapID | READs done | WRITE done | Read upper bracket (us) | Write upper bracket (us) | Serialized sum of upper brackets (us) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q/O 4096x4096 | 32 MiB | 2 | 262,144 | 262,144 | 736.000 | 165.920 | 901.920 |
| K/V 1024x4096 | 8 MiB | 2 | 65,536 | 65,536 | 184.560 | 41.120 | 225.680 |
| FFN gate/up 14336x4096 | 112 MiB | 2 | 917,504 | 917,504 | 2575.300 | 581.910 | 3157.210 |
| FFN down 4096x14336 | 112 MiB | 3 | 917,504 | 917,504 | 4826.080 | 581.910 | 5407.990 |

**Observed FFN script issue and fix:** initial gate/up and down traces passed, but `measure_relayout.py` raised `exceeded 10 million cycles` before completion bracketing. User changed only hard search ceiling to 30,000,000 cycles; unchanged DRAM timings and traces. Both then completed successfully. No old 8-KiB measurements have been pooled into this table.

**32-block calculation** (seven linear matrices/block): per-block serialized sum `2*901.920 + 2*225.680 + 2*3157.210 + 5407.990 = 13,977.610 us`; multiply by 32 = **447,283.520 us = 447.283520 ms**. Separately, per-block READ stage-sum = 11,817.800 us, WRITE stage-sum = 2,159.810 us; full 32-block stage sums = **378.169600 ms READ**, **69.113920 ms WRITE**. This is a sum of DRAMsim3 stage-completion *upper brackets* under sequential, once-per-matrix re-layout assumptions, **not** a measurement or rigorous bound on real CPU/GPU permute-and-copy, or actual end-to-end TTFT. Paper used a DRAM-only copy estimate; current timing proxy uses static encoded MapID traces to submit DRAMsim3 requests. User sent terminal printouts, not all raw `summary.json`, `dramsim3.txt`, manifest, SHA hashes; archive those before finalizing provenance.

## 2026-10-23 — Analytical SoC prefill GEMM model implemented and self-checked (assistant runtime)

**Artifact:** `personB/llama3_soc_gemm_roofline.py` for user's repo (downloaded script named `llama3_soc_gemm_roofline.py` in ChatGPT artifacts); outputs under `personB/results/llama3_soc_gemm_analytical/` upon local run. Assistant's local copy and results are kept alongside evolving paper draft in `/mnt/data/FACIL_Overleaf_Working_Draft_2026-10-22/results/soc_gemm_analytical/`. User has **not yet run this new script on WSL**; results below are assistant-side analytical calculations, **not measurements**.

**Paper-grounded platform input:** FACIL Table II, Jetson AGX Orin, FP16 **42.5 TFLOP/s peak compute** and **204.8 GB/s theoretical peak bandwidth**. These are source-reported capabilities, not achieved throughput under current DRAMsim3 configuration. Workload: 32 Llama3-8B decoder blocks, 7 linear weight matrices per block (Q/O 2 x 4096x4096; K/V 2 x 1024x4096; gate/up 2 x 14336x4096; down 1 x 4096x14336); **224 GEMMs**, **13 GiB FP16 weights**. For prefill length P and W[M,K], X[K,P], modeled FLOPs `2*M*K*P` and modeled external memory traffic `2*M*K+2*P*K+2*P*M` bytes per GEMM (weights+input+output each transferred once). Idealized time per GEMM = `max(FLOPs/42.5e12, bytes/204.8e9)` seconds; sum across all 224 projection GEMMs. 7 weights/block = 416 MiB, 32 blocks = 13 GiB.

| Prefill tokens | GEMMs | Ideal SoC FP16 projection GEMM roofline (ms) | Per-GEMM roofline regime |
|---:|---:|---:|---|
| 8 | 224 | 68.362 | memory-bound |
| 16 | 224 | 68.567 | memory-bound |
| 32 | 224 | 68.977 | memory-bound |
| 64 | 224 | 69.796 | memory-bound |
| 128 | 224 | 71.434 | memory-bound |

**Validation:** Internal self-test PASS: 32 blocks, seven projection types/block, 224 linear GEMMs, 13 GiB weights, FLOP arithmetic, FP16 bytes, units, non-negative/memory bound, and monotonic prefill times. No PIM command latency invented. **Limitations:** no real GPU execution or GPU kernel utilization, no native LPDDR5 timing calibration, no attention score/value GEMMs, normalizations, nonlinear operations, input embedding, output LM head, KV cache, kernel overhead/caching, or other prefill terms; optimistic bandwidth at *theoretical* 204.8 GB/s is not measured DRAMsim3 throughput. It is **not full TTFT**. No measured mapping-dependent GEMM penalty or baseline-vs-FACIL end-to-end speedup is established. Do not add GEMM floor to serialized copy bound and call it an observed or rigorous TTFT bound.

**Next:** User runs `python3 personB/llama3_soc_gemm_roofline.py --output personB/results/llama3_soc_gemm_analytical` and shares terminal/CSV; then analytical PIM GEMV sensitivity, matched FACIL mapped-access experiment, and appropriately qualified TTFT estimate, while continuing to maintain this log and the same IEEE paper source.


## 2026-10-23 — Combined baseline projection GEMM + re-layout component scenario

**New calculation (no new DRAMsim3/GPU timing run).** Following the user's WSL self-test PASS for the 224-projection Llama3-8B Jetson roofline model, combined the pre-existing analytical *ideal* SoC linear GEMM estimate with the **447.283520 ms** sum of 32-layer serialized READ+WRITE completion upper brackets from the corrected synthetic 2-KiB-row DRAMsim3 configuration. All GEMM and DRAM proxy inputs remain unchanged.

| Prefill P | Ideal SoC linear GEMM (ms) | Re-layout stage upper-bracket sum (ms) | Combined component scenario (ms) |
|---:|---:|---:|---:|
| 8 | 68.362 | 447.283520 | 515.645520 |
| 16 | 68.567 | 447.283520 | 515.850520 |
| 32 | 68.977 | 447.283520 | 516.260520 |
| 64 | 69.796 | 447.283520 | 517.079520 |
| 128 | 71.434 | 447.283520 | 518.717520 |

**Boundary:** The sum is *not* actual or fully calibrated TTFT, nor a rigorous latency upper bound: analytical GEMM uses peak roofline (optimistic) but the copy uses DRAM stage search upper brackets, and omitted work may add time. It assumes all seven linear weights per decoder block are re-laid out once, all copy stages serial, identical isolation across blocks, and ignores host rearrangement/overlap. Actual GPU GEMM, PIM GEMV, attention and other operations not simulated. FACIL mapped SoC access and GEMM mapping penalty are still outstanding; no FACIL speedup computed from this table. No previous experiment has been deleted.

**Artifacts updated:** same evolving IEEE `main.tex` (new combined table and methodology notes), same cumulative `FACIL_PROJECT_LOG.md`, plus calculation-only `results/soc_gemm_analytical/baseline_projection_plus_copy_scenario.csv`.


## 2026-10-23 — Baseline TTFT reduced-scope proxy finalized (calculation-only; no new simulation)

**Status: FINAL FOR THE DECLARED REDUCED SCOPE, NOT ACTUAL END-TO-END TTFT.** The professor's baseline is the on-demand PIM-to-SoC re-layout plus SoC prefill GEMM. The four 2-KiB-geometry DRAMsim3 stage experiments have finished, and the user ran the 224-GEMM/32-layer Jetson analytical model with its self-test PASS. We combine them with the explicitly *truncated* TTFT component definition `T_baseline_scope(P) = ideal_SoC_linear_GEMM(P) + serialized_copy_stage_bracket_sum`. The matrix shape/multiplicity and 32-block accounting are unchanged.

| Prefill P | Ideal SoC linear GEMM (ms) | DRAMsim3 re-layout stage upper-bracket sum (ms) | Baseline reduced-scope TTFT proxy (ms) |
|---:|---:|---:|---:|
| 8 | 68.362240 | 447.283520 | **515.645760** |
| 16 | 68.567040 | 447.283520 | **515.850560** |
| 32 | 68.976640 | 447.283520 | **516.260160** |
| 64 | 69.795840 | 447.283520 | **517.079360** |
| 128 | 71.434240 | 447.283520 | **518.717760** |

**Precision correction:** Earlier calculation-only tables added GEMM values rounded to three decimal places; this revision uses full-precision `soc_gemm_roofline.csv` values, resulting in 516.260 (rather than 516.261) ms at P=32 and 517.079 (rather than 517.080) ms at P=64 when displaying three decimals. This is a rounding correction, not a changed model or newly measured result.

**Interpretation:** The scenario is a named TTFT *proxy* used for the controlled comparison, not an identified full LLM TTFT. Missing prefill work (attention QK/AV, softmax, normalizations, embeddings, nonlinearities, output head, runtime/sampling), real GPU GEMM performance, and CPU reordering/overlap have no measured or justifiably calibrated additive timing here; keep the residual unspecified rather than setting it to zero or inventing constants. The ideal GEMM theoretical *lower* performance floor and DRAMsim3 copy-stage completion-time *upper* brackets together are not a rigorous bound on true TTFT. Standard PIM decode GEMV occurs after the first token; do not add decode GEMV to TTFT. PIM GEMV remains a separate analytical decode/TTLT sensitivity task.

**Provenance:** `/mnt/data/FACIL_Overleaf_Working_Draft_2026-10-22/results/soc_gemm_analytical/baseline_ttft_proxy.csv` (theoretical analytical GEMM + user-reported DRAM stage results); `main.tex` in the same evolving IEEE folder; same cumulative `FACIL_PROJECT_LOG.md`. A helper `finalize_baseline_ttft.py` re-reads the user's four local `summary.json` files and GEMM CSV and validates counts/config, so the table can be recomputed in WSL without manual transcription. Earlier non-2-KiB geometry results remain superseded in history.

**Next required comparison:** Represent FACIL-mapped SoC memory access and potential GEMM mapping penalty under verified equivalence (not the ad hoc peak assumption); compare against baseline using the same truncated prefill boundary. Then analytically model PIM GEMV for decode/TTLT.


## 2026-10-23 — FACIL Step 1 standalone MapID verification (read-only ZIP audit)

**Scope:** Rechecked the `personA/facil_mapper.py` and `personA/validate_placement.py` shipped inside the user-uploaded `DRAMsim3.zip` in a temporary directory without modifying the ZIP. The ZIP contains the *old* 8-KiB config; for the configuration-consistency check only, changed `rows` 65536→262144 and `columns` 1024→256 in that temporary extracted copy, mirroring the user's confirmed WSL settings. This is a source/reference verification, **not** direct access to the user's live WSL files.

**Observed PASS:** 10/10 mapper unit tests; paper Figure 10 MapID examples 3 and 5; selected 4-channel × 2-rank × 16-bank geometry, AiM FP16 chunk 2 KiB, 2 MiB huge pages; Q/O MapID2/16,384 chunks; K/V MapID2/4,096 chunks; FFN gate/up MapID2/57,344 chunks; FFN down MapID3/57,344 chunks (2 or 3 PUs per compact row; 48 huge-page-crossing rows expected). Total **135,168 independently checked 2 KiB chunks** (equivalently **2,162,688 128-byte requests**). Geometry calculation from edited config confirms 2 KiB aggregate bank rows, 128B requests, 4 channels, 2 ranks/channel, and 16 banks/rank.

**What this proves:** standalone MapID selection, encoder/decoder invertibility and configured PIM row/bank placement constraints of the test geometry. **Not proved:** actual dynamic MapID in DRAMsim3 controller, PIM compute timing, native LPDDR5 protocol, or fair SoC GEMM memory-access timing. Next Step 2 is explicitly simulator integration/verified address decoding. Existing IEEE paper's already-reported standalone mapping tests remain applicable; no new performance or timing claim.


## 2026-10-23 — FACIL Step 2 native DRAMsim3 MapID integration (isolated audit, WSL installation pending)

**Scope/ownership:** Audited user-uploaded `DRAMsim3.zip` as read-only source. Created and compiled a minimal **three-file C++ patch** against an isolated extraction; **did not modify the uploaded ZIP or the user's WSL repository**. A separate temporary config was updated from the ZIP's old 8-KiB `rows=65536,columns=1024` geometry to the same `rows=262144,columns=256` 2-KiB geometry reported by the user (four 64-bit channels, two ranks/channel, 16 banks/rank, 128-B requests, LPDDR4-protocol LPDDR5-style timing). The user's earlier EOF trace-reader fix is independent and unaffected by this patch. This is a source-and-simulator integration test, **not a new performance benchmark**.

**Source modifications, pending application on user's PC:**
- `src/configuration.h`: add an optional per-2MiB-huge-page MapID registry to `dramsim3::Config`.
- `src/configuration.cc`: load explicit `(huge_page_index, MapID)` pairs from the `FACIL_PAGE_MAP_FILE` environment variable and perform MapID-aware PA-to-DA decoding for those pages; unregistered pages retain the configured conventional decoder. Reject wrong geometry, malformed/duplicate page IDs, and unsupported MapIDs (>3). MapID changes the PU bit positions following the standalone AiM mapper.
- `src/dram_system.cc`: route each memory request to the channel returned by the **same** `Config::AddressMapping()` the controller uses; otherwise changing only command decoding would route requests to the wrong channels.

**Native source/code checks in isolated Linux build:** Successfully compiled patched `dramsim3main`; full test against `personA/facil_mapper.py` created an independent Python fixture and compared with actual C++ `Config::AddressMapping` for 996 sampled/boundary addresses spanning Q/O MapID2, K/V MapID2, FFN gate/up MapID2, FFN down MapID3. All 996 PASSED. The C++ validator independently checked 2,162,688/2,162,688 complete 128-B request mappings were unique across 132 nonoverlapping 2MiB pages, and 16,384/16,384 conventional accesses on an unregistered page decoded *identically* with and without the FACIL registry. These are address/placement checks, not data-payload simulation.

**Actual simulator channel routing smoke:** With 32 offered READ requests and fixed EOF reader, conventional simulation completed per-channel reads `[8,8,8,8]`, FACIL MapID2 simulation completed `[32,0,0,0]`; both zero unexpected writes. Matches independent mapping prediction; proves the MapID choice affects DRAMsim3's real request routing. Not a performance comparison.

**Artifacts:** `facil_step2_audit/facil_step2_mapid.patch` (only three simulator C++ files); `facil_step2_audit/facil_step2_validate.py` (driver/fixtures + simulator smoke); `facil_step2_audit/facil_step2_native_validator.cc` (C++ reference compare / exhaustive uniqueness); `facil_step2_audit/full_validation_log.txt`, plus `work/.../personB/results/facil_step2/summary.json`. Patch dry-run applied cleanly to original archived C++ source.

**Important limitations:** No native LPDDR5 protocol, no OS/TLB/PTE MapID plumbing (environment-provided static page map is a reduced-scope proxy), no AiM PIM execution, no real SoC GEMM request stream, no measured mapping-induced SoC GEMM slowdown or FACIL TTFT speedup. The paper's 32B transfers are modeled as 128B DRAMsim3 requests under explicitly synthetic 2KiB bank rows. The **next real step** is user applying patch in WSL, rebuilding without overwriting EOF fix, rerunning `facil_step2_validate.py`, and sharing local `summary.json`; only then call user's local Step 2 finished. Any matched performance workloads come AFTER that.

## 2026-10-23 — FACIL Step 2 verified on user's Ubuntu; Step 3 matched SoC read experiment planned

**User-reported local validation:** The native C++ MapID integration in DRAMsim3 passed `PASS: 411 Python/C++ checks, MapID 2/3 uniqueness, conventional fallback`; the mixed-page DRAMsim3 test completed 96 intended reads with channel counts `[72,8,8,8]` and zero unexpected writes. This supersedes the prior "WSL installation pending" status; the 2-KiB synthetic geometry / LPDDR4 protocol with LPDDR5-style timing caveat still applies.

**Step 3 comparison design (K/V first; user execution pending):** Use the SAME 65,536 offered logical 128-byte K/V weight-block accesses in both cases: baseline SoC read from conventional re-layout destination `0x10000000 + i*128` using conventional decoding, versus FACIL read from original physical/logical weight pages `i*128` with native MapID=2 registered for huge pages 0,1,2,3. Before any simulation, check that the 65,536 FACIL logical requests and their old offline PIM-encoded baseline source reads correspond to the same bank/row placement, and that each baseline conventional read matches the previous re-layout WRITE target. Use exactly the same simulator executable, timing configuration SHA, trace cycle offerings and complete-transaction count; explicitly unset `FACIL_PAGE_MAP_FILE` for conventional mode and set it only for FACIL. First smoke-test completion counters, then measure completion-time brackets at 256-cycle resolution. Existing 225.680us K/V baseline re-layout copy-stage bracket is **separate** from the matched conventional SoC read bracket; do not add an independent SoC-read term to a peak-roofline GEMM time because that double-counts memory accesses.

**Not yet shown by Step 3:** Actual GPU GEMM timings / accesses, PIM GEMV hardware timing, real LPDDR5 timing, paper-grade TTFT. This is a **sequential weight-read memory-traffic sensitivity proxy** rather than an inferred GEMM slowdown. Avoid treating the result as a calibrated FACIL TTFT speedup without a justified GEMM access-performance model.


## 2026-10-23 — Native FACIL, GEMV sensitivity and FFN-down padding extension
- Native MapID2/3 source integration and address validity: PASS; matched logical weight-read tests in all four projection categories: PASS.
- 32-block reduced-scope baseline TTFT proxy: 515.646–518.718 ms; FACIL ideal: 68.362–71.434 ms; sequential-read mapping penalty sensitivity 308.964 ms; adjusted FACIL proxy: 377.327–380.399 ms. Not measured GPU slowdown or end-to-end TTFT.
- PIM GEMV analytical waves/matrix: Q/O 128, K/V 32, FFN gate/up 448, FFN down 448. Hypothetical 75, 100, 200 ns/wave; memory broadcast, inter-PU reductions and PIM commands not calibrated. Dynamic short-prefill optimization is conditional, not validated physical PIM timing.
- Original FFN-down extension: 28KiB compact vs 32KiB padded stride, allocated storage 112MiB vs 128MiB (+14.3%); PU count/row compact 2048 rows with 2 PUs, 2048 rows with 3; padded all 4096 rows with 2 PUs; huge-page crossings 48 vs 0.
- Representative native DRAMsim3 matched-read test of 128 stratified output rows, 28,672 useful reads/case: compact <= 127.411 us, padded <= 141.907 us (compact/padded ratio 0.898x). Sampling, not full inference: do not extrapolate speedup to whole matrix.
- Figures: personB/results/facil_pim_gemv_analytical/{pim_prefill_sensitivity,pim_gemv_per_token}.png and personB/results/facil_ffn_down_padding_sample/ffn_padding_sample_comparison.png.
- Limitations: LPDDR4 protocol with LPDDR5-like timing; no native PIM MAC execution, no GPU GEMM execution, no complete TTFT measurements. Original padding optimizes row alignment; runtime improvement is not presumed.


## 2026-10-23 — Paper integration and submission QA
- Revised existing IEEE working manuscript (not a separate scientific project) to include tested native MapID2/3 checks, four matched-read experiments, three static TTFT scenarios, hypothetical PIM dynamic sensitivity, sample padding result and seven labeled figures.
- Reviewer caution: 308.964 ms is sensitivity assumption, 75/100/200 ns is hypothetical PIM wave cost; no measured end-to-end TTFT, GPU GEMM or PIM timing.
- Paper PDF and source bundle are locally generated from an archived snapshot and are NOT automatically synced to the user's Ubuntu Git checkout or cloud Overleaf project.
- Author names, current repository commit URL/hash need confirmation before actual submission.


---

## 2026-11-02 — Batch-aware decode extension: Experiments 1--5 (new evidence; no original experiment overwritten)

**Scope and contribution.** Retain all previously logged FACIL mapping/baseline and FFN-down padding evidence. The MAIN original extension is now analytical *batch-width-aware per-decode-step SoC/PIM dispatch* for 32-block Llama3-8B FP16 linear layers (224 projections) using FACIL's one-copy layout. The original FACIL paper's prefill-aware SoC/PIM selection is acknowledged; this work extends the policy to batch-width-varying **decode**. Do not claim novelty for batched inference generally (NeuPIMs is related work).

**User-reported Ubuntu validation of Experiments 1--2:** `PASS: 256 comparisons against previous validated run` and `EXPERIMENTS 1 AND 2: PASS`. Model checked at B=1, exact PIM 5.3248 ms (assumed 100 ns per 53,248 waves) and 20.0 ms (illustrative calibration only). For η=0.763, ρ=0, SoC first preferable at B=17 (optimistic) or B=5 (illustrative). For η=0.5, ρ=0, first SoC B=26 and B=7 respectively. Sweeps η={0.30,0.50,0.763,1.00}; ρ={0,0.25,0.50}; B=1..64. η=0.763 derives its numerical inspiration from paper's GEMV bandwidth utilization, NOT measured GEMM utilization; ρ>0 represents unvalidated future PIM batch reuse, NOT AiM behavior. PIM assumed linear in B for main ρ=0 case. Original PIM 100ns/wave values are not calibrated to actual hardware. 20-ms/token scenario is only paper-informed heuristic, NOT read from FACIL as actual per-token measured GEMV.

**User-reported Ubuntu validation of Experiments 3--4:**
```
PASS: Batch-1 PIM latency
PASS: PIM reuse monotonicity
PASS: Zero-overhead FACIL = duplication latency
PASS: Offline adaptive never exceeds best static
PASS: Huge overhead reduces offline optimum to static
PASS: Exact switching-overhead boundaries
PASS: On-demand conversion ordering
EXPERIMENTS 3 AND 4: PASS
```
Memory accounting: one copy=13,958,643,712 bytes =13.959 GB (13 GiB); two copies 27.917 GB; duplication adds 13.959 GB. Weight duplication (paper Fig.5a) can match zero-overhead FACIL dispatch's latency but doubles linear-weight storage; **do not claim FACIL beats duplication on ideal latency**. Paper-style on-demand re-layout (Fig.5b) pays a conversion for each modeled SoC pass (447.28352 ms from our full-model serialized read/write stage sum; compare an explicitly rough 200 ms alternative as sensitivity). One-time in-place conversion is a different hypothetical alternative, not the paper's scheme; its converted weights cannot simultaneously provide a PIM-compatible view. Temporary buffers and metadata not counted. Whole-step engine choice; no per-matrix dispatch claim.

Main sensitivity η=0.763, ρ=0; user-reported **offline** largest tolerable uniform switching overhead before mixed schedule loses to best static choice:

| PIM timing scenario | Rising ms/switch (1,4,16,32,64) | Falling ms/switch | Oscillating ms/switch (1,32,4,64,8,48,2,64) | Zero-cost switches rising/falling/oscillating |
| --- | ---: | ---: | ---: | --- |
| 100 ns/wave optimistic | 156.86848 | 156.86848 | 84.03698 | 1/1/7 |
| Illustrative 20ms/token | 78.82422 | 78.82422 | 69.36178 | 1/1/5 |

Offline dynamic programming knows entire future trace; **it is NOT deployable without workload prediction**. Online myopic hysteresis was also coded and compared but the user's complete `.csv` and its h-dependent values were not uploaded, so only the reported `h_max` summary is certified as user-run. The first step chooses its engine for free. `h_max = max_{path with switches>0}(best_static - zero_overhead_path_time)/switch_count` is a *threshold derived from analytical model*, not measured switch latency. A high h restores best static only for offline optimal. Batch-aware decode time is **linear-layer only**, not end-to-end TTLT; attention, KV, activation, sampling, memory contention, kernels, real PIM cycles, reductions, broadcasts, transition/synchronization cost excluded.

**User-reported Experiment 5 DRAMsim3 sample:** `EXPERIMENT 5: PASS`; 32,768 unique 128-byte transactions per stage, 4,194,304 bytes per stage. Original-order reads: 202,752 approximate cycles / 63.36 μs / 66.198 GB/s / 32.32% external peak; sequential-order reads: 66,560 cycles / 20.8 μs / 201.6492 GB/s / 98.46%. This is 3.046× faster completed-read throughput for that sample and indicates **ordering matters** in this geometry. Original and sequential WRITEs each 66,560 cycles / 20.8 μs / 201.6492 GB/s, but **write commands ISSUED**, not completed WRITE transactions, and thus cannot be treated as sustained completed-write bandwidth. No proof the whole 447.284ms baseline copy cost is entirely ordering-related. Full original experiment-5 traces, measurement scripts and raw simulator stats were **not supplied in this paper-authoring session**; this entry is derived from user-pasted output, not an independently rerun measurement.

**Author-side analytical reconstruction on Nov 2:** Independently reconstructed the exact formula/sweep from the user's messages (rather than copying unseen Ubuntu CSVs). Computed all 6 h_max values and four main crossover thresholds, matching user-provided numeric output. Rebuilt figure PNGs/CSV (`analysis/reconstructed_*.csv`) and a provenance JSON with status `ANALYTICAL RECONSTRUCTION`. These reconstructed CSVs must **not** be described as the original Ubuntu-generated files; original per-test scripts and outputs should be committed from Ubuntu when accessible.

**Paper/presentation:** Updated the SAME evolving IEEE manuscript from October 23 snapshot, preserving baseline and FACIL methods/TTFT proxy; replaced the primary FFN-down padding extension with new batch-aware decode section and retained a short padding *negative result* (+14.3% storage, sampled read slower). Generated a revised PDF/source snapshot and 18-slide editable presentation for the November 4 assignment deadline. Note the author's remote Overleaf and WSL Git checkout were **not** directly edited by local artifact generation, team names and contributions remain placeholders, and repository URL needs confirmation. We cannot declare final submission before those are addressed.

**Experiment-5 provenance task remaining:** add actual Ubuntu `personB/results/...` CSV/JSON, original/sequential read/write traces, config and simulator hashes, plus script commit before claiming source-level reproducibility. Verify same multiset of physical transactions and same timed injection schedule aside from order, since the user-pasted summary alone cannot prove equivalence; verify WRITE completion separately or continue saying WRITE issued. Check report graph/legend against this distinction.
