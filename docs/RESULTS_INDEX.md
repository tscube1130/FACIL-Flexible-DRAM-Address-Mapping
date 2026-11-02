# Results and producing code

All `results/` entries below are original local evidence. Reconstructed CSVs from the submission authoring package are not substituted for native simulator output. The supplied manuscript keeps its original script labels; [rename mapping](SCRIPT_RENAMES.csv) identifies the corresponding release scripts.

| Report item | Producing code | Evidence |
| --- | --- | --- |
| MapID anchors/inverse/page properties | `mapping/facil_mapper.py`, `tests/test_mapper.py` | `results/mapping/llama3_validation/`; `mapid3_8K_columns.png`, `mapid5_64K_columns.png` |
| Four-shape placement/PU/page crossing table | `mapping/validate_placement.py` | `results/mapping/llama3_validation/placement_audit/summary.json`, row-placement CSVs |
| Compact/padded structural alignment | Preserved mapping test history | `results/mapping/llama3_validation/compact_vs_padded/`, `placement_audit/` |
| Structural bank grouping | `mapping/check_lockstep_groups.py` | `results/mapping/llama3_validation/lockstep_grouping/summary.json` |
| Native decoder, MapID 2/3, fallback | `tests/native/verify_facil_decoder.cc` | `results/facil/facil_native_validation/` expected tuples, registry, mixed trace and statistics |
| Conventional vs mapped channel example | Modified `src/configuration.cc` and `src/dram_system.cc` | `results/facil/facil_step2_check/` and native mixed-page results |
| Baseline per-shape copy stages, 447.28352-ms sum | `experiments/baseline/generate_verified_baseline_traces_2k.py`, `measure_relayout.py` | `results/baseline/verified_baseline_*_2k/` summaries and native READ/WRITE statistics; `traces/verified_baseline_*_2k/manifest.json` |
| Matched conventional/FACIL memory-access table | `experiments/facil/facil_weight_access_comparison.py` (original FFN driver); exact trace regeneration for all shapes in `generate_matched_read_traces.py` | `results/facil/facil_step3_*_2k/` comparisons, page registries, native stats |
| Report memory-access cost figure | `experiments/facil/facil_comparison_figures.py` | `results/facil/facil_step6_comparison/read_vs_relayout.png` |
| Report TTFT component table/figures | Same comparison producer + `experiments/analytical/soc_gemm_roofline.py` | `results/facil/facil_step6_comparison/ttft_comparison.csv`, `ttft_comparison.png`, `ttft_speedups.png` |
| SoC projection roofline/accounting | `experiments/analytical/soc_gemm_roofline.py` | `results/analytical/llama3_soc_gemm_analytical/` original CSV, per-prefill JSONs and assumptions |
| PIM GEMV and optional short-prefill sensitivity | `experiments/analytical/pim_gemv_analytical.py`, `plot_pim_sensitivity.py` | `results/analytical/facil_pim_gemv_analytical/pim_gemv_model.json`, sensitivity CSV and PNG/PDF plots |
| Batch feasibility screening | `experiments/extension/batch_dispatch_feasibility.py` | `results/extension/facil_batch_decode_feasibility/` |
| Experiments 1–2: whole-step crossover and heatmaps | `experiments/extension/batch_crossover_sensitivity.py` | `results/extension/facil_batch_exp12/batch_sweep.csv`, `crossovers.csv`, `latency_*.png`, `crossover_*.png`, assumptions |
| Experiments 3–4: dynamic traces, h_max, memory | `experiments/extension/batch_trace_switching.py` | `results/extension/facil_batch_exp34/dynamic_policy_results.csv`, `switching_overhead_limits.csv`, `weight_memory_comparison.csv`, six `overhead_*.png`, assumptions |
| Experiment 5 / report baseline access-order diagnostic | `experiments/extension/relayout_bandwidth_diagnostic.py` | `results/extension/facil_batch_exp5/bandwidth_diagnostic.csv`, figure, samples, four native-statistics folders; source streams under `traces/llama3_k_v_permutation/` |
| Negative FFN-down padding result | Preserved historical experiment; source outside release tip | `results/facil/padding_negative_evidence/comparison.json`, figure; mapping alignment evidence above |
| Earlier PIM workload/timing budget | `experiments/analytical/pim_llama3_timing_budget.py` | `results/analytical/llama3_pim_workload/` |
| Earlier TTFT scenario, distinct from final table | `experiments/analytical/ttft_llama3_baseline.py` | `results/analytical/llama3_ttft/scenario.csv`; three supporting historical baseline folders |

## Supplied manuscript figures

The canonical manuscript under `paper/` includes authored composite charts. Its baseline, TTFT, PIM and padding plots derive from the evidence above. The authored batch composite filenames are `batch_dispatch_two_scenarios.png`, `batch_crossover_heatmaps.png`, `batch_dynamic_trace.png`, and `batch_switching_hmax.png`. Their underlying original numerical records are the Experiment 1–4 CSVs listed above; current producers generate the original individual latency/heatmap/overhead plots, rather than silently relabeling composite images as native simulator output.

`exp5_sequential_bandwidth.png` in the manuscript is an authored rendition of the original four native diagnostic rows. The original diagnostic figure is retained in the Experiment 5 result folder. `placement_alignment.pdf` is an authored presentation of the retained placement/compact-padding records.

## Provenance and publication boundaries

The mapper is byte-identical to its original checksummed implementation. Current config hashes match the four corrected baseline manifests. Original metadata keeps original path/source labels and hashes; paths are mapped in the active code, not rewritten inside evidence. All original full trace bytes were regenerated and checked before exclusion from Git. See [TRACE_CHECKSUMS.json](provenance/TRACE_CHECKSUMS.json) and [validation](../VALIDATION_REPORT.md).

The supplied report claims additional historical test counts beyond the current native fixture. Those limits and manuscript author placeholders are explicitly listed in [report reconciliation](REPORT_RECONCILIATION.md).
