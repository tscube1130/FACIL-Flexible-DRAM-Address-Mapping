# FACIL two-person implementation kit — 21 October 2026

This kit **adds** Person A's standalone FACIL AiM address mapping model and Person B's prefill-only analytical timing model. It does **not** change your existing DRAMsim3 build/configuration or overwrite the completed re-layout experiments.

## Install into your existing WSL repository

Place `FACIL_A_B_Implementation_Kit.zip` inside `~/DRAMsim3/DRAMsim3-master/` (copy via Windows Explorer into `\\wsl.localhost\Ubuntu-24.04\home\sukhjot\DRAMsim3\DRAMsim3-master`). Then run:

```bash
cd ~/DRAMsim3/DRAMsim3-master
unzip -o FACIL_A_B_Implementation_Kit.zip
source ~/facil-venv/bin/activate
```

ZIP extraction creates `personA/`, adds **only** `personB/ttft_model.py` to the existing `personB/` folder, and adds `tests/`, `fixtures/` and `example_outputs/`. Your existing `generate_relayout_trace.py`, `measure_relayout.py`, real results, configs, and binary remain untouched.

## Person A — Mapping and correctness

```bash
python3 personA/facil_mapper.py --rows 2048 --cols 8192 --sample 16
python3 personA/facil_mapper.py --rows 2048 --cols 65536 --sample 16
python3 personA/facil_mapper.py --rows 4096 --cols 4096 --sample 12
python3 personA/facil_mapper.py --rows 4096 --cols 14336 --sample 12
python3 personA/visualize_mapper.py
python3 -m unittest discover -s tests -v
```

**Expected Figure 10 outcomes, 2 channels / 1 rank / 16 banks per channel / 2 MiB huge pages / AiM chunk 1×1024 FP16:**

- 2048×8192: MapID **3**, no intra-row PU partitioning.
- 2048×65536: MapID **5**, each 128 KiB matrix row splits across two PUs.
- For a geometry matching Person B's proxy (**4 channels, 2 ranks, 16 banks/rank**), `--channels 4 --ranks 2` can produce *different* MapIDs. Do not compare those MapIDs as though the physical configuration were unchanged.

The code implements Figure 9's rounded-row-width selector and an explicit Figure 8/10-inspired bit permutation:

`[row high][bank][rank][channel][row low (MapID bits)][chunk column][byte offset]`

A 2 KiB AiM chunk uses 32-byte physical DRAM transfers (**5 byte-offset bits and 6 chunk-column bits**) as illustrated in the paper. Your DRAMsim3 proxy uses **128-byte input transactions**, which each cover four such 32-byte transfers; these are separate modeling granularities.

`PerHugePageMapper` supports different MapIDs on different 2 MiB pages. Tests validate distinct decode tuples, inverse round-trips, chunk placement and matrix-row PU partitioning.

**Important limitations:** Non-power-of-two matrix columns (e.g. 14336) are rounded up by the MapID selector, but the compact row-major logical tensor may not satisfy all ideal PIM row confinement/alignment properties. Verify padding/stride before claiming full kernel compatibility. This is a *standalone reference mapper*; DRAMsim3 **does not** accept a MapID from this Python class. A separately verified address-field encoder or controller modification is still required to translate its results into DRAMsim3 traces.

## Person B — Estimate prefill-only TTFT *component* from your actual data

Your completed DRAMsim3 run already saved:
`personB/results/relayout_v1/summary.json` for **512×1024 FP16, 1 MiB**, reporting a **serialized DRAM-only copy upper-bound estimate of 18.48 µs**.

Run:

```bash
python3 personB/ttft_model.py \
  --summary personB/results/relayout_v1/summary.json \
  --rows 512 --cols 1024 \
  --output personB/results/ttft_model_512x1024
```

Outputs:

- `ttft_scenario.csv` — per-prefill-length equations and modeled values.
- `assumptions_and_provenance.json` — every numerical input, source and limitations.
- `prefill_times_analytical.png` — modeled baseline vs FACIL single-layer prefill components.
- `speedup_analytical.png` — *scenario* speedup, **not** measured FACIL speedup.

This uses FACIL Table II's Jetson reference **204.8 GB/s** peak bandwidth and **42.5 FP16 TFLOPS**, with default *ideal* compute utilization `--gpu-util 1.0`. It assumes a single pass over weights and one pass over inputs/outputs per prefill, then takes the roofline max of memory time and math time. You can perform sensitivity checks with `--gpu-util 0.5`, but no assumed utilization should be called a measurement. Option `--facil-penalty 0.021` uses the paper's worst-case Jetson layout slowdown (Table III) as an **external reference sensitivity**, NOT a measured slowdown in your reduced-size hardware.

**The formula is prefill only:**

`T_baseline,component = analytical_SOC_GEMM + measured_DRAM_copy_proxy`

`T_FACIL,component = analytical_SOC_GEMM × (1 + assumed_GEMM_layout_penalty)`

The ordinary **decode GEMV term is excluded from TTFT**. Full TTLT and real near-bank PIM GEMV/reduction hardware modeling still need a separate model. This is a modeled **single-layer prefill component**, not measured Llama3-8B TTFT, and cannot claim the paper's absolute speedups.

## Included offline preview

The files under `example_outputs/ttft_512x1024/` were generated from `fixtures/user_reported_relayout_1MiB_summary.json`, a clearly identified transcription of **your** 1 MiB run (9.36 µs read + 9.12 µs write). The analytical GPU values were **calculated**, not run on a real Jetson. You should re-run the command above against your actual WSL `summary.json` to generate final reproducible plots.

## What comes next (not yet implemented)

1. **Bridge** Person A's `(channel,rank,bank,row,column)` mapping to the *actual* DRAMsim3 configured decoder. Verify raw address -> decoder fields against samples, and test collision freedom across 2 MiB pages with different MapIDs.
2. **Experiment** compare conventional SoC mapping and FACIL mapping under equivalent realistic GEMM/GEMV traces. Record row-hit rate, bank utilization, latency, access count. Do not interpret a mapping-only model as PIM compute.
3. **Original addition:** interference-aware selection between *two legal* bank/channel interleave orders (or another mapping extension), with explicit correctness tests and repeated DRAMsim3 traces under background traffic. Compare against unmodified FACIL, without forcing a positive result.
4. Build an explicit near-bank PIM GEMV + reduction analytical model and TTLT (paper Figure 14), labeling all assumptions.
5. Report differences from Figures 6/13/14 and the **LPDDR4-protocol with LPDDR5-style timing approximation**. The proxy is not native LPDDR5.

## Paper grounding

FACIL: *Flexible DRAM Address Mapping for SoC-PIM Cooperative On-device LLM Inference*, HPCA 2025. Figure 8 (bit layout), Figure 9 (MapID selector), Figure 10 (width-based MapID examples); Table II (Jetson reference), Figure 6 and Figure 13 (TTFT), Figure 14 (TTLT). Original authors use a customized DRAMsim-derived PIM simulator and LPDDR5/X timing; this starter is deliberately a reduced-scope reconstruction.
