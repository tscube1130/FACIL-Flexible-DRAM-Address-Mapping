
from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
import os, re, csv, json, tempfile, subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = ROOT
binary = (SIMULATOR).resolve()
config = (CONFIG).resolve()

source = TRACES / "llama3_k_v_permutation"
out = RESULTS / "extension/facil_batch_exp5"

assert binary.is_file(), "STOP: Missing DRAMsim3 executable"
assert config.is_file(), "STOP: Missing validated timing config"
assert not out.exists(), "STOP: Preserve existing results"

sources = {
    "read": source / "copy_read.trace",
    "write": source / "copy_write.trace"
}
for p in sources.values():
    assert p.is_file(), f"STOP: Missing existing trace {p}"

match = re.search(
    r"^\s*tCK\s*=\s*([0-9.]+)",
    config.read_text(), re.M | re.I
)
assert match, "STOP: Cannot determine DRAM clock"
tck_ns = float(match.group(1))
assert abs(tck_ns - 0.3125) < 1e-6, \
    "STOP: Timing differs from validated configuration"

TRANSACTION_BYTES = 128
PEAK_GBS = 204.8

def read_unique_trace(path, expected_op):
    rows = []
    seen = set()
    previous_cycle = -1

    with path.open() as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            assert len(parts) == 3, \
                f"Unexpected trace format: {line[:120]}"
            addr = int(parts[0], 0)
            op = parts[1].upper()
            cycle = int(parts[2])

            assert op == expected_op, (path, op)
            assert cycle >= previous_cycle
            previous_cycle = cycle

            # Deduplicate physical 128-byte DRAM transactions.
            aligned = addr & ~(TRANSACTION_BYTES - 1)
            if aligned in seen:
                continue
            seen.add(aligned)
            rows.append((aligned, cycle))

    return rows

read_rows = read_unique_trace(sources["read"], "READ")
write_rows = read_unique_trace(sources["write"], "WRITE")

N = min(32768, len(read_rows), len(write_rows))
assert N >= 4096, "STOP: Too few distinct transactions"

print("Unique transaction sample:", N, "per stage", flush=True)

out.mkdir(parents=True)
trace_dir = out / "traces"
trace_dir.mkdir()

def create_pair(stage, rows):
    rows = rows[:N]
    cycles = [c - rows[0][1] for a, c in rows]
    original_addresses = [a for a, c in rows]
    sequential_addresses = sorted(original_addresses)

    assert sorted(original_addresses) == sequential_addresses

    created = {}
    for label, addresses in (
        ("original", original_addresses),
        ("sequential", sequential_addresses)
    ):
        path = trace_dir / f"{stage}_{label}.trace"
        op = stage.upper()
        with path.open("w") as f:
            for address, cycle in zip(addresses, cycles):
                f.write(f"0x{address:x} {op} {cycle}\n")
        created[label] = path

    return created

traces = {
    "read": create_pair("read", read_rows),
    "write": create_pair("write", write_rows)
}

env = os.environ.copy()
env.pop("FACIL_PAGE_MAP_FILE", None)
env.pop("FACIL_CHANNEL_XOR", None)

def simulate(trace, stage, cycles, destination):
    destination.mkdir(parents=True, exist_ok=True)

    command = [
        str(binary), str(config),
        "-c", str(cycles),
        "-t", str(trace),
        "-o", str(destination)
    ]
    result = subprocess.run(
        command, cwd=root, env=env,
        capture_output=True, text=True
    )

    assert result.returncode == 0, (
        "STOP: DRAMsim3 failed\n"
        + result.stderr[-1500:]
        + result.stdout[-1500:]
    )

    stats_path = destination / "dramsim3.json"
    assert stats_path.is_file(), \
        "STOP: Native DRAMsim3 statistics missing"

    stats = json.loads(stats_path.read_text())
    assert isinstance(stats, dict) and stats

    counter = (
        "num_reads_done" if stage == "read"
        else "num_write_cmds"
    )

    observed = sum(
        int(channel[counter])
        for channel in stats.values()
    )
    return observed, stats

