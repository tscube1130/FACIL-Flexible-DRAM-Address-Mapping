# Scope and limitations

- The original FACIL paper provides re-layout-free shared access. This reproduction implements a reference mapper and a native DRAMsim3 address-decoding/routing fixture; it does not reproduce the paper’s OS or physical controller.
- The LPDDR4 command protocol uses selected LPDDR5-style parameters and synthetic 2-KiB aggregate rows. Native LPDDR5 CK/WCK behavior and AiM MAC commands are absent.
- Baseline 447.28352 ms sums serialized traffic-stage brackets. CPU/GPU rearrangement, caches and overlap are absent. Write callbacks are buffer acknowledgements and need not mean commands issued or data drained.
- SoC numbers are roofline calculations using assumed peak bandwidth/compute. No GPU/NPU kernels were timed.
- Prefill figures cover projection-only components. Attention, nonlinearities, norms, embeddings/output head, KV traffic, launches and real runtime behavior are excluded. They are not end-to-end TTFT bounds or measurements.
- The 308.96428-ms mapping increment extrapolates sequential-read differences. It is not measured GEMM slowdown and cannot be directly compared with the paper’s GPU layout penalty.
- PIM 75/100/200-ns waves, 5.3248-ms linear-pass time and illustrative 20-ms timing are assumptions. Input broadcast, reduction and synchronization are excluded. Compact FFN-down placement spans multiple PUs and does not establish an efficient hardware kernel.
- Eta=0.763 is a sensitivity anchor derived from a different memory-utilization context, not measured GEMM efficiency. Rho>0 is hypothetical reuse, not demonstrated AiM behavior.
- Decode estimates omit attention/KV and actual hardware switching. The offline optimum knows future batches; online hysteresis is evaluated separately. No hardware dispatch speedup or full TTLT is demonstrated.
- Duplication is a conceptual two-copy reference. Our extension does not duplicate weights. Weight-only storage excludes metadata, KV and temporary conversion buffers.
- The 4-MiB bandwidth diagnostic does not replace or fully decompose the complete re-layout estimate. Its write throughput counts issued commands, not completed writes.
- Some historical verification counts in the supplied manuscript have retained summaries but no standalone producing test for those exact counts. See [report reconciliation](REPORT_RECONCILIATION.md). The native 411-comparison and complete-page/fallback checks are independently rerun.
- Original saved JSON metadata retains original source/path/hash labels as provenance. The structural refactor changes script hashes and output-location strings on regeneration; numerical values, trace bytes and original evidence remain unchanged.
- Two retained upstream optional utilities use Python 2 syntax and are outside the active FACIL Python 3 workflow. Upstream thermal support requires its optional submodule and extra libraries and was not validated.
- The supplied manuscript still has author/team placeholders. This repository preparation does not certify the separate coursework submission form or author fields as complete.
