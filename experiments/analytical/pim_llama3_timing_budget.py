#!/usr/bin/env python3
"""Llama3-8B analytical PIM timing budget.

Uses verified mapper workload counts and DRAM timing parameters.
Does NOT invent PIM MAC latency or simulate PIM hardware.
"""

from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG


import json
import re
from pathlib import Path

root = (RESULTS / "analytical/llama3_pim_workload")
data = json.loads((root / "summary.json").read_text())

records = {r["layer"]: r for r in data["records"]}

required = [
    "q_o", "k_v", "ffn_gate_up",
    "ffn_down_compact", "ffn_down_padded"
]
for name in required:
    assert name in records, f"Missing workload: {name}"

cfg = CONFIG.read_text()

def parameter(name):
    pattern = rf"(?m)^\s*{re.escape(name)}\s*=\s*([0-9.]+)"
    match = re.search(pattern, cfg)
    if not match:
        raise ValueError(f"Missing configuration parameter: {name}")
    return float(match.group(1))

tck = parameter("tCK")
tras = parameter("tRAS")
trp = parameter("tRP")

def slots_per_block(down_layout):
    return (
        2 * records["q_o"]["max_chunks_per_pu"]
        + 2 * records["k_v"]["max_chunks_per_pu"]
        + 2 * records["ffn_gate_up"]["max_chunks_per_pu"]
        + records[down_layout]["max_chunks_per_pu"]
    )

compact_block = slots_per_block("ffn_down_compact")
padded_block = slots_per_block("ffn_down_padded")

result = {
    "classification": "Analytical PIM workload and timing budget",
    "model": "Llama3-8B",
    "decoder_blocks": 32,
    "PIM_type": "AiM-style (1,1024) FP16",
    "total_PIM_units": 128,
    "DRAM_config": "LPDDR4 protocol / LPDDR5-style timing proxy",
    "tCK_ns": tck,
    "tRAS_cycles": tras,
    "tRP_cycles": trp,
    "conditional_bank_row_turnaround_ns": (tras + trp) * tck,
    "compact_slots_per_block": compact_block,
    "padded_slots_per_block": padded_block,
    "compact_slots_per_decode_token": 32 * compact_block,
    "padded_slots_per_decode_token": 32 * padded_block,
    "effective_PIM_slot_latency_ns": None,
    "PIM_GEMV_latency_ms": None,
    "unknown_components": [
        "PIM compute command latency",
        "Input-vector loading",
        "Partial-sum reduction",
        "Bank lock-step scheduling and synchronization"
    ],
    "limitations": [
        "Operation slots are optimistic workload counts",
        "DRAM turnaround timing is not PIM MAC latency",
        "No native LPDDR5 PIM simulation performed",
        "No PIM latency or speedup is claimed"
    ]
}

output = root / "timing_budget.json"
output.write_text(json.dumps(result, indent=2) + "\n")

print(json.dumps(result, indent=2))
print("\nSaved:", output)