def find_completion(stage, label, trace):
    # Binary-search the minimum simulated cycles at which
    # all selected reads complete or all write commands issue.
    # Write command issue is NOT write-data persistence.
    with tempfile.TemporaryDirectory(
        prefix="facil_exp5_"
    ) as temporary:
        temp = Path(temporary)
        trial_number = 0

        def probe(cycles):
            nonlocal trial_number
            trial_number += 1
            directory = temp / f"trial_{trial_number:03}"
            observed, _ = simulate(
                trace, stage, cycles, directory
            )
            assert observed <= N
            return observed

        high = max(4096, N * 2)

        while probe(high) < N:
            high *= 2
            assert high <= 4000000, \
                "STOP: Trace not completed within cycle limit"

        low = 0

        # Resolution: 256 DRAM cycles.
        while high - low > 256:
            middle = (low + high) // 2
            if probe(middle) >= N:
                high = middle
            else:
                low = middle

    final = out / f"native_{stage}_{label}"
    count, stats = simulate(trace, stage, high, final)

    assert count == N, (
        f"Incomplete transaction count: {stage}, {label}, "
        f"{count}/{N}"
    )

    return high, stats

results = []

for stage in ("read", "write"):
    for label in ("original", "sequential"):
        print(f"Running: {stage} / {label}", flush=True)

        cycles, stats = find_completion(
            stage, label, traces[stage][label]
        )

        duration_us = cycles * tck_ns / 1000
        traffic_bytes = N * TRANSACTION_BYTES
        bandwidth_gbs = traffic_bytes / (cycles * tck_ns)

        row = {
            "stage": stage,
            "access_order": label,
            "transactions": N,
            "bytes": traffic_bytes,
            "cycles_approx": cycles,
            "duration_us_approx": round(duration_us, 4),
            "bandwidth_GBs_approx": round(bandwidth_gbs, 4),
            "percent_external_peak": round(
                100 * bandwidth_gbs / PEAK_GBS, 2
            ),
            "completion_definition": (
                "reads completed" if stage == "read"
                else "write commands issued"
            )
        }

        results.append(row)
        print(row, flush=True)

with (out / "bandwidth_diagnostic.csv").open(
    "w", newline=""
) as f:
    writer = csv.DictWriter(
        f, fieldnames=list(results[0])
    )
    writer.writeheader()
    writer.writerows(results)

fig, ax = plt.subplots(figsize=(8, 5))
labels = ["Read", "Write"]
x = range(2)
width = 0.35

for offset, order in (
    (-width/2, "original"),
    (width/2, "sequential")
):
    values = [
        next(
            r["bandwidth_GBs_approx"] for r in results
            if r["stage"] == stage
            and r["access_order"] == order
        )
        for stage in ("read", "write")
    ]
    ax.bar(
        [i + offset for i in x],
        values, width, label=order
    )

ax.axhline(
    PEAK_GBS, linestyle="--",
    label="Theoretical external peak"
)
ax.set_xticks(list(x), labels)
ax.set_ylabel("Approximate effective bandwidth (GB/s)")
ax.set_title("K/V sampled DRAMsim3 traffic: access-order diagnostic")
ax.legend()
ax.grid(axis="y", alpha=0.25)

fig.text(
    0.5, 0.01,
    "Same address set and injection schedule; "
    "read completion vs write command issuance.",
    ha="center", fontsize=8
)
fig.tight_layout(rect=(0, 0.05, 1, 1))
fig.savefig(out / "bandwidth_diagnostic.png", dpi=220)
plt.close(fig)

(out / "assumptions.json").write_text(
    json.dumps({
        "purpose": "Diagnose access-order effect, not reproduce full copy",
        "original_sources": {
            k: str(v) for k, v in sources.items()
        },
        "transactions_per_stage": N,
        "transaction_bytes_assumed": TRANSACTION_BYTES,
        "physical_transaction_deduplication": True,
        "same_addresses_within_each_comparison": True,
        "same_request_arrival_times_within_each_comparison": True,
        "facil_mapping": "Disabled; conventional baseline",
        "sampling": "First N unique aligned transactions per stage",
        "timing_measurement":
            "Binary search, 256-cycle resolution",
        "read_completion": "All read callbacks observed",
        "write_completion":
            "All write commands issued, not necessarily drained",
        "limitation":
            "Sampled diagnostic does not directly replace the "
            "full-matrix 447.284 ms serialized re-layout estimate"
    }, indent=2
    ) + "\n"
)

print("\nEXPERIMENT 5: PASS")
print("Saved:", out)
