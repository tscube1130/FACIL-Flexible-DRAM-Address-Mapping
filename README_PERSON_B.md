# FACIL Person B — Baseline Re-layout Starter

Use from the root of your existing `DRAMsim3/DRAMsim3-master` checkout in WSL.

## Files

- `generate_relayout_trace.py`: writes *two separate traces* for the same FP16 matrix: a source PIM-weight DRAM read and a destination SoC-scratch DRAM write. Checks count, alignment, and non-overlap.
- `measure_relayout.py`: runs both traces against the chosen DRAMsim3 configuration. Uses bounded cycle search to estimate the **minimum cycle budget required to complete each trace**, without a manual sweep.

## Install into your existing project

Copy the two `.py` files into the `personB/` directory under the DRAMsim3 checkout. From the checkout root:

```sh
python3 personB/generate_relayout_trace.py
python3 personB/measure_relayout.py
cat personB/results/relayout_v1/summary.json
```

Default parameters: 512 x 1024 FP16, 128 B per transaction, 1 MiB weights; read 8192 transactions; write 8192 transactions; source `0x0`; destination `0x10000000`. The two phases account for **2 MiB** of DRAM copy traffic in total.

Outputs: `personB/traces/relayout/copy_read.trace`, `copy_write.trace`, and `manifest.json`; `personB/results/relayout_v1/read/dramsim3.txt`, `write/dramsim3.txt`, `summary.json`.

## IMPORTANT LIMITATIONS

1. The baseline's logical **rearrangement/permutation is not modeled yet**. Person A's mapper must supply layout-specific source/destination addresses for a faithful FACIL comparison. This is **only the memory movement component**.
2. Separate read and write stages assume a *serialized* copy; realistic hardware could pipeline reads and writes, and there is no modeled CPU/GPU conversion or buffer/cache effect. As such, this is a **serialized DRAM-only proxy**, neither an accurate end-to-end time nor a general upper/lower bound for real re-layout.
3. The memory controller remains `LPDDR4` with selected LPDDR5-6400-style timings; **not native LPDDR5**.
4. Completion cycles are upper bounds with 256-cycle resolution, not exact per-request callback timing.
5. Do not compare 1-MiB copy time directly to the paper's full Llama3-8B ~100/300-ms TTFT plot. Compare qualitative trends and clearly stated scaling/model assumptions.
