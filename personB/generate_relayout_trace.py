#!/usr/bin/env python3
"""Generate a reduced-scale DRAM traffic proxy for FACIL baseline re-layout.

Read PIM-resident FP16 weights, then write to a separate SoC-layout buffer.
The stages are separate to avoid pretending that writes can complete before reads.
This emits DRAM transactions only; it does not permute matrix elements or model
CPU/GPU conversion, and it is not a native LPDDR5 implementation.
"""
from argparse import ArgumentParser
from pathlib import Path
import json


def emit(path: Path, base: int, operation: str, count: int, burst: int) -> None:
    with path.open("w", encoding="utf-8") as file:
        for i in range(count):
            file.write(f"{base + i * burst:#x} {operation} {i}\n")


def main():
    parser = ArgumentParser()
    parser.add_argument("--rows", type=int, default=512)
    parser.add_argument("--cols", type=int, default=1024)
    parser.add_argument("--element-bytes", type=int, default=2)
    parser.add_argument("--transaction-bytes", type=int, default=128)
    parser.add_argument("--src-base", type=lambda s: int(s, 0), default=0)
    parser.add_argument("--dst-base", type=lambda s: int(s, 0), default=0x10000000)
    parser.add_argument("--output", type=Path, default=Path("personB/traces/relayout"))
    args = parser.parse_args()

    if min(args.rows, args.cols, args.element_bytes, args.transaction_bytes) <= 0:
        parser.error("Dimensions and byte sizes must be positive")
    size = args.rows * args.cols * args.element_bytes
    if size % args.transaction_bytes:
        parser.error("Matrix byte size must be a multiple of transaction size")
    if args.src_base % args.transaction_bytes or args.dst_base % args.transaction_bytes:
        parser.error("Base addresses must be transaction-aligned")
    src_range = (args.src_base, args.src_base + size)
    dst_range = (args.dst_base, args.dst_base + size)
    if max(src_range[0], dst_range[0]) < min(src_range[1], dst_range[1]):
        parser.error("PIM source and SoC scratch address ranges must not overlap")

    args.output.mkdir(parents=True, exist_ok=True)
    count = size // args.transaction_bytes
    read_file = args.output / "copy_read.trace"
    write_file = args.output / "copy_write.trace"
    emit(read_file, args.src_base, "READ", count, args.transaction_bytes)
    emit(write_file, args.dst_base, "WRITE", count, args.transaction_bytes)

    manifest = {
        "matrix_shape": [args.rows, args.cols],
        "element_bytes": args.element_bytes,
        "matrix_bytes": size,
        "transaction_bytes": args.transaction_bytes,
        "transactions_per_stage": count,
        "total_read_and_write_bytes": 2 * size,
        "source_address_range": [hex(src_range[0]), hex(src_range[1])],
        "destination_address_range": [hex(dst_range[0]), hex(dst_range[1])],
        "read_trace": str(read_file),
        "write_trace": str(write_file),
        "method": "two separate serialized DRAM-only traffic stages; no logical permutation or compute",
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Matrix: {args.rows} x {args.cols} FP{args.element_bytes*8}; {size:,} bytes")
    print(f"Each trace: {count:,} requests of {args.transaction_bytes} bytes")
    print(f"Total copy traffic: {2 * size:,} bytes (read + write)")
    print(f"Read trace: {read_file}")
    print(f"Write trace: {write_file}")
    print(f"Manifest: {args.output / 'manifest.json'}")


if __name__ == "__main__":
    main()
