# FACIL viva evidence

Start with your question and open the linked source, configuration, or raw results. [Build and replay instructions](REPRODUCIBILITY.md) · [Figure and table index](RESULTS_INDEX.md)

## Original paper and coursework scope

The paper covers user-level selection, OS page metadata, controller mapping, and system-level evaluation. This coursework implements the Python reference mapper and native DRAMsim3 address decoding and routing through a static page registry. It measures simulated DRAM traffic and models SoC/PIM linear projections and batch-aware decode. Full OS and controller integration, measured GPU GEMM, calibrated PIM execution, real dispatch, and end-to-end inference remain outside the evaluation. [FACIL paper (HPCA 2025)](https://seonghoonseo.github.io/files/pdf/research/2025-hpca-facil.pdf) · [Project limitations](LIMITATIONS.md)

Figure 13 reports a 2.89× Jetson TTFT geomean. Figure 15 reports 2.37× and 2.63× geomeans on two datasets. Table III reports up to 2.1% measured Jetson GEMM slowdown for PIM layout. The coursework's 1.366× result uses a 16-token projection-component proxy with a synthetic mapped-read sensitivity term. The synthetic scan and the paper's GPU kernel timings use different workloads and metrics. [Original evaluation](https://seonghoonseo.github.io/files/pdf/research/2025-hpca-facil.pdf) · [TTFT proxy CSV](../results/facil/facil_step6_comparison/ttft_comparison.csv) · [Comparison assumptions](../results/facil/facil_step6_comparison/comparison_notes.md)

## Member demonstrations

| Member | Show live | Priority questions |
| --- | --- | --- |
| Sukhjot | Walk through the page registry, native decoding, channel routing, fallback, and corrected timing configuration. | Q1, Q6–Q8, Q11–Q12, Q22 |
| Sreeja | Derive MapID 2/3, the SoC and PIM costs, the crossover, and the offline schedule. | Q2–Q5, Q24, Q28–Q36 |
| Mayank | Generate READ/WRITE traces, check stage counters, and derive 447.284 ms. | Q13–Q21, Q25 |
| Pankaj | Run mapper/native checks, show mixed routing, and walk through the two-copy result. | Q9–Q10, Q16–Q17, Q37–Q40 |

## Mapping and native implementation

| Question | Files to open | What to demonstrate |
| --- | --- | --- |
| **Q1.** What does MapID do? | [Reference mapper](../mapping/facil_mapper.py#L83) · [Native decoder and registry](../src/configuration.cc#L40) | It selects the bit split that assigns an address to channel, rank, bank and row. The within-chunk offset selects the column. |
| **Q2.** Why MapID 2 or 3? | [Reference mapper](../mapping/facil_mapper.py#L83) · [Placement audit](../results/mapping/llama3_validation/placement_audit) | 4096 FP16 columns form an 8 KiB row, or four 2 KiB chunks, giving MapID 2. FFN-down has 28 KiB rows, so the selector caps the mapping span at the 16 KiB per-PU page share and partitions the row, giving MapID 3. |
| **Q3.** What is a PU and where are the four chunks? | [Reference mapper](../mapping/facil_mapper.py#L83) · [Placement audit](../results/mapping/llama3_validation/placement_audit) | A PU is associated with a bank. One 8 KiB logical row can occupy four 2 KiB physical rows in that bank. |
| **Q4.** Why 128 PUs? | [Timing and geometry config](../configs/LPDDR5_6400_APPROX_v1.ini) · [Native decoder and registry](../src/configuration.cc#L40) | Four channels × two ranks/channel × sixteen banks/rank, with one modeled PU per bank. |
| **Q5.** What is 16 KiB per PU? | [Reference mapper](../mapping/facil_mapper.py#L83) · [Timing and geometry config](../configs/LPDDR5_6400_APPROX_v1.ini) | The modeled share of one 2 MiB huge page per bank, calculated as 2 MiB / 128. |
| **Q6.** Where did we modify DRAMsim3? | [Native decoder and registry](../src/configuration.cc#L40) · [Config declarations](../src/configuration.h) · [Controller routing](../src/dram_system.cc#L31) · [Trace reader](../src/cpu.cc) | Show registry loading and address decoding in Config, then request routing and the trace EOF fix. |
| **Q7.** Why change channel routing? | [Controller routing](../src/dram_system.cc#L31) · [Native test inputs](../results/facil/facil_native_validation/) · [Mixed-page counters](../results/facil/facil_native_validation/mixed_run/dramsim3.json) | The decoder can return a different channel from the fixed bit positions. Admission and submission must both use the decoded channel. |
| **Q8.** What happens to unregistered pages? | [Registry lookup and fallback](../src/configuration.cc#L158) · [C++ verifier](../tests/native/verify_facil_decoder.cc) | They use the conventional decoder. The verifier checks a full unregistered page against the registry-free configuration. |
| **Q9.** How was the mapper validated? | [Python mapper tests](../tests/test_mapper.py) · [C++ verifier](../tests/native/verify_facil_decoder.cc) · [Native test inputs](../results/facil/facil_native_validation/) · [Mixed-page counters](../results/facil/facil_native_validation/mixed_run/dramsim3.json) | Ten mapper tests, 411 native/reference tuples, uniqueness and fallback checks, and 96 mixed reads distributed [72, 8, 8, 8]. |
| **Q10.** What do the 411 comparisons establish? | [C++ verifier](../tests/native/verify_facil_decoder.cc) · [Native test inputs](../results/facil/facil_native_validation/) · [Timing and geometry config](../configs/LPDDR5_6400_APPROX_v1.ini) | They establish agreement for sampled tuples in this geometry. The separate uniqueness loop enumerates two mapped pages at 128-byte intervals. |
| **Q11.** Does changing MapID move existing bytes? | [Registry lookup and fallback](../src/configuration.cc#L158) · [Baseline trace generator](../experiments/baseline/generate_verified_baseline_traces_2k.py) | The registry changes decoding. Initial placement must agree with the mapping, or data must be moved separately. |
| **Q12.** Where is the OS page-table change? | [Native decoder and registry](../src/configuration.cc#L40) · [Native test inputs](../results/facil/facil_native_validation/) | FACIL_PAGE_MAP_FILE supplies static simulator metadata. The project implements the decoding path from physical addresses. |

## Baseline, traces and measurements

| Question | Files to open | What to demonstrate |
| --- | --- | --- |
| **Q13.** How did we generate the traffic? | [Baseline trace generator](../experiments/baseline/generate_verified_baseline_traces_2k.py) · [Matrix evidence](#matrix-by-matrix-evidence) | Generate 128-byte source READs from PIM-oriented placement encoded into conventional physical addresses, then WRITE to a separate conventional region. |
| **Q14.** Why 128-byte transactions? | [Timing and geometry config](../configs/LPDDR5_6400_APPROX_v1.ini) · [Baseline trace generator](../experiments/baseline/generate_verified_baseline_traces_2k.py) | A 64-bit bus × burst length 16 / 8 yields 128 bytes. A 2 KiB PIM chunk spans 16 requests. |
| **Q15.** Logical matrix row or physical DRAM row? | [Timing and geometry config](../configs/LPDDR5_6400_APPROX_v1.ini) · [Placement audit](../results/mapping/llama3_validation/placement_audit) | 4096 FP16 elements form an 8 KiB logical row. The proxy has 2 KiB aggregate physical bank rows. |
| **Q16.** How was latency measured? | [Cycle bracketing and counters](../experiments/baseline/measure_relayout.py#L22) · [K/V stage summary](../results/baseline/verified_baseline_k_v_2k/summary.json) · [Trace reader](../src/cpu.cc) | Find cycle-budget brackets from counters. Multiply cycles by 0.3125 ns and divide by 1000 for µs. Add the serialized READ and WRITE upper brackets. |
| **Q17.** Why check completion counts? | [K/V stage summary](../results/baseline/verified_baseline_k_v_2k/summary.json) · [K/V raw READ and WRITE stats](../results/baseline/verified_baseline_k_v_2k) · [Cycle bracketing and counters](../experiments/baseline/measure_relayout.py#L22) | K/V needs 65,536 counted transactions for each stage. READ completions and WRITE callbacks use separate counters. The WRITE callback can acknowledge buffering. |
| **Q18.** Where does 26 GiB of baseline traffic come from? | [SoC roofline](../experiments/analytical/soc_gemm_roofline.py) · [Matrix evidence](#matrix-by-matrix-evidence) | 416 MiB of weights per block × 32 blocks gives 13 GiB. One modeled conversion reads and writes every included weight. |
| **Q19.** Where does 447.284 ms come from? | [TTFT proxy calculation](../experiments/facil/facil_comparison_figures.py) · [Matrix evidence](#matrix-by-matrix-evidence) | 32 × [2 × 901.920 + 2 × 225.680 + 2 × 3157.210 + 5407.990] µs = 447.283520 ms of serialized DRAM traffic. |
| **Q20.** Why is FFN-down expensive? | [FFN-down comparison](../results/facil/facil_step3_ffn_down_2k/comparison.json) · [Reference mapper](../mapping/facil_mapper.py#L83) · [Matrix evidence](#matrix-by-matrix-evidence) | The matrix is 112 MiB with fourteen 2 KiB chunks per logical row. Placement partitions the row, and measured traffic also depends on access order and DRAM scheduling. |
| **Q21.** How is effective bandwidth calculated? | [Two-copy runner](../experiments/facil/two_copy_k_v.py) · [Two-copy CSV](../results/facil/facil_two_copy_k_v_2k/run/duplication_vs_facil.csv) | Divide useful bytes by simulated seconds and report decimal GB/s. 8,388,608 bytes in 41.4115625 µs gives 202.567 GB/s. |
| **Q22.** Why use an LPDDR4 config? | [Timing and geometry config](../configs/LPDDR5_6400_APPROX_v1.ini) · [Comparison assumptions](../results/facil/facil_step6_comparison/comparison_notes.md) | The simulator runs the LPDDR4 protocol with selected LPDDR5-style timings, including a 0.3125 ns tick. |

## Prefill and analytical timing

| Question | Files to open | What to demonstrate |
| --- | --- | --- |
| **Q23.** Why use a TTFT component proxy? | [SoC roofline](../experiments/analytical/soc_gemm_roofline.py) · [TTFT proxy calculation](../experiments/facil/facil_comparison_figures.py) · [Comparison assumptions](../results/facil/facil_step6_comparison/comparison_notes.md) | The model covers 224 linear projections and selected DRAM traffic. Full TTFT would include attention, runtime, and other operations. |
| **Q24.** How is SoC GEMM time calculated? | [SoC roofline](../experiments/analytical/soc_gemm_roofline.py) · [16-token projection breakdown](../results/analytical/llama3_soc_gemm_analytical/gemm_details_P16.json) | For each projection, take the larger of compute time and weight/input/output transfer time using 42.5 FP16 TFLOP/s and 204.8 GB/s. Sum the projection times. |
| **Q25.** How did we obtain 1.366×? | [TTFT proxy calculation](../experiments/facil/facil_comparison_figures.py) · [TTFT proxy CSV](../results/facil/facil_step6_comparison/ttft_comparison.csv) | The 16-token case adds the 447.284 ms conversion cost or the 308.964 ms mapped-read sensitivity to the common 68.567 ms roofline time. 515.851 / 377.531 ≈ 1.366. |
| **Q26.** Where does 308.964 ms come from? | [TTFT proxy calculation](../experiments/facil/facil_comparison_figures.py) · [Comparison assumptions](../results/facil/facil_step6_comparison/comparison_notes.md) · [Matrix evidence](#matrix-by-matrix-evidence) | Sum mapped-minus-conventional simulated read brackets by matrix multiplicity across 32 blocks. Using that difference as a GEMM increment is a sensitivity assumption. |
| **Q27.** Why add only the read-time difference? | [SoC roofline](../experiments/analytical/soc_gemm_roofline.py) · [TTFT proxy calculation](../experiments/facil/facil_comparison_figures.py) | The roofline already accounts for weight bytes. The increment represents the assumed extra access cost. |

## Original batch-aware decode extension

| Question | Files to open | What to demonstrate |
| --- | --- | --- |
| **Q28.** What is our extension? | [Batch feasibility](../experiments/extension/batch_dispatch_feasibility.py) · [Experiments 1–2](../experiments/extension/batch_crossover_sensitivity.py) · [Experiments 3–4](../experiments/extension/batch_trace_switching.py) | Select a modeled engine for each changing active decode batch, then evaluate crossovers, switching costs, and layout trade-offs. |
| **Q29.** Why can decode use GEMM? | [Experiments 1–2](../experiments/extension/batch_crossover_sensitivity.py) · [SoC roofline](../experiments/analytical/soc_gemm_roofline.py) | Stack the current token vector of each active sequence into a column of X and compute W × X. |
| **Q30.** How is PIM latency modeled? | [PIM wave model](../experiments/analytical/pim_gemv_analytical.py) · [PIM wave counts and assumptions](../results/analytical/facil_pim_gemv_analytical/pim_gemv_model.json) · [Experiments 1–2](../experiments/extension/batch_crossover_sensitivity.py) | Use T₁[1 + (B−1)(1−ρ)]. For the hypothetical 100 ns/wave case, 53,248 waves yield T₁ = 5.3248 ms. A 20 ms single-token case is also illustrative. |
| **Q31.** How is SoC latency modeled? | [Experiments 1–2](../experiments/extension/batch_crossover_sensitivity.py) · [Batch assumptions](../results/extension/facil_batch_exp12/assumptions.json) | Sum per-projection roofline costs with assumed efficiency η. The η = 0.763 scenario borrows a paper GEMV utilization figure as a sensitivity input. |
| **Q32.** How is crossover found? | [Experiments 1–2](../experiments/extension/batch_crossover_sensitivity.py) · [Crossover CSV](../results/extension/facil_batch_exp12/crossovers.csv) | Find the first integer B where SoC time is lower than PIM time. At η = 0.763 and ρ = 0, the two cases cross at B = 17 and B = 5. |
| **Q33.** What dispatcher was implemented? | [Experiments 3–4](../experiments/extension/batch_trace_switching.py) · [Dynamic-policy CSV](../results/extension/facil_batch_exp34/dynamic_policy_results.csv) | Python computes engine schedules and modeled costs for synthetic batch sequences. |
| **Q34.** How do online hysteresis and offline DP differ? | [Experiments 3–4](../experiments/extension/batch_trace_switching.py) · [Dynamic-policy CSV](../results/extension/facil_batch_exp34/dynamic_policy_results.csv) | Online switches when current-step savings exceed the assumed transition cost. Offline DP minimizes total modeled cost using the entire future batch sequence. The first choice is free. |
| **Q35.** What is the 84 ms switching tolerance? | [Experiments 3–4](../experiments/extension/batch_trace_switching.py) · [Switching-limit CSV](../results/extension/facil_batch_exp34/switching_overhead_limits.csv) | For the oscillating trace at η = 0.763 and ρ = 0, the modeled offline break-even costs are 84.037 and 69.362 ms/switch. At the boundary, the best mixed schedule ties the best fixed engine. |
| **Q36.** How does FACIL enable the extension? | [Native decoder and registry](../src/configuration.cc#L40) · [Experiments 3–4](../experiments/extension/batch_trace_switching.py) · [Two-copy placement audit](../results/facil/facil_two_copy_k_v_2k/run/placement_validation.json) | A shared layout removes the modeled need for an on-demand weight re-layout. The policy separately accounts for assumed transition overhead. |

## Two-copy comparison

| Question | Files to open | What to demonstrate |
| --- | --- | --- |
| **Q37.** Why compare duplication? | [Storage comparison](../results/extension/facil_batch_exp34/weight_memory_comparison.csv) · [Two-copy raw counters and assumptions](../results/facil/facil_two_copy_k_v_2k/run/) | A second layout gives SoC conventional access while preserving a PIM-compatible region. The trade-off is extra weight storage. |
| **Q38.** How were the two copies simulated? | [Two-copy runner](../experiments/facil/two_copy_k_v.py) · [Two-copy C++ verifier](../tests/native/verify_two_copy_decoder.cc) · [Two-copy placement audit](../results/facil/facil_two_copy_k_v_2k/run/placement_validation.json) | Pair identical logical offsets in disjoint regions, register the PIM region with MapID 2, then verify both physical placements and mixed routing. |
| **Q39.** What did the two-copy experiment produce? | [Two-copy CSV](../results/facil/facil_two_copy_k_v_2k/run/duplication_vs_facil.csv) · [Two-copy raw counters and assumptions](../results/facil/facil_two_copy_k_v_2k/run/) | Both scans complete 65,536 reads. The mapped and conventional copies take 184.505 and 41.412 µs, respectively, or 4.455× for this simulated scan. |
| **Q40.** Why use FACIL if the conventional scan is faster? | [Two-copy CSV](../results/facil/facil_two_copy_k_v_2k/run/duplication_vs_facil.csv) · [Storage comparison](../results/extension/facil_batch_exp34/weight_memory_comparison.csv) · [Two-copy raw counters and assumptions](../results/facil/facil_two_copy_k_v_2k/run/) | The modeled full linear-weight footprint is 13 GiB shared versus 26 GiB duplicated. The scan quantifies access for one K/V matrix. |

## Matrix-by-matrix evidence

| Matrix class | Size × copies per block | Baseline inputs | Baseline measurements | Matched conventional and FACIL read measurements |
| --- | --- | --- | --- | --- |
| Q/O (4096 × 4096) | 32 MiB × 2 | [Manifest](../traces/verified_baseline_q_o_2k/manifest.json) | [Summary](../results/baseline/verified_baseline_q_o_2k/summary.json) · [READ and WRITE raw stats](../results/baseline/verified_baseline_q_o_2k) | [Timing and raw stats](../results/facil/facil_step3_q_o_2k) |
| K/V (1024 × 4096) | 8 MiB × 2 | [Manifest](../traces/verified_baseline_k_v_2k/manifest.json) | [Summary](../results/baseline/verified_baseline_k_v_2k/summary.json) · [READ and WRITE raw stats](../results/baseline/verified_baseline_k_v_2k) | [Timing and raw stats](../results/facil/facil_step3_k_v_2k) |
| FFN gate/up (14336 × 4096) | 112 MiB × 2 | [Manifest](../traces/verified_baseline_ffn_gate_up_2k/manifest.json) | [Summary](../results/baseline/verified_baseline_ffn_gate_up_2k/summary.json) · [READ and WRITE raw stats](../results/baseline/verified_baseline_ffn_gate_up_2k) | [Timing and raw stats](../results/facil/facil_step3_ffn_gate_up_2k) |
| FFN down (4096 × 14336) | 112 MiB × 1 | [Manifest](../traces/verified_baseline_ffn_down_2k/manifest.json) | [Summary](../results/baseline/verified_baseline_ffn_down_2k/summary.json) · [READ and WRITE raw stats](../results/baseline/verified_baseline_ffn_down_2k) | [Timing and raw stats](../results/facil/facil_step3_ffn_down_2k) |

Use the original manifests to regenerate the large trace streams and verify their checksums. [Trace recipes](REPRODUCIBILITY.md#regenerate-baseline-traces-without-simulations)

## Extension source and results

| Stage | Source | Evidence |
| --- | --- | --- |
| Feasibility, per-projection choice | [Batch feasibility](../experiments/extension/batch_dispatch_feasibility.py) | [Sweep, crossovers, assumptions](../results/extension/facil_batch_decode_feasibility) |
| Experiments 1–2, whole-step crossover and sensitivity | [Experiments 1–2](../experiments/extension/batch_crossover_sensitivity.py) | [Sweep, crossover CSV, figures](../results/extension/facil_batch_exp12) |
| Experiments 3–4, dynamic policies and switching | [Experiments 3–4](../experiments/extension/batch_trace_switching.py) | [Policy CSVs, switching limits, storage](../results/extension/facil_batch_exp34) |
| Experiment 5, sampled access-order diagnostic | [Experiment 5](../experiments/extension/relayout_bandwidth_diagnostic.py) | [Sample traces and counters](../results/extension/facil_batch_exp5) · [Source permutation traces](../traces/llama3_k_v_permutation) |
| Separate K/V shared-vs-duplicated placement | [Two-copy runner](../experiments/facil/two_copy_k_v.py) · [Two-copy C++ verifier](../tests/native/verify_two_copy_decoder.cc) | [Original results and replay instructions](../results/facil/facil_two_copy_k_v_2k) |

Experiment 5 uses a 4 MiB sample and reports issued WRITE commands. The separate K/V two-copy experiment compares completed READs for two 8 MiB scans.

## Seven rehearsal prompts

1. **What did we implement?** Q1 and Q6–Q12. Walk from the mapper to controller routing.
2. **What supports correctness?** Q9–Q10. Open the fixtures, native verifier, and mixed counters.
3. **Why charge 447 ms?** Q16–Q19. Reconstruct the serialized conversion scenario from the four raw summaries.
4. **Why do our scans look different from the paper's GEMM results?** Q26–Q27 and [the paper comparison](#original-paper-and-coursework-scope).
5. **Is 1.366× experimentally measured?** Q23–Q27. Separate simulated traffic from analytical execution assumptions.
6. **How is the extension different from the paper?** Q28–Q36. Show the active-batch cost model and switching policy.
7. **What is the strongest original simulated observation?** Q37–Q40. Show the matched scans and separate calculated storage cost.
