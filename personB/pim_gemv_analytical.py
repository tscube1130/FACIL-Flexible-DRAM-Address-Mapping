#!/usr/bin/env python3
"""Parameterised, illustrative AiM-style PIM GEMV model.

This does NOT reproduce a PIM instruction simulator. The only FACIL-paper
parameters used are chunk size (1 x 1024 FP16) and architectural concept of
near-bank parallel processing. Total PUs, transfer bandwidth, and per-chunk
service latency are explicit scenario assumptions. No paper-calibrated PIM
speedup is claimed.

Default two-layer network: input 1024 -> hidden 512 -> output 1024.
A one-token input is a GEMV; modeled linear portion is NOT full TTFT.
"""
import argparse
import csv
import json
import math
from pathlib import Path

LAYERS = [("linear_1", 512, 1024), ("linear_2", 1024, 512)]


def estimate_layer(name, rows, cols, num_pus, chunk_cols, chunk_ns,
                   element_bytes, ranks_total, bandwidth_gbs):
    if min(rows, cols, num_pus, chunk_cols, element_bytes, ranks_total) <= 0:
        raise ValueError("All counts and matrix dimensions must be positive")
    if chunk_ns <= 0 or bandwidth_gbs <= 0:
        raise ValueError("Timing and bandwidth must be positive")
    if cols > chunk_cols:
        raise ValueError("This first model is scoped to <= 1 PIM chunk per matrix row; "
                         "partial reduction for wider rows is not yet implemented")
    waves = math.ceil(rows / num_pus)
    # Idealised parallel waves: one independent near-bank PU per matrix row.
    compute_us = waves * chunk_ns / 1000.0
    # Vector is assumed transferred once to each rank for broadcast to banks,
    # and output transferred back once. This may over/under-count a real device.
    input_bytes = cols * element_bytes * ranks_total
    output_bytes = rows * element_bytes
    io_us = (input_bytes + output_bytes) / (bandwidth_gbs * 1000.0)
    return {"layer": name, "rows": rows, "cols": cols,
            "weight_bytes": rows * cols * element_bytes,
            "total_pu_count": num_pus, "waves": waves,
            "assumed_chunk_service_ns": chunk_ns,
            "model_compute_us": compute_us, "model_vector_io_us": io_us,
            "estimated_linear_layer_us": compute_us + io_us}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunk-ns", type=float, nargs="+", required=True,
                        help="Illustrative per-wave service times in ns; NOT from FACIL paper")
    parser.add_argument("--channels", type=int, default=4)
    parser.add_argument("--ranks-per-channel", type=int, default=2)
    parser.add_argument("--banks-per-rank", type=int, default=16)
    parser.add_argument("--pim-chunk-cols", type=int, default=1024)
    parser.add_argument("--element-bytes", type=int, default=2)
    parser.add_argument("--external-bandwidth-gbs", type=float, default=204.8,
                        help="Assumed theoretical external bandwidth, not effective throughput")
    parser.add_argument("--out", type=Path,
                        default=Path("personB/results/pim_gemv_analytical"))
    args = parser.parse_args()
    pus = args.channels * args.ranks_per_channel * args.banks_per_rank
    ranks_total = args.channels * args.ranks_per_channel
    per_layer, summary = [], []
    for t in args.chunk_ns:
        layers = [estimate_layer(n, r, c, pus, args.pim_chunk_cols, t,
                                 args.element_bytes, ranks_total,
                                 args.external_bandwidth_gbs)
                  for n, r, c in LAYERS]
        per_layer.extend(layers)
        summary.append({"assumed_chunk_ns": t,
                        "linear_only_single_token_prefill_us": sum(x["estimated_linear_layer_us"] for x in layers),
                        "total_matrix_weight_MiB": sum(x["weight_bytes"] for x in layers) / (1024 ** 2),
                        "total_waves": sum(x["waves"] for x in layers),
                        "modeled_total_vector_io_us": sum(x["model_vector_io_us"] for x in layers)})
    args.out.mkdir(parents=True, exist_ok=True)
    def write_csv(path, records):
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0]))
            w.writeheader()
            w.writerows(records)
    write_csv(args.out / "pim_gemv_layers.csv", per_layer)
    write_csv(args.out / "one_token_sensitivity.csv", summary)
    (args.out / "provenance.json").write_text(json.dumps({
        "classification": "illustrative analytical PIM GEMV, NOT measured or paper-calibrated",
        "model": "two-layer FP16 MLP, 1024 -> 512 -> 1024, 1 token",
        "layers": [{"name": n, "M_rows": r, "K_cols": c} for n, r, c in LAYERS],
        "paper_grounding": "FACIL paper section II-B, AiM chunk (1,1024) in FP16",
        "scenario_assumptions": {
            "channels": args.channels,
            "ranks_per_channel": args.ranks_per_channel,
            "banks_per_rank": args.banks_per_rank,
            "ideal_parallel_pus": pus,
            "pim_chunk_cols": args.pim_chunk_cols,
            "assumed_per_wave_chunk_ns": args.chunk_ns,
            "external_peak_GBps": args.external_bandwidth_gbs,
            "input_vector_replication": "one copy to each rank",
            "execution": "serialized waves + vector input/output transfers"
        },
        "method": "sum_layer(ceil(M/PUs)*t_wave + (K*dtype*num_ranks+M*dtype)/BW_ext)",
        "excluded": ["ACT/PRE commands", "PIM instruction/control overhead", "PIM input register contention",
                     "reduction overhead", "nonlinear activations", "attention", "normalization", "other LLM layers"],
        "interpretation": "Only a PIM-executed, one-token prefill linear-component scenario. Ordinary decode GEMV belongs to TTLT, not SoC prefill TTFT. Not full model TTFT."}, indent=2) + "\n")
    print("Model: FP16 1024 -> 512 -> 1024; 1-token PIM GEMV linear part only")
    print(f"Total PUs: {pus} ({args.channels} channels x {args.ranks_per_channel} ranks x {args.banks_per_rank} banks)")
    for r in summary:
        print(f"Assumed chunk service {r['assumed_chunk_ns']:g} ns: "
              f"linear-only scenario = {r['linear_only_single_token_prefill_us']:.4f} us, "
              f"waves = {r['total_waves']}")
    print(f"Outputs: {args.out}")
    print("WARNING: These are hypothetical sensitivity scenarios, not PIM measurements")

if __name__ == "__main__":
    main()
