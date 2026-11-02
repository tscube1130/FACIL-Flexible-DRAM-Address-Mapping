# Reproducibility

Run commands from the repository root in Linux/WSL. Python 3.12, GCC/G++ 13, CMake 3.28 and the package versions in [the environment record](provenance/VALIDATED_ENVIRONMENT.json) were validated. Install a compiler, CMake and Python’s venv support through your operating system if absent. Optional thermal simulation is outside this validation.

## Build and meaningful checks

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 2
python -B -m unittest discover -s tests -v
python -B scripts/validate_release.py --regenerate-traces
```

The last command was run successfully. It compiles/runs the original C++ tests, compiles the native decoder verifier, checks the mixed-page sample and one-WRITE EOF fixture, runs baseline byte-layout correctness, reproduces analytical/extension outputs in an isolated results tree, checks original numerical files, and regenerates/checksums all baseline and matched input streams. It uses only small routing/regression simulator runs. Full matrix simulations are **not** rerun.

Logs from a validation run go to `.validation/validation.log` and `.validation/validation.json`. Original `results/` files are not overwritten. Full input regeneration uses temporary space of several hundred MB; the temporary run directory is removed on completion.

For shorter read-only checks:

```bash
python -B -m unittest discover -s tests -v
python -B experiments/analytical/soc_gemm_roofline.py --self-test
python -B experiments/baseline/verify_baseline_relayout.py
```

## Native decoder verifier

```bash
g++ -std=c++11 -Isrc -Iext/headers -Iext/fmt/include \
  tests/native/verify_facil_decoder.cc -L. -ldramsim3 \
  -Wl,-rpath,"$PWD" -o build/verify_facil_decoder
./build/verify_facil_decoder \
  configs/LPDDR5_6400_APPROX_v1.ini \
  results/facil/facil_native_validation/pages.txt \
  results/facil/facil_native_validation/expected.tsv \
  build/verified_channel_counts.txt
