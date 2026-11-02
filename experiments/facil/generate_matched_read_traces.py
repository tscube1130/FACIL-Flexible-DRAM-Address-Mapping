#!/usr/bin/env python3
"""Regenerate preserved matched-read inputs; no simulator or compute model."""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.paths import TRACES
SHAPES = {"q_o": (4096, 4096, 2), "k_v": (1024, 4096, 2),
          "ffn_gate_up": (14336, 4096, 2), "ffn_down": (4096, 14336, 3)}
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shape", choices=SHAPES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Existing output preserved; choose a new directory")
    rows, cols, mapid = SHAPES[args.shape]
    args.output.mkdir(parents=True)
    count = rows * cols * 2 // 128
    with (args.output / "facil_read.trace").open("w") as mapped, (args.output / "baseline_soc_read.trace").open("w") as baseline:
        for i in range(count):
            logical = i * 128
            mapped.write(f"{logical:#x} READ {i}\n")
            baseline.write(f"{0x10000000 + logical:#x} READ {i}\n")
    (args.output / "pages.txt").write_text("".join(f"{i} {mapid}\n" for i in range(rows * cols * 2 // (2 * 1024 * 1024))))
    print(f"Generated {count} requests per stream; no simulation run")
if __name__ == "__main__":
    main()
