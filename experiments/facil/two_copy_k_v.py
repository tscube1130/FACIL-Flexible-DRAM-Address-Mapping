#!/usr/bin/env python3
"""Validate and time the native K/V two-copy comparison."""
import argparse
from collections import Counter
import configparser
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.paths import CONFIG, ROOT, SIMULATOR as SIM
from mapping.facil_mapper import AiMMapper, Geometry, choose_mapid

LIB = ROOT / "libdramsim3.so"
REFERENCE = ROOT / "results/facil/facil_step3_k_v_2k/matched_read_timing.json"
ROWS, COLS = 1024, 4096
TRANSFER = 128
SIZE = ROWS * COLS * 2
N = SIZE // TRANSFER
SOC = 0x10000000
MAPID = 2
GEO = Geometry(channels=4, ranks=2, banks_per_rank=16)
ENV = {key: value for key, value in os.environ.items()
       if key not in ("FACIL_PAGE_MAP_FILE", "FACIL_CHANNEL_XOR", "LD_LIBRARY_PATH")}
ENV["LD_LIBRARY_PATH"] = str(ROOT)


def save(out, name, data):
    (out / name).write_text(json.dumps(data, indent=2) + "\n")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def validate(out, pages):
    check(SIZE <= SOC and SOC % GEO.page_bytes == SIZE % GEO.page_bytes == 0,
          "Physical regions overlap or are unaligned")
    check(choose_mapid(COLS, GEO)[:2] == (MAPID, False), "Unexpected K/V MapID")
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / "verify_decoder"
        subprocess.run(["c++", "-std=c++11", "-I", str(ROOT / "src"),
                        "-I", str(ROOT / "ext/headers"),
                        str(ROOT / "tests/native/verify_two_copy_decoder.cc"),
                        str(LIB), "-o", str(exe)], check=True, env=ENV)
        fixture = "".join(f"{offset} {SOC + offset}\n"
                          for offset in range(0, SIZE, TRANSFER))
        lines = subprocess.run([str(exe), str(CONFIG), str(pages)],
                               input=fixture, capture_output=True, text=True,
                               env=ENV, check=True).stdout.splitlines()
    check(lines[0] == "FACIL MapID registry loaded: 4 pages" and len(lines) == N + 1,
          "Unexpected native verification output")
    mapper = AiMMapper(GEO, MAPID)
    seen = set()
    row_pus = set()
    expected_channels = Counter()
    with (out / "mixed.trace").open("w") as mixed:
        for i, line in enumerate(lines[1:]):
            values = tuple(map(int, line.split()))
            pim, soc, control = values[:6], values[6:12], values[12:]
            offset = i * TRANSFER
            loc = mapper.decode(offset)
            end = mapper.decode(offset + TRANSFER - 1)
            expected = (loc.channel, loc.rank, loc.bank // 4, loc.bank % 4,
                        loc.row, loc.column // 4)
            check(pim == expected and loc.column % 4 == loc.byte_offset == 0
                  and mapper.encode(loc) == offset
                  and mapper.encode(end) == offset + TRANSFER - 1
                  and (end.channel, end.rank, end.bank, end.row)
                  == (loc.channel, loc.rank, loc.bank, loc.row),
                  f"PIM placement mismatch at logical byte {offset}")
            check(soc == control, f"Conventional fallback mismatch at {offset}")
            check(pim != soc and pim not in seen and soc not in seen,
                  f"Native DRAM tuple alias at {offset}")
            seen.update((pim, soc))
            row_pus.add(pim[:4])
            if (offset + TRANSFER) % (COLS * 2) == 0:
                check(len(row_pus) == 1, f"Matrix row spans PUs at {offset}")
                row_pus.clear()
            # Sample four PIM channels and the interleaved SoC region.
            if i < 256:
                mixed.write(f"{offset:#x} READ {2*i}\n{SOC+offset:#x} READ {2*i+1}\n")
                expected_channels.update((pim[0], soc[0]))
    return [expected_channels[channel] for channel in range(4)]


def run_sim(trace, cycles, folder, pages):
    folder.mkdir(exist_ok=True)
    proc = subprocess.run([str(SIM), str(CONFIG), "-t", str(trace),
                           "-c", str(cycles), "-o", str(folder)],
                          env={**ENV, "FACIL_PAGE_MAP_FILE": str(pages)},
                          capture_output=True, text=True, check=True)
    check("FACIL MapID registry loaded: 4 pages" in proc.stdout + proc.stderr,
          "Simulator did not confirm loading the registry")
    stats = (folder / "dramsim3.txt").read_text()
    reads = list(map(int, re.findall(r"(?m)^\s*num_reads_done\s*=\s*(\d+)", stats)))
    writes = list(map(int, re.findall(r"(?m)^\s*num_writes_done\s*=\s*(\d+)", stats)))
    check(len(reads) == 4 and writes == [0] * 4, "Unexpected simulator counts")
    return reads


def measure(out, pages, label, base, copies, tck):
    trace = out / f"{label}.trace"
    with trace.open("w") as stream:
        for i in range(N):
            stream.write(f"{base + i * TRANSFER:#x} READ {i}\n")
    lo, hi = 0, 16 * N
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        check(sum(run_sim(trace, hi, scratch, pages)) == N,
              f"{label} did not finish within {hi} cycles")
        while hi - lo > 1:
            mid = (lo + hi) // 2
            count = sum(run_sim(trace, mid, scratch, pages))
            check(count <= N, "Extra completions")
            if count == N:
                hi = mid
            else:
                lo = mid
        counts = run_sim(trace, hi, out / label, pages)
        check(sum(counts) == N and sum(run_sim(trace, hi - 1, scratch, pages)) < N,
              "Completion boundary verification failed")
    us = hi * tck / 1000
    result = dict(case=label, transactions=N, bytes_requested=SIZE,
                  cycles=hi, latency_us=us, bandwidth_gb_s=SIZE / (us * 1000),
                  kv_storage_mib=copies * 8, model_storage_gib=copies * 13,
                  model_storage_gb=copies * 13 * 2**30 / 10**9,
                  pim_placement="verified")
    print(f"{label}: {N:,} reads, 0 writes, {hi:,} cycles, "
          f"{us:.6f} us, {result['bandwidth_gb_s']:.3f} GB/s; channels {counts}",
          flush=True)
    return result


def figure(out, rows):
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.5))
    fig.patch.set_facecolor("#f4f7fa")
    labels = ["FACIL", "Duplication"]
    for ax, key, title, unit in zip(
            axes, ("latency_us", "kv_storage_mib", "model_storage_gib"),
            ("SoC read latency · measured", "K/V storage · calculated",
             "224 matrices · calculated"), ("µs", "MiB", "GiB")):
        values = [row[key] for row in rows]
        bars = ax.barh(labels, values, color=["#15667a", "#a54e1c"], height=.5)
        ax.invert_yaxis()
        ax.set_xlim(0, max(values) * 1.34)
        texts = [f"{value:.2f} {unit}" if unit == "µs" else f"{value:g} {unit}"
                 for value in values]
        ax.bar_label(bars, labels=texts, padding=5, fontsize=11)
        ax.set_title(title, loc="left", fontsize=12, weight="bold")
        ax.set_facecolor("#f4f7fa")
        ax.tick_params(length=0, labelsize=11)
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.suptitle("FACIL shared weights vs. two-copy placement", x=.035, y=.96,
                 ha="left", fontsize=19, weight="bold")
    fig.text(.035, .79, "1024 × 4096 FP16 K/V · 65,536 matched 128-byte reads",
             fontsize=12)
    fig.text(.035, .095, "Native DRAMsim3 timing covers the SoC weight scan only. "
             "GPU GEMM, PIM arithmetic, and inference runtime were outside the experiment.",
             fontsize=10)
    fig.subplots_adjust(left=.11, right=.98, bottom=.20, top=.68, wspace=.58)
    fig.savefig(out / "comparison.png", dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for this run")
    out = parser.parse_args().output.resolve()
    out.mkdir(parents=True)
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    cfg.read(CONFIG)
    tck = cfg.getfloat("timing", "tCK")
    reference = json.loads(REFERENCE.read_text())
    check(sha(CONFIG) == reference["config_sha256"], "Reference configuration differs")
    pages = out / "pages.txt"
    pages.write_text("".join(f"{i} {MAPID}\n" for i in range(SIZE // GEO.page_bytes)))
    expected = validate(out, pages)
    actual = run_sim(out / "mixed.trace", 20000, out / "mixed", pages)
    check(actual == expected and all(actual), "Mixed-trace channel routing mismatch")
    save(out, "placement_validation.json", {
        "status": "PASS", "shape": [ROWS, COLS], "dtype": "FP16",
        "model": "Both addresses for logical byte offset i refer to the same matrix byte i.",
        "regions_end_exclusive": {"pim": [0, SIZE], "soc": [SOC, SOC + SIZE]},
        "page_bytes": GEO.page_bytes, "pim_mapid": MAPID,
        "soc_registered_pages": 0, "native_transactions_checked_per_copy": N,
        "unique_native_dram_tuples": 2 * N, "chunks_checked": SIZE // GEO.chunk_bytes,
        "pim_processing_units_per_matrix_row": 1,
        "mixed_expected_reads_per_channel": expected,
        "mixed_measured_reads_per_channel": actual,
    })
    print("TWO-COPY PLACEMENT: PASS", flush=True)
    rows = [measure(out, pages, "facil", 0, 1, tck),
            measure(out, pages, "duplication", SOC, 2, tck)]
    with (out / "duplication_vs_facil.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    facil, dup = rows
    save(out, "assumptions.json", {
        "measured": "Native DRAMsim3 read completions and simulated cycles.",
        "calculated": ["Effective scan bandwidth", "Latency ratios", "Weight storage"],
        "assumed": ["Preplaced copies", "Shared row-major FP16 logical offsets",
                    "Cold sequential scan, one eligible read per cycle",
                    "LPDDR4 protocol with LPDDR5-6400 approximate timing"],
        "unmeasured": ["Physical weight bytes", "GPU GEMM", "PIM arithmetic",
                       "Switching and re-layout timing", "Full decode or inference latency"],
        "model_matrices": 224, "request_bytes": TRANSFER, "tck_ns": tck,
        "dram_row_bytes": GEO.chunk_bytes, "config_sha256": sha(CONFIG),
        "simulator_sha256": sha(SIM), "native_library_sha256": sha(LIB),
        "mapper_sha256": sha(ROOT / "mapping/facil_mapper.py"),
        "completion": "First integer cycle budget with all read callbacks counted and no writes.",
        "reference": reference,
        "reference_minus_new_cycles": {
            "facil": reference["facil"]["cycles_upper_bound"] - facil["cycles"],
            "duplication": reference["baseline"]["cycles_upper_bound"] - dup["cycles"],
        },
        "duplication_latency_savings_us": facil["latency_us"] - dup["latency_us"],
        "duplication_latency_reduction_fraction": 1 - dup["cycles"] / facil["cycles"],
        "duplication_bandwidth_gain_fraction": dup["bandwidth_gb_s"] / facil["bandwidth_gb_s"] - 1,
        "duplication_scan_speedup": facil["cycles"] / dup["cycles"],
    })
    figure(out, rows)
    print("MATCHED READ COMPARISON: PASS", flush=True)


if __name__ == "__main__":
    main()
