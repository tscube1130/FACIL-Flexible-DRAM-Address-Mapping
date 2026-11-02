#!/usr/bin/env python3
"""Reproducible, deliberately limited SoC prefill GEMM roofline model.

Source parameters: FACIL (HPCA 2025), Table II: NVIDIA Jetson AGX Orin
42.5 TFLOP/s FP16 peak and 204.8 GB/s theoretical DRAM peak bandwidth.

Workload: Llama3-8B FP16 *decoder linear projections* only, 32 blocks.
No timing here is measured on SoC, nor do these numbers equal full TTFT.

For each W[M,K] and input X[K,P] (P prefill tokens), Y[M,P]:
    operations = 2*M*K*P FLOPs (FMA counted as 2)
    bytes = 2*M*K + 2*K*P + 2*M*P
    compute_time = operations / 42.5e12
    memory_time = bytes / 204.8e9
    ideal_gemm_time = max(compute_time, memory_time)
Summation over the 7 modeled projections per decoder block and 32 blocks.

Assumptions: one full FP16 weight read and one input/output traffic each GEMM;
perfect compute-memory overlap, full specified peak service, no GPU-specific
kernel/caching overhead, no attention-score/value matmuls, no nonlinearities,
no embeddings/output head or other prefill work. Model, not a measurement.
"""
from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG


import argparse
import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

PEAK_FP16_FLOPS_PER_S = 42.5e12
PEAK_THEORETICAL_BW_BYTES_PER_S = 204.8e9
BYTES_PER_FP16 = 2
BLOCKS = 32
DEFAULT_PREFILL_TOKENS = (8, 16, 32, 64, 128)


@dataclass(frozen=True)
class Projection:
    name: str
    m: int
    k: int
    count_per_block: int


PROJECTIONS = (
    Projection("q_o", 4096, 4096, 2),
    Projection("k_v", 1024, 4096, 2),
    Projection("ffn_gate_up", 14336, 4096, 2),
    Projection("ffn_down", 4096, 14336, 1),
)


def projection_work(proj: Projection, tokens: int) -> dict:
    if tokens < 1:
        raise ValueError("Prefill token count must be >= 1")
    weights_b = BYTES_PER_FP16 * proj.m * proj.k
    input_b = BYTES_PER_FP16 * tokens * proj.k
    output_b = BYTES_PER_FP16 * tokens * proj.m
    flops = 2 * proj.m * proj.k * tokens
    arithmetic_time = flops / PEAK_FP16_FLOPS_PER_S
    memory_time = (weights_b + input_b + output_b) / PEAK_THEORETICAL_BW_BYTES_PER_S
    return {
        "name": proj.name,
        "shape_m_k": [proj.m, proj.k],
        "count_per_block": proj.count_per_block,
        "weight_bytes_per_matrix": weights_b,
        "input_bytes_per_matrix": input_b,
        "output_bytes_per_matrix": output_b,
        "flops_per_matrix": flops,
        "compute_floor_ms_per_matrix": 1000 * arithmetic_time,
        "memory_floor_ms_per_matrix": 1000 * memory_time,
        "roofline_ms_per_matrix": 1000 * max(arithmetic_time, memory_time),
        "bottleneck": "memory" if memory_time >= arithmetic_time else "compute",
    }


def model(tokens: int) -> dict:
    details = [projection_work(p, tokens) for p in PROJECTIONS]
    total_flops = sum(d["flops_per_matrix"] * d["count_per_block"] * BLOCKS for d in details)
    weight_bytes = sum(d["weight_bytes_per_matrix"] * d["count_per_block"] * BLOCKS for d in details)
    input_output_bytes = sum(
        (d["input_bytes_per_matrix"] + d["output_bytes_per_matrix"])
        * d["count_per_block"] * BLOCKS
        for d in details
    )
    # Each independent GEMM is accounted separately, exactly as the stated model.
    soc_ms = sum(d["roofline_ms_per_matrix"] * d["count_per_block"] * BLOCKS for d in details)
    return {
        "prefill_tokens": tokens,
        "linear_gemm_count": BLOCKS * sum(p.count_per_block for p in PROJECTIONS),
        "weight_GiB": weight_bytes / (1024**3),
        "input_output_MiB": input_output_bytes / (1024**2),
        "total_linear_flops_TF": total_flops / 1e12,
        "peak_compute_floor_ms": 1e3 * total_flops / PEAK_FP16_FLOPS_PER_S,
        "peak_memory_floor_ms": 1e3 * (weight_bytes + input_output_bytes) / PEAK_THEORETICAL_BW_BYTES_PER_S,
        "sum_per_gemm_ideal_roofline_ms": soc_ms,
        "all_individual_gemms_memory_bound": all(d["bottleneck"] == "memory" for d in details),
    }


