# Report-to-source reconciliation

The canonical supplied manuscript and PDF are retained under `paper/`. Original scientific values and model assumptions were not edited. Actual local CSV/JSON/native evidence, rather than the authoring package’s reconstructed measurements, is published under `results/`.

The primary reported numerical claims agree with those artifacts: whole-model copy-stage sum 447.28352 ms; mapping sensitivity 308.96428 ms; batch crossovers 17 and 5 at eta=0.763/rho=0; the six switching limits; 13,958,643,712 bytes per linear-weight copy; and diagnostic reads 66.198/201.6492 GB/s. The saved two-copy reference equals ideal zero-overhead adaptive execution, and no physical weight duplication is implemented.

The manuscript’s original script labels map to current paths in [SCRIPT_RENAMES.csv](SCRIPT_RENAMES.csv). They were retained in the supplied report so the scientific artifact is not silently rewritten during a structural code release.

## Verification boundaries

The native fixture permits rerunning 411 independent Python/C++ tuple comparisons, MapID 2/3 single-page uniqueness, 16,384 conventional-fallback checks, and the mixed-page routing sample. The manuscript additionally mentions 996 checks and 2,162,688 non-aliasing blocks; retained placement summaries explain some workload counts, but a standalone source/test reproducing those exact combined historical counts was not identified. Those exact two claims are **not independently revalidated** by this release. They are not replaced with invented measurements.

The standalone numerical reduction result is preserved as a historical terminal artifact. Its exact original standalone driver is not present in the active checkout. The mapper tests and native validator do not substitute for that numerical-kernel test.

The older `compare_facil_reads.py` implements a static 8-KiB-row proxy and retains that guard. It is labeled a legacy comparison and uses the recovered historical configuration. Current 2-KiB native comparisons and evidence are separate. The two FFN native comparisons have their original timing driver; Q/O and K/V saved timing evidence and exact traffic regeneration are retained, but a single original end-to-end timing driver for those earlier two comparisons was not found. Full reruns were not invented to hide that gap.

`ttft_llama3_baseline.py` preserves an earlier scenario and its smaller set of historical input summaries. The final paper-aligned TTFT producer is `facil_comparison_figures.py`; do not substitute the earlier scenario for the final comparison CSV.

The manuscript’s author names and contribution fields remain placeholders. They require the team’s actual details before coursework submission. No third-party paper PDF or duplicate presentation package is included.