```

Expected: 411 tuple checks, MapID 2/3 uniqueness and conventional fallback pass. Expected mixed-page channel counts are `(72,8,8,8)`; the release validator also verifies those using the fresh simulator. The native registry fixture is not an OS/PTE implementation.

## Reproduce analytical models and Experiments 1–4

The preparation helper copies only immutable input summaries to a **new** directory. Scripts use repository-relative source/config paths and `FACIL_RESULTS_ROOT` for isolated results. The following actual script sequence was exercised by the release validator from a different working directory:

```bash
python -B scripts/prepare_reproduction.py --output .reproduce/results
export FACIL_RESULTS_ROOT="$PWD/.reproduce/results"
python -B experiments/analytical/soc_gemm_roofline.py
python -B experiments/facil/facil_comparison_figures.py
python -B experiments/analytical/pim_gemv_analytical.py
python -B experiments/analytical/plot_pim_sensitivity.py
python -B experiments/extension/batch_dispatch_feasibility.py
python -B experiments/extension/batch_crossover_sensitivity.py
python -B experiments/extension/batch_trace_switching.py
python -B experiments/analytical/pim_llama3_timing_budget.py
python -B experiments/analytical/ttft_llama3_baseline.py
python -B mapping/validate_placement.py
python -B mapping/check_lockstep_groups.py
unset FACIL_RESULTS_ROOT
```

Do not delete saved result folders to bypass preservation guards. Choose a fresh scratch path instead. Generated numerical CSV/JSON values match original evidence; regenerated source hashes and output-location strings necessarily reflect the new code location. The validator explicitly compares scientific data while allowing those two provenance differences.

The final TTFT source is `facil_comparison_figures.py`. `ttft_llama3_baseline.py` reproduces an earlier preserved scenario; it is not the final paper-aligned TTFT comparison.

## Regenerate baseline traces without simulations

Full streams are omitted from the Git tip because they are deterministic, large and redundant. The original manifests stay under `traces/verified_baseline_*_2k/`; do not overwrite them. Generate into new directories:

```bash
python -B experiments/baseline/generate_verified_baseline_traces_2k.py --rows 4096 --cols 4096 --output .reproduce/traces/verified_baseline_q_o_2k
python -B experiments/baseline/generate_verified_baseline_traces_2k.py --rows 1024 --cols 4096 --output .reproduce/traces/verified_baseline_k_v_2k
python -B experiments/baseline/generate_verified_baseline_traces_2k.py --rows 14336 --cols 4096 --output .reproduce/traces/verified_baseline_ffn_gate_up_2k
python -B experiments/baseline/generate_verified_baseline_traces_2k.py --rows 4096 --cols 14336 --output .reproduce/traces/verified_baseline_ffn_down_2k
```

Each original read/write SHA-256 and request-mapping digest was matched for all four shapes. Manifest path fields change with the scratch location; trace bytes do not. `scripts/validate_release.py --regenerate-traces` performs these comparisons automatically.

The lightweight mechanical helper reproduces the two matched-read streams for each shape. It does not infer or regenerate measured timing:

```bash
python -B experiments/facil/generate_matched_read_traces.py q_o --output .reproduce/matched/q_o
python -B experiments/facil/generate_matched_read_traces.py k_v --output .reproduce/matched/k_v
python -B experiments/facil/generate_matched_read_traces.py ffn_gate_up --output .reproduce/matched/ffn_gate_up
python -B experiments/facil/generate_matched_read_traces.py ffn_down --output .reproduce/matched/ffn_down
```

All eight generated stream files matched the original saved checksums. Native page registries and native statistics remain with their result folders.

## Optional full traffic simulations — not part of lightweight validation

These commands can be expensive. Their input paths and CLI parsers were checked, but the full workloads were not rerun during release preparation.

After generating baseline inputs above, measure each shape with distinct output paths:

```bash
python -B experiments/baseline/measure_relayout.py --trace-dir .reproduce/traces/verified_baseline_q_o_2k --results .reproduce/measured/q_o
python -B experiments/baseline/measure_relayout.py --trace-dir .reproduce/traces/verified_baseline_k_v_2k --results .reproduce/measured/k_v
python -B experiments/baseline/measure_relayout.py --trace-dir .reproduce/traces/verified_baseline_ffn_gate_up_2k --results .reproduce/measured/ffn_gate_up
python -B experiments/baseline/measure_relayout.py --trace-dir .reproduce/traces/verified_baseline_ffn_down_2k --results .reproduce/measured/ffn_down
```

The original FFN native comparison driver is preserved, with updated paths:

```bash
python -B scripts/prepare_reproduction.py --output .reproduce/native --baseline-only
export FACIL_RESULTS_ROOT="$PWD/.reproduce/native"
export FACIL_TRACES_ROOT="$PWD/.reproduce/traces"
python -B experiments/facil/facil_weight_access_comparison.py ffn_gate_up
python -B experiments/facil/facil_weight_access_comparison.py ffn_down
unset FACIL_RESULTS_ROOT FACIL_TRACES_ROOT
```

The exact original Q/O and K/V input streams, completion brackets, native statistics and registries remain preserved. A standalone original timing-search driver for those two earlier comparisons was not identified; see [reconciliation](REPORT_RECONCILIATION.md). Their saved evidence and exact traffic regeneration are validated, without claiming to have rerun their full timing searches.

## Optional Experiment 5 simulator rerun

Its source traces are committed because they are modest and essential. Four samples and their native result files are original evidence. To rerun into a new root:

```bash
FACIL_RESULTS_ROOT="$PWD/.reproduce/diagnostic" \
FACIL_TRACES_ROOT="$PWD/traces" \
python -B experiments/extension/relayout_bandwidth_diagnostic.py
```

This bounded multi-run diagnostic was not rerun during release preparation. Saved evidence was checked read-only: 32,768 distinct transactions/stage, equal address sets and offered times per order comparison, source sampling equivalence, native counters and B/ns arithmetic. READ conditions count completed reads; WRITE conditions count issued commands.

## Path configuration and safety

`experiments/paths.py` exposes optional `FACIL_RESULTS_ROOT`, `FACIL_TRACES_ROOT`, `FACIL_SIM_BINARY`, and `FACIL_CONFIG` overrides. Defaults select this repository and the current corrected configuration. The baseline trace generator intentionally keeps outputs inside the repository and refuses overwrites. Always clear `FACIL_PAGE_MAP_FILE` and `FACIL_CHANNEL_XOR` for conventional measurements; the release validator does so explicitly.

The older `experiments/facil/compare_facil_reads.py` retains its 8-KiB guard and uses `configs/LPDDR5_6400_APPROX_8K_HISTORICAL.ini`. It is not the final native 2-KiB method. Keep historical and current results distinct.

No `.tools/` content, credentials, build output or `.validation/` scratch data is committed. Original result JSONs retain historical paths as provenance; use the [result index](RESULTS_INDEX.md) to locate their current physical files.
