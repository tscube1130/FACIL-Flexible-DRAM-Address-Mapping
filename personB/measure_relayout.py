#!/usr/bin/env python3
"""Run separate DRAMsim3 copy stages and find completion cycles automatically.

Reports serialized memory-traffic cost, not the exact hardware re-layout time.
"""
from argparse import ArgumentParser
from configparser import ConfigParser
from pathlib import Path
import json
import re
import subprocess
import tempfile


def count_completed(stat_file: Path, label: str) -> int:
    content = stat_file.read_text(encoding="utf-8")
    counts = re.findall(rf"^\s*{re.escape(label)}\s*=\s*(\d+)", content, re.MULTILINE)
    if not counts:
        raise RuntimeError(f"Couldn't find {label} in {stat_file}")
    return sum(map(int, counts))


def main():
    ap = ArgumentParser()
    ap.add_argument("--sim", type=Path, default=Path("build/dramsim3main"))
    ap.add_argument("--config", type=Path, default=Path("configs/LPDDR5_6400_APPROX_v1.ini"))
    ap.add_argument("--trace-dir", type=Path, default=Path("personB/traces/relayout"))
    ap.add_argument("--results", type=Path, default=Path("personB/results/relayout_v1"))
    ap.add_argument("--resolution", type=int, default=256, help="Completion boundary tolerance, in cycles")
    args = ap.parse_args()

    cfg = ConfigParser()
    cfg.optionxform = str
    if not cfg.read(args.config):
        ap.error(f"Could not open config: {args.config}")
    tick_ns = float(cfg["timing"]["tCK"])
    manifest = json.loads((args.trace_dir / "manifest.json").read_text())
    expected = int(manifest["transactions_per_stage"])
    matrix_bytes = int(manifest["matrix_bytes"])
    args.results.mkdir(parents=True, exist_ok=True)

    stages = [("read", "copy_read.trace", "num_reads_done"),
              ("write", "copy_write.trace", "num_writes_done")]
    report = {"config": str(args.config), "tCK_ns": tick_ns,
              "matrix_bytes": matrix_bytes,
              "note": "Serialized DRAM-only copy proxy, LPDDR4 protocol with LPDDR5-style timings"}

    for stage, filename, stat_label in stages:
        trace = args.trace_dir / filename
        with tempfile.TemporaryDirectory(prefix=f"dramsim_{stage}_") as temp:
            probe_dir = Path(temp)

            def run(cycles: int, outdir: Path) -> int:
                outdir.mkdir(parents=True, exist_ok=True)
                command = [str(args.sim.resolve()), str(args.config.resolve()),
                           "-t", str(trace.resolve()), "-c", str(cycles),
                           "-o", str(outdir.resolve())]
                proc = subprocess.run(command, capture_output=True, text=True)
                if proc.returncode:
                    raise RuntimeError(f"DRAMsim3 failed with {proc.returncode}:\n{proc.stdout}\n{proc.stderr}")
                return count_completed(outdir / "dramsim3.txt", stat_label)

            lo, hi = 0, max(expected * 2, 2048)
            while run(hi, probe_dir) < expected:
                lo, hi = hi, 2 * hi
                if hi > 10_000_000:
                    raise RuntimeError(f"{stage}: exceeded 10 million cycles; check configuration or trace")
            while hi - lo > args.resolution:
                mid = (hi + lo) // 2
                if run(mid, probe_dir) >= expected:
                    hi = mid
                else:
                    lo = mid

            final = args.results / stage
            done = run(hi, final)
            if done != expected:
                raise RuntimeError(f"{stage}: expected {expected}, completed {done}")
            duration_ns = hi * tick_ns
            bw_gbs = matrix_bytes / duration_ns  # B/ns == GB/s
            report[stage] = {"cycles_upper_bound": hi,
                             "completion_resolution_cycles": args.resolution,
                             "completed_transactions": done,
                             "elapsed_us_upper_bound": duration_ns / 1000,
                             "effective_bandwidth_GB_s_lower_bound": bw_gbs,
                             "statistics": str(final / "dramsim3.txt")}
            print(f"{stage.upper():5} {done:,}/{expected:,} transactions | "
                  f"completion <= {hi:,} cycles | "
                  f"time <= {duration_ns / 1000:.3f} us | "
                  f"BW >= {bw_gbs:.2f} GB/s")

    total_time_ns = sum(report[stage]["cycles_upper_bound"] * tick_ns
                        for stage, _, _ in stages)
    report["serialized_copy"] = {
        "traffic_bytes": 2 * matrix_bytes,
        "estimated_time_us_upper_bound": total_time_ns / 1000,
        "note": "Serialized stages cannot model overlap, element rearrangement, CPU/GPU cost or cache effects",
    }
    (args.results / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"SERIALIZED COPY time <= {total_time_ns / 1000:.3f} us")
    print(f"Saved: {args.results / 'summary.json'}")


if __name__ == "__main__":
    main()
