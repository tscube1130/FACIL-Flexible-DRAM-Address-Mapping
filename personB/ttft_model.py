#!/usr/bin/env python3
"""FACIL single-linear-layer prefill timing scenario (not measured TTFT).

Re-layout time is read from a DRAMsim3-produced summary.json (actual measured
workload proxy). SoC GEMM is an analytical roofline estimate with documented
hardware peak inputs, not observed GPU inference time. Decode GEMV is excluded.
Outputs numeric CSV + provenance JSON + two separate graphs.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path


def compute_gemm_us(rows: int, cols: int, prompt: int, element_bytes: int,
                    bandwidth_gbs: float, peak_tflops: float, gpu_util: float,
                    count_activation_traffic: bool = True) -> dict:
    if min(rows, cols, prompt, element_bytes) <= 0 or bandwidth_gbs <= 0 or peak_tflops <= 0 or not (0 < gpu_util <= 1):
        raise ValueError("Invalid positive dimensions/speeds or GPU efficiency")
    weight_bytes = rows * cols * element_bytes
    activation_bytes = (rows + cols) * prompt * element_bytes if count_activation_traffic else 0
    # Minimum model traffic: weight read once, inputs once, outputs once.
    # Caches may eliminate some DRAM transfers, real kernels may transfer more.
    modeled_bytes = weight_bytes + activation_bytes
    flops = 2 * rows * cols * prompt
    mem_us = modeled_bytes / bandwidth_gbs / 1000  # B/(GB/s) -> ns -> us
    compute_us = flops / (peak_tflops * 1e6 * gpu_util)
    return {"gemm_us_analytical": max(mem_us, compute_us),
            "memory_component_us": mem_us,
            "compute_component_us": compute_us,
            "weights_bytes": weight_bytes,
            "minimum_modeled_memory_bytes": modeled_bytes,
            "flops": flops}


def evaluate(rows, cols, element_bytes, prompts, bandwidth_gbs, peak_tflops,
             gpu_util, facil_penalty, copy_us, count_activation_traffic):
    if copy_us < 0 or facil_penalty < 0:
        raise ValueError("Time and penalty must be nonnegative")
    records = []
    for p in prompts:
        g = compute_gemm_us(rows, cols, p, element_bytes,
                            bandwidth_gbs, peak_tflops, gpu_util,
                            count_activation_traffic)
        gemm = g["gemm_us_analytical"]
        # Model: paper hybrid-static baseline does one layout conversion for
        # this modeled weight layer; FACIL accesses same weight copy directly.
        baseline = gemm + copy_us
        facil = gemm * (1.0 + facil_penalty)
        records.append({"prefill_tokens": p, "gemm_model_us": gemm,
                        "gemm_memory_us": g["memory_component_us"],
                        "gemm_compute_us": g["compute_component_us"],
                        "modeled_bytes": g["minimum_modeled_memory_bytes"],
                        "weight_bytes": g["weights_bytes"],
                        "copy_proxy_us_upper_bound": copy_us,
                        "baseline_us_scenario": baseline,
                        "facil_us_scenario": facil,
                        "speedup_scenario": baseline / facil})
    return records


def main():
    a = argparse.ArgumentParser(description="Generate transparent single-layer FACIL TTFT-component scenario")
    a.add_argument("--summary", type=Path, default=Path("personB/results/relayout_v1/summary.json"))
    a.add_argument("--rows", type=int, default=512)
    a.add_argument("--cols", type=int, default=1024)
    a.add_argument("--element-bytes", type=int, default=2)
    a.add_argument("--prompts", nargs="+", type=int, default=[8, 16, 32, 64, 128, 256, 512])
    a.add_argument("--bandwidth-gbs", type=float, default=204.8,
                   help="Analytical SoC DRAM bandwidth assumption, paper Jetson theoretical peak")
    a.add_argument("--peak-tflops", type=float, default=42.5,
                   help="Analytical SoC GPU FP16 peak, paper Jetson Table II")
    a.add_argument("--gpu-util", type=float, default=1.0,
                   help="Fraction of peak GPU FLOPS assumed; 1.0 is idealistic")
    a.add_argument("--facil-penalty", type=float, default=0.0,
                   help="Optional GEMM mapping penalty fraction; e.g., 0.021 paper Jetson upper ref, not measured here")
    a.add_argument("--exclude-activations", action="store_true",
                   help="Model weight-traffic only; default counts each input/output once")
    a.add_argument("--output", type=Path, default=Path("personB/results/ttft_model_512x1024"))
    args = a.parse_args()
    if any(p <= 0 for p in args.prompts):
        a.error("Prefill tokens must be positive")
    if not args.summary.exists():
        a.error(f"Missing actual DRAMsim3 copy summary: {args.summary}")
    sim = json.loads(args.summary.read_text())
    expected_bytes = args.rows * args.cols * args.element_bytes
    recorded_bytes = int(sim["matrix_bytes"])
    if expected_bytes != recorded_bytes:
        a.error(f"Shape/data mismatch: shape is {expected_bytes} bytes, simulation {recorded_bytes}. Use matching --rows/--cols.")
    if "serialized_copy" not in sim or "estimated_time_us_upper_bound" not in sim["serialized_copy"]:
        a.error("Missing serialized_copy measured proxy from DRAMsim3 summary")
    for stage in ("read", "write"):
        if int(sim[stage]["completed_transactions"]) <= 0:
            a.error(f"{stage} appears to have zero completed transactions")
    copy_us = float(sim["serialized_copy"]["estimated_time_us_upper_bound"])
    records = evaluate(args.rows, args.cols, args.element_bytes, args.prompts,
                       args.bandwidth_gbs, args.peak_tflops, args.gpu_util,
                       args.facil_penalty, copy_us, not args.exclude_activations)
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "ttft_scenario.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    prov = {
        "classification": "analytical single-layer prefill timing scenario, NOT measured end-to-end TTFT",
        "paper_reference": "FACIL HPCA 2025, Fig. 6, Fig. 13, Table II and Table III",
        "measured_input": {"dramsim3_summary": str(args.summary),
                           "matrix_bytes": recorded_bytes,
                           "serialized_copy_us_upper_bound": copy_us,
                           "config": sim.get("config"),
                           "measurement_limitation": sim.get("note", "")},
        "model_inputs": {"matrix_shape": [args.rows, args.cols],
                         "element_bytes": args.element_bytes,
                         "prefill_tokens": args.prompts,
                         "gpu_peak_TFLOPS_FP16": args.peak_tflops,
                         "gpu_compute_fraction_of_peak": args.gpu_util,
                         "theoretical_memory_GB_s": args.bandwidth_gbs,
                         "activation_output_traffic_once": not args.exclude_activations,
                         "facil_gemm_layout_penalty_fraction": args.facil_penalty},
        "equations": ["gemm_analytical=max((W_bytes + P*(M+K)*dtype)/BW, 2*M*K*P/(FLOPS*gpu_util))",
                      "baseline_component=gemm_analytical+measured_copy_proxy",
                      "facil_component=gemm_analytical*(1+mapping_penalty)",
                      "decode PIM GEMV NOT included in TTFT"],
        "warnings": [
            "DRAMsim3 re-layout proxy is serialized read plus write; no physical permutation/CPU reorder/overlap/caches.",
            "GPU compute time here is a roofline assumption rather than a measured kernel.",
            "Reported scenario speedups are NOT empirical FACIL speedups or rigorous bounds.",
            "DRAM model is LPDDR4-protocol proxy with LPDDR5-style timings, not native LPDDR5.",
            "This is a single modeled linear layer; other LLM operations are excluded."
        ]
    }
    (args.output / "assumptions_and_provenance.json").write_text(json.dumps(prov, indent=2) + "\n")

    # Import Matplotlib only for visualization: CSV/JSON remain usable without it.
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("Matplotlib missing; saved CSV and provenance JSON only")
        return
    plotcfg = [("prefill_times_analytical.png", "Single-layer prefill component — modeled, NOT measured TTFT",
                ["baseline_us_scenario", "facil_us_scenario"], ["Baseline: GEMM + copy proxy", "FACIL: GEMM without copy"], "Modeled prefill time (µs)"),
               ("speedup_analytical.png", "Modeled FACIL component speedup — not measured",
                ["speedup_scenario"], ["Analytical scenario"], "Modeled speedup (×)")]
    for filename, title, keys, labels, ylabel in plotcfg:
        fig, ax = plt.subplots(figsize=(8.6, 5.3))
        for key, label in zip(keys, labels):
            ax.plot(args.prompts, [r[key] for r in records], marker="o", lw=2, label=label)
        ax.set_xlabel("Prefill length (tokens)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_xscale("log", base=2)
        ax.set_xticks(args.prompts)
        ax.set_xticklabels([str(v) for v in args.prompts])
        ax.grid(alpha=0.25)
        if len(keys) > 1:
            ax.legend()
        fig.text(0.5, 0.02,
                 "Copy from DRAMsim3; GEMM roofline assumed | LPDDR4 protocol / LPDDR5 timing proxy\n"
                 "Single FP16 layer only; no decode PIM GEMV, no measured end-to-end TTFT",
                 ha="center", fontsize=8)
        fig.subplots_adjust(bottom=0.24, top=0.88)
        fig.savefig(args.output / filename, dpi=220, bbox_inches="tight")
        plt.close(fig)
    print(f"Read DRAMsim3 copy proxy: {copy_us:.3f} us ({recorded_bytes / 2**20:.2f} MiB)")
    for r in records:
        print(f"P={r['prefill_tokens']:>4}: GEMM_model={r['gemm_model_us']:.3f} us, "
              f"baseline={r['baseline_us_scenario']:.3f} us, "
              f"FACIL={r['facil_us_scenario']:.3f} us, "
              f"scenario_speedup={r['speedup_scenario']:.3f}x")
    print(f"Saved CSV, provenance JSON and PNGs in {args.output}")

if __name__ == "__main__":
    main()
