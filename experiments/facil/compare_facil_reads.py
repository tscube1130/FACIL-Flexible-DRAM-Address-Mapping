#!/usr/bin/env python3
"""Matched baseline/FACIL DRAMsim3 read-traffic experiment.

Same logical FP16 weight reads and injection cycles.
Baseline: conventional configured DRAMsim3 address mapping.
FACIL: static trace encoding of standalone MapID placement.

A 2KiB reference PIM row occupies one quarter of an
8KiB simulated bank row. NOT a PIM execution simulator.
"""

from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

import argparse
import configparser
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = ROOT
sys.path.insert(0, str(ROOT / "mapping"))

from facil_mapper import Geometry, AiMMapper, choose_mapid

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def log2pow(n):
    assert n > 0 and n & (n - 1) == 0
    return n.bit_length() - 1

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, required=True)
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()

    cfgfile = ROOT / "configs/LPDDR5_6400_APPROX_8K_HISTORICAL.ini"
    exe = SIMULATOR

    cfg = configparser.ConfigParser(
        inline_comment_prefixes=("#", ";")
    )
    assert cfg.read(cfgfile)
    d, s = cfg["dram_structure"], cfg["system"]

    channels = int(s["channels"])
    bg = int(d["bankgroups"])
    bpg = int(d["banks_per_group"])
    bus = int(s["bus_width"])
    device = int(d["device_width"])
    burst = int(d["BL"])
    columns = int(d["columns"])
    dram_rows = int(d["rows"])
    mapping = s["address_mapping"]

    rank_mib = (
        dram_rows * columns * device // 8 *
        bg * bpg * (bus // device)
    ) // (1024 * 1024)
    ranks = int(s["channel_size"]) // rank_mib

    assert (
        channels, ranks, bg, bpg, bus, device,
        burst, columns, mapping
    ) == (4, 2, 4, 4, 64, 16, 16, 1024,
          "rorabgbacoch")

    transfer = bus * burst // 8
    bank_row_bytes = columns * bus // 8
    assert transfer == 128
    assert bank_row_bytes == 8192

    widths = {
        "ro": log2pow(dram_rows),
        "ra": log2pow(ranks),
        "bg": log2pow(bg),
        "ba": log2pow(bpg),
        "co": log2pow(columns // burst),
        "ch": log2pow(channels),
    }
    fields = [mapping[i:i+2] for i in range(0, 12, 2)]
    assert set(fields) == set(widths)
    shift = log2pow(transfer)

    # Mirror DRAMsim3 configuration.cc's bit-field encoding.
    def encode(values):
        word = 0
        for f in fields:
            assert 0 <= values[f] < (1 << widths[f])
            word = (word << widths[f]) | values[f]
        return word << shift

    def decode(address):
        word = address >> shift
        result = {}
        for f in reversed(fields):
            result[f] = word & ((1 << widths[f]) - 1)
            word >>= widths[f]
        assert word == 0
        return result

    geo = Geometry(
        channels=channels,
        ranks=ranks,
        banks_per_rank=bg*bpg
    )
    mapid, partition, _ = choose_mapid(a.cols, geo)
    mapper = AiMMapper(geo, mapid)

    out = RESULTS / (
        "facil/facil_matched_" + a.name
    )
    out.mkdir(parents=True, exist_ok=True)

    size = a.rows * a.cols * geo.element_bytes
    assert size % transfer == 0
    n = size // transfer

    baseline_trace = out / "baseline_read.trace"
    facil_trace = out / "facil_read.trace"
    seen = set()

    with baseline_trace.open("w") as b, \
         facil_trace.open("w") as f:

        for i in range(n):
            logical = i * transfer
            loc = mapper.decode(logical)

            assert loc.byte_offset == 0
            assert loc.column % 4 == 0

            # 32B reference columns -> 128B simulator column.
            # Four 2KiB reference PIM rows -> one 8KiB DRAM row.
            values = {
                "ch": loc.channel,
                "ra": loc.rank,
                "bg": loc.bank // bpg,
                "ba": loc.bank % bpg,
                "ro": loc.row // 4,
                "co": (loc.row % 4) * 16
                      + loc.column // 4
            }

            physical = encode(values)
            assert decode(physical) == values
            assert physical not in seen, "FACIL alias!"
            seen.add(physical)

            # Identical logical request sequence and arrival cycles.
            b.write(f"{logical:#x} READ {i}\n")
            f.write(f"{physical:#x} READ {i}\n")

    assert len(seen) == n
    print("Address translation validation: PASS")
    print("Matrix:", a.rows, "x", a.cols)
    print("MapID:", mapid, "partition:", partition)
    print("Verified unique 128B requests:", n)

    if not exe.is_file():
        raise SystemExit("Missing build/dramsim3main")

    tck = float(cfg["timing"]["tCK"])
    probe_dir = out / "_probe"
    probe_dir.mkdir(exist_ok=True)

    def run(trace, cycles):
        command = [
            str(exe), str(cfgfile),
            "-t", str(trace),
            "-c", str(cycles),
            "-o", str(probe_dir)
        ]
        p = subprocess.run(
            command, capture_output=True, text=True
        )
        if p.returncode:
            raise RuntimeError(p.stderr + p.stdout)

        stats = (probe_dir / "dramsim3.txt").read_text()
        counts = re.findall(
            r"(?m)^\s*num_reads_done\s*=\s*(\d+)",
            stats
        )
        if not counts:
            raise RuntimeError("Cannot parse DRAMsim3 read counts")

        return sum(map(int, counts))

    def measure(label, trace):
        lo = 0
        hi = max(n * 4, 65536)

        while run(trace, hi) < n:
            lo = hi
            hi *= 2
            if hi > 100000000:
                raise RuntimeError("Completion horizon exceeded")

        while hi - lo > 256:
            mid = (lo + hi) // 2
            if run(trace, mid) == n:
                hi = mid
            else:
                lo = mid

        assert run(trace, hi) == n
        shutil.copy2(
            probe_dir / "dramsim3.txt",
            out / f"{label}_dramsim3.txt"
        )

        us = hi * tck / 1000
        print(
            f"{label}: {n}/{n} completed, "
            f"cycles <= {hi}, time <= {us:.3f} us"
        )
        return {
            "cycles_upper_bound": hi,
            "completion_resolution_cycles": 256,
            "elapsed_us_upper_bound": us,
            "completed_transactions": n
        }

    baseline = measure("baseline", baseline_trace)
    facil = measure("facil", facil_trace)

    result = {
        "classification": (
            "Matched SoC weight-read timing proxy; "
            "NOT native MapID controller or PIM execution"
        ),
        "matrix": [a.rows, a.cols],
        "weight_bytes": size,
        "mapid": mapid,
        "partition": partition,
        "request_bytes": transfer,
        "simulated_bank_row_bytes": bank_row_bytes,
        "reference_chunk_bytes": geo.chunk_bytes,
        "protocol": d["protocol"],
        "config_sha256": sha(cfgfile),
        "simulator_sha256": sha(exe),
        "baseline_reads": baseline,
        "facil_reads": facil,
        "limitations": [
            "Static trace encoding, not MapID hardware",
            "Four 2KiB reference chunks share an 8KiB DRAM row",
            "Sequential logical weight scan, not measured GPU GEMM",
            "No PIM execution, caches, or re-layout permutation"
        ]
    }

    path = out / "summary.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print("Saved:", path)

if __name__ == "__main__":
    main()