def self_test() -> None:
    assert len(PROJECTIONS) == 4
    assert sum(p.count_per_block for p in PROJECTIONS) == 7
    weights_per_block = sum(p.m * p.k * 2 * p.count_per_block for p in PROJECTIONS)
    assert weights_per_block == 416 * 1024 * 1024
    assert weights_per_block * BLOCKS == 13 * 1024**3
    assert set(p.name for p in PROJECTIONS) == {"q_o", "k_v", "ffn_gate_up", "ffn_down"}
    # Independent analytic consistency and nonnegative latency.
    for p in PROJECTIONS:
        d = projection_work(p, 8)
        assert d["flops_per_matrix"] == p.m * p.k * 16
        assert d["weight_bytes_per_matrix"] == p.m * p.k * 2
        assert d["roofline_ms_per_matrix"] >= d["compute_floor_ms_per_matrix"]
        assert d["roofline_ms_per_matrix"] >= d["memory_floor_ms_per_matrix"]
    previous = 0
    for prefill in DEFAULT_PREFILL_TOKENS:
        result = model(prefill)
        assert result["linear_gemm_count"] == 224
        assert result["weight_GiB"] == 13
        assert result["sum_per_gemm_ideal_roofline_ms"] >= previous
        assert result["sum_per_gemm_ideal_roofline_ms"] >= result["peak_compute_floor_ms"] - 1e-8
        assert result["sum_per_gemm_ideal_roofline_ms"] >= result["peak_memory_floor_ms"] - 1e-8
        previous = result["sum_per_gemm_ideal_roofline_ms"]
    print("SELF-TEST: PASS (32 blocks, 224 GEMMs, 13 GiB weights, FLOPs/bytes/time checks)")


def run(output_dir: Path, prefills: tuple[int, ...]) -> None:
    self_test()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [model(p) for p in prefills]
    csv_path = output_dir / "soc_gemm_roofline.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=tuple(results[0].keys()))
        w.writeheader()
        w.writerows(results)

    for prefill in prefills:
        detail_path = output_dir / f"gemm_details_P{prefill}.json"
        detail_path.write_text(json.dumps({
            "prefill_tokens": prefill,
            "projections": [projection_work(p, prefill) for p in PROJECTIONS],
        }, indent=2) + "\n", encoding="utf-8")

    payload = {
        "classification": "ANALYTICAL SCENARIO ONLY - not DRAMsim3/GPU measurement or full TTFT",
        "model": "sum over each independent linear GEMM: max(FLOPs/peak_FLOPs_per_s, (weights+input+output)_bytes/peak_BW_bytes_per_s)",
        "source_platform": "FACIL HPCA 2025 Table II: NVIDIA Jetson AGX Orin 64 GB",
        "peak_fp16_flops_per_s": PEAK_FP16_FLOPS_PER_S,
        "peak_theoretical_dram_bandwidth_bytes_per_s": PEAK_THEORETICAL_BW_BYTES_PER_S,
        "weight_dtype": "FP16",
        "blocks": BLOCKS,
        "projections": [asdict(p) for p in PROJECTIONS],
        "results": results,
        "excluded": [
            "attention-score and attention-value GEMM", "rotary embeddings",
            "nonlinear activations and normalization", "embedding and LM output head",
            "KV-cache traffic", "kernel launches and GPU utilization effects",
            "re-layout", "actual PIM decode GEMV", "memory mapping penalty",
        ],
        "model_assumptions": [
            "each independent GEMM loads weights once from external DRAM",
            "each GEMM reads its activation input and writes its output once in FP16",
            "all modeled transfers are charged at paper's theoretical peak bandwidth",
            "ideal overlap of math and memory within each GEMM; no overlap assumed between separate GEMMs",
            "all 7 linear projections per block for 32 blocks are counted; no attention/embedding/output-head computation",
        ],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (output_dir / "assumptions_and_results.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print("SoC GEMM ideal peak-roofline model — Llama3-8B FP16 linear projections only")
    print("Source: FACIL Table II Jetson, 42.5 TFLOP/s, 204.8 GB/s theoretical peak")
    print("Tokens | GEMMs |  Weights |  TFLOPs | Ideal SoC linear GEMM ms | Bottleneck")
    for r in results:
        print(
            f"{r['prefill_tokens']:>6} | {r['linear_gemm_count']:>5} | "
            f"{r['weight_GiB']:>5.1f} GiB | {r['total_linear_flops_TF']:>7.3f} | "
            f"{r['sum_per_gemm_ideal_roofline_ms']:>24.3f} | "
            f"{'Memory' if r['all_individual_gemms_memory_bound'] else 'Mixed'}"
        )
    print("NOTE: Not real SoC GEMM execution time and NOT end-to-end TTFT.")
    print(f"Saved: {csv_path}")
    print(f"Saved: {output_dir / 'assumptions_and_results.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=(RESULTS / "analytical/llama3_soc_gemm_analytical"))
    parser.add_argument("--prefill", nargs="+", type=int, default=DEFAULT_PREFILL_TOKENS)
    parser.add_argument("--self-test", action="store_true", help="Only run built-in validation")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.prefill or any(p <= 0 for p in args.prefill) or len(set(args.prefill)) != len(args.prefill):
            parser.error("Prefill values must be distinct positive integers")
        run(args.output, tuple(args.prefill))


if __name__ == "__main__":
    main()
