#!/usr/bin/env python3
"""Llama3-8B linear-layer TTFT roofline scenario.
Measured DRAMsim3 copy bounds + paper platform peak specs.
Not a full inference or native PIM timing measurement.
"""

from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
import json
import csv

root = ROOT
results = RESULTS
output = results / "analytical/llama3_ttft"
output.mkdir(parents=True, exist_ok=True)

# Jetson Orin platform specs from FACIL Table II
peak_flops = 42.5e12
peak_bw = 204.8e9
facil_gemm_penalty = 1.021

# (name, output features, input features, count/block, result source)
layers = [
    ("q_o", 4096, 4096, 2, "baseline/llama3_q_o"),
    ("k_v", 1024, 4096, 2, "baseline/llama3_k_v"),
    ("ffn_gate_up", 14336, 4096, 2, "baseline/llama3_ffn_gate_up"),
    ("ffn_down", 4096, 14336, 1, "baseline/llama3_ffn_gate_up"),
]

blocks = 32
copy_us_per_block = 0
details = []

for name, m, k, count, source in layers:
    path = results / source / "summary.json"
    if not path.exists():
        raise SystemExit(f"Missing required result: {path}")

    data = json.loads(path.read_text())
    assert data["matrix_bytes"] == 2 * m * k

    copy_us = data["serialized_copy"]["estimated_time_us_upper_bound"]
    copy_us_per_block += count * copy_us
    details.append((name, m, k, count, copy_us, source))

copy_ms = blocks * copy_us_per_block / 1000
rows = []

for tokens in [8, 16, 32, 64, 128]:
    soc_seconds_per_block = 0

    for name, m, k, count, _, _ in details:
        flops = 2 * m * k * tokens

        # Weights read once per prefill GEMM;
        # minimum activation and output transfer accounting.
        bytes_transferred = (
            2 * m * k +
            2 * tokens * k +
            2 * tokens * m
        )

        roofline_seconds = max(
            flops / peak_flops,
            bytes_transferred / peak_bw
        )
        soc_seconds_per_block += count * roofline_seconds

    soc_ms = blocks * soc_seconds_per_block * 1000
    baseline_scenario = soc_ms + copy_ms
    facil_scenario = soc_ms * facil_gemm_penalty

    rows.append({
        "prefill_tokens": tokens,
        "soc_linear_roofline_ms": round(soc_ms, 6),
        "copy_proxy_ms": round(copy_ms, 6),
        "baseline_scenario_ms": round(baseline_scenario, 6),
        "facil_scenario_ms": round(facil_scenario, 6),
        "scenario_ratio": round(
            baseline_scenario / facil_scenario, 4
        ),
    })

with (output / "scenario.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print("Llama3-8B: 32 decoder blocks, seven linear matrices/block")
print("MODEL: peak-roofline prefill + serialized DRAM copy proxy")
print("NOTE: not measured TTFT; excludes attention/nonlinear overhead")
print("NOTE: FFN-down reuses FFN gate/up sequential size proxy")
print(f"Total modeled copy proxy: {copy_ms:.6f} ms")
print()
print("Tokens | SoC roofline | Baseline scenario | FACIL scenario | Ratio")
for r in rows:
    print(
        f"{r['prefill_tokens']:>6} | "
        f"{r['soc_linear_roofline_ms']:>11.3f} | "
        f"{r['baseline_scenario_ms']:>17.3f} | "
        f"{r['facil_scenario_ms']:>14.3f} | "
        f"{r['scenario_ratio']:>5.2f}x"
    )
print(f"\nSaved: {output / 'scenario.csv'}")
