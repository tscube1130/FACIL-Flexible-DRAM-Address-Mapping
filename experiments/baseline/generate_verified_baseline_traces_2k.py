#!/usr/bin/env python3
"""Step 4: verified *baseline re-layout* traces for the 2-KiB bank-row setup.

Keep mapping/facil_mapper.py and DRAMsim3 unchanged. Each logical 128-byte
weight block is read once from its PIM-oriented DRAM location, then written
once to its conventional contiguous destination. Source and destination use
DRAMsim3's FIXED address decoder; the MapID placement is encoded OFFLINE.

This validates addresses and complete coverage; it does NOT simulate moving
actual data, CPU rearrangement, SoC GEMM, PIM GEMV, or native MapID hardware.
Use with the updated LPDDR4-protocol/LPDDR5-style config (262144 rows, 256
columns per device). Do not mix timings with the old 8-KiB-row runs.
"""
from __future__ import annotations

from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG


import argparse
import configparser
import hashlib
import json
import sys
from pathlib import Path

ROOT = ROOT
sys.path.insert(0, str(ROOT / "mapping"))
from facil_mapper import Geometry, AiMMapper, choose_mapid  # noqa: E402


def pow2_bits(x: int) -> int:
    if x < 1 or (x & (x - 1)):
        raise ValueError(f"Non-power-of-two DRAM field: {x}")
    return x.bit_length() - 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    config_path = CONFIG
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    if not cp.read(config_path):
        ap.error(f"Configuration missing: {config_path}")
    d, s = cp["dram_structure"], cp["system"]
    prot = d["protocol"].strip()
    rows = int(d["rows"])
    columns = int(d["columns"])
    channels = int(s["channels"])
    bg = int(d["bankgroups"])
    bpg = int(d["banks_per_group"])
    bus = int(s["bus_width"])
    device = int(d["device_width"])
    burst = int(d["BL"])
    chan_capacity = int(s["channel_size"]) * 1024 * 1024
    bytes_per_rank = rows * columns * device // 8 * bg * bpg * (bus // device)
    if chan_capacity % bytes_per_rank:
        ap.error("Configured channel capacity is not a whole number of ranks")
    ranks = chan_capacity // bytes_per_rank
    request_bytes = bus * burst // 8
    aggregate_row_bytes = columns * bus // 8

    expected = ("LPDDR4", 4, 2, 16, 128, 2048, 262144, 256, 16)
    actual = (prot, channels, ranks, bg * bpg, request_bytes,
              aggregate_row_bytes, rows, columns, burst)
    if actual != expected:
        ap.error(f"STOP: config changed; expected {expected}, found {actual}")
    if float(cp["timing"]["tCK"]) != 0.3125:
        ap.error("STOP: unexpected timing tCK")
    geometry = Geometry(channels=channels, ranks=ranks, banks_per_rank=bg * bpg)
    geometry.validate()
    if geometry.dram_row_bytes != aggregate_row_bytes:
        ap.error("STOP: FACIL 2KiB chunk and simulator row size disagree")
    if args.rows <= 0 or args.cols < geometry.chunk_columns or args.cols % geometry.chunk_columns:
        ap.error("Positive rows and columns divisible by 1024 are required")

    # Verified against src/configuration.cc: SetAddressMapping() iterates
    # mapping tokens right-to-left for the least-significant field; an entire
    # DRAMsim3 request occupies the lowest log2(request_bytes) address bits.
    mapping = s["address_mapping"].strip()
    order = [mapping[i:i + 2] for i in range(0, len(mapping), 2)]
    widths = {"ro": pow2_bits(rows), "ra": pow2_bits(ranks),
              "bg": pow2_bits(bg), "ba": pow2_bits(bpg),
              "co": pow2_bits(columns // burst), "ch": pow2_bits(channels)}
    if mapping != "rorabgbacoch" or len(order) != 6 or set(order) != set(widths):
        ap.error("STOP: decoder arrangement changed; revalidate C++ fields first")
    request_bits = pow2_bits(request_bytes)

    def encode(fields: dict[str, int]) -> int:
        word = 0
        for name in order:
            number = fields[name]
            if not 0 <= number < (1 << widths[name]):
                raise AssertionError(f"Out-of-range DRAM {name}={number}")
            word = (word << widths[name]) | number
        return word << request_bits

    def decode(encoded: int) -> dict[str, int]:
        word = encoded >> request_bits
        fields = {}
        for name in reversed(order):
            fields[name] = word & ((1 << widths[name]) - 1)
            word >>= widths[name]
        if word:
            raise AssertionError("Decoded address exceeds DRAM capacity")
        return fields

    mapid, partition, _ = choose_mapid(args.cols, geometry)
    pim = AiMMapper(geometry, mapid)
    matrix_bytes = args.rows * args.cols * geometry.element_bytes
    if matrix_bytes % request_bytes or matrix_bytes % geometry.page_bytes:
        ap.error("Matrix must contain complete 128-byte blocks and 2MiB huge pages")
    count = matrix_bytes // request_bytes
    src_base = 0
    dst_base = 0x10000000  # conventional row-major destination, 256MiB offset
    if not (dst_base >= matrix_bytes and dst_base + matrix_bytes <= channels * chan_capacity):
        ap.error("Source/destination overlap or go beyond configured memory")
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT.resolve()):
        ap.error("Output must be inside repository")
    if any((out / f).exists() for f in ("copy_read.trace", "copy_write.trace", "manifest.json")):
        ap.error("Output files already exist: choose a new directory (no overwrites)")
    out.mkdir(parents=True, exist_ok=True)

    seen = bytearray(count)
    channels_seen = [0] * channels
    mapping_digest = hashlib.sha256()
    trace_read = out / "copy_read.trace"
    trace_write = out / "copy_write.trace"
    try:
        with trace_read.open("w") as fr, trace_write.open("w") as fw:
            for block in range(count):
                logical = block * request_bytes
                address = None
                parent = None
                # Four adjacent 32B transfers must decode to the same PIM
                # bank/row, with four consecutive 32B column locations.
                for fidx in range(request_bytes // geometry.dram_transfer_bytes):
                    offset = fidx * geometry.dram_transfer_bytes
                    loc = pim.decode(logical + offset)
                    if loc.byte_offset != 0:
                        raise AssertionError("Unaligned 32B PIM transfer")
                    key = (loc.channel, loc.rank, loc.bank, loc.row)
                    if parent is None:
                        parent = key
                        if loc.column % 4:
                            raise AssertionError("First fragment must start at 128B boundary")
                    if key != parent or loc.column % 4 != fidx:
                        raise AssertionError("128B request crosses PIM bank/row or column group")
                    fields = {"ch": loc.channel, "ra": loc.rank,
                              "bg": loc.bank // bpg, "ba": loc.bank % bpg,
                              "ro": loc.row, "co": loc.column // 4}
                    current = encode(fields) + (loc.column % 4) * geometry.dram_transfer_bytes
                    if decode(current) != fields:
                        raise AssertionError("DRAMsim3 decoder round-trip failed")
                    if address is None:
                        address = current
                    if current != address + offset:
                        raise AssertionError("Four PIM fragments are not one contiguous 128B request")
                assert address is not None
                if address % request_bytes or not src_base <= address < src_base + matrix_bytes:
                    raise AssertionError("PIM source is outside matrix physical footprint")
                physical_block = (address - src_base) // request_bytes
                if seen[physical_block]:
                    raise AssertionError("Mapped source address collision")
                seen[physical_block] = 1
                channels_seen[decode(address)["ch"]] += 1
                dest = dst_base + logical
                if dest % request_bytes or not dst_base <= dest < dst_base + matrix_bytes:
                    raise AssertionError("Conventional destination is not aligned/in range")
                # One trace for source reads; one for destination writes.
                # Same block number denotes which *logical* bytes are copied.
                # Timestamps are earliest offered cycles, not necessarily accepted cycles.
                fr.write(f"{address:#x} READ {block}\n")
                fw.write(f"{dest:#x} WRITE {block}\n")
                mapping_digest.update(logical.to_bytes(8, "little") + address.to_bytes(8, "little"))
        if sum(seen) != count:
            raise AssertionError("Source coverage incomplete")
        if channels_seen != [count // channels] * channels:
            raise AssertionError(f"Channel imbalance: {channels_seen}")
    except BaseException:
        trace_read.unlink(missing_ok=True)
        trace_write.unlink(missing_ok=True)
        raise

    result = {
        "status": "PASS", "matrix_shape": [args.rows, args.cols],
        "precision": "FP16", "matrix_bytes": matrix_bytes,
        "mapid": mapid, "partition_required": partition,
        "dram_row_bytes": aggregate_row_bytes, "reference_chunk_bytes": geometry.chunk_bytes,
        "requests_per_stage": count, "transactions_per_stage": count,
        "total_32B_fragments_checked": count * (request_bytes // geometry.dram_transfer_bytes),
        "transaction_bytes": request_bytes,
        "total_read_write_bytes": 2 * matrix_bytes,
        "channel_read_requests": channels_seen,
        "source_base": hex(src_base), "destination_base": hex(dst_base),
        "request_mapping_sha256": mapping_digest.hexdigest(),
        "read_trace": str(trace_read.relative_to(ROOT)),
        "write_trace": str(trace_write.relative_to(ROOT)),
        "config_path": str(config_path.relative_to(ROOT)),
        "config_sha256": sha256(config_path),
        "facil_mapper_sha256": sha256(ROOT / "mapping/facil_mapper.py"),
        "read_trace_sha256": sha256(trace_read),
        "write_trace_sha256": sha256(trace_write),
        "limitations": (
            "Uses static trace encoding into stock DRAMsim3 fixed decoder, not native "
            "MapID hardware. Read and write stages are separate; CPU byte movement, "
            "GPU GEMM and PIM GEMV not executed. LPDDR4 protocol with LPDDR5-like "
            "timings and an explicitly configured synthetic 2KiB bank row."
        ),
    }
    (out / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS: {args.rows}x{args.cols} FP16, MapID={mapid}, "
          f"{count:,} unique 128B PIM reads and {count:,} conventional writes")
    print(f"32B fragments verified: {count*4:,}; reads/channel={channels_seen}")
    print(f"2KiB DRAM row verified; config SHA256: {result['config_sha256'][:16]}...")
    print(f"Generated: {out.relative_to(ROOT)}")
    print("LIMIT: traffic traces only; DRAM timing and actual PIM/GEMM not yet measured")

if __name__ == "__main__":
    main()
