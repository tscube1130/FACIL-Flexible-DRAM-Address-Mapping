
from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
import csv, json, hashlib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

root = ROOT
res = RESULTS
cfg = CONFIG
assert cfg.is_file()
cfg_hash = hashlib.sha256(cfg.read_bytes()).hexdigest()

def load(path):
    assert path.is_file(), f"Missing: {path}"
    return json.loads(path.read_text())

def time_ms(record):
    cycles = int(record["cycles_upper_bound"])
    ms = cycles * 0.3125 / 1000000
    reported = record.get(
        "time_us_upper_bound",
        record.get("elapsed_us_upper_bound")
    )
    assert reported is not None
    assert abs(ms * 1000 - float(reported)) < 0.003
    return ms

shapes = {
    "Q/O": (
        "q_o", 2, 262144, "comparison.json",
        "baseline_conventional_read", "facil_mapped_read"
    ),
    "K/V": (
        "k_v", 2, 65536, "matched_read_timing.json",
        "baseline", "facil"
    ),
    "FFN gate/up": (
        "ffn_gate_up", 2, 917504, "comparison.json",
        "baseline_conventional_read", "facil_native_read"
    ),
    "FFN down": (
        "ffn_down", 1, 917504, "comparison.json",
        "baseline_conventional_read", "facil_native_read"
    ),
}

copy_ms = 0
penalty_ms = 0
details = {}

for label, (name, copies, n, filename, bk, fk) in shapes.items():
    old = load(res / f"baseline/verified_baseline_{name}_2k/summary.json")
    new = load(res / f"facil/facil_step3_{name}_2k/{filename}")

    assert old["read"]["completed_transactions"] == n
    assert old["write"]["completed_transactions"] == n
    assert new.get("transactions", n) == n
    assert new.get("config_sha256", cfg_hash) == cfg_hash

    relayout = time_ms(old["read"]) + time_ms(old["write"])
    conventional = time_ms(new[bk])
    facil = time_ms(new[fk])

    copy_ms += 32 * copies * relayout
    penalty_ms += 32 * copies * (facil - conventional)

    details[label] = {
        "relayout": relayout * 1000,
        "conventional": conventional * 1000,
        "facil": facil * 1000,
    }

assert abs(copy_ms - 447.283520) < 0.002

with (res / "analytical/llama3_soc_gemm_analytical/soc_gemm_roofline.csv").open() as f:
    gemm_data = list(csv.DictReader(f))

baseline_file = res / "baseline_ttft_reduced_scope/baseline_ttft_proxy.csv"
original_baseline = {}
if baseline_file.is_file():
    with baseline_file.open() as f:
        original_baseline = {
            int(r["prefill_tokens"]):
            float(r["reduced_scope_baseline_ttft_proxy_ms"])
            for r in csv.DictReader(f)
        }
else:
    print("INFO: Reconstructing baseline from GEMM and re-layout records")

results = []

for r in gemm_data:
    p = int(r["prefill_tokens"])
    assert int(r["linear_gemm_count"]) == 224

    gemm = float(r["sum_per_gemm_ideal_roofline_ms"])
    baseline = gemm + copy_ms
    ideal = gemm
    adjusted = gemm + penalty_ms

    if p in original_baseline:
        assert abs(baseline - original_baseline[p]) < 0.003

    results.append({
        "prefill_tokens": p,
        "baseline_ms": baseline,
        "facil_ideal_ms": ideal,
        "facil_sensitivity_ms": adjusted,
        "ideal_speedup_x": baseline / ideal,
        "sensitivity_speedup_x": baseline / adjusted,
    })

results.sort(key=lambda r: r["prefill_tokens"])
assert [r["prefill_tokens"] for r in results] == [8,16,32,64,128]

# Verify Step 5 if its CSV is already saved.
step5 = res / "facil_step5_ttft_scope/facil_ttft_scenarios.csv"

if step5.is_file():
    with step5.open() as f:
        saved = {
            int(r["prefill_tokens"]): r
            for r in csv.DictReader(f)
        }

    columns = {
        "baseline_ms": [
            "baseline_ttft_proxy_ms", "baseline_ttft_scope_ms"
        ],
        "facil_ideal_ms": [
            "facil_ideal_ttft_proxy_ms",
            "facil_ideal_no_mapping_penalty_ms"
        ],
        "facil_sensitivity_ms": [
            "facil_adjusted_ttft_proxy_ms",
            "facil_penalty_adjusted_ttft_scope_ms"
        ],
    }

    for r in results:
        old = saved[r["prefill_tokens"]]
        for key, alternatives in columns.items():
            col = next((x for x in alternatives if x in old), None)
            assert col is not None
            assert abs(r[key] - float(old[col])) < 0.003

    print("PASS: Step 5 results independently verified")
else:
    print("PASS: Step 5 values reconstructed from validated measurements")

out = res / "facil/facil_step6_comparison"
assert not (out / "ttft_comparison.png").exists(), \
    "STOP: Existing Step 6 plots preserved"
out.mkdir(parents=True, exist_ok=True)

with (out / "ttft_comparison.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(results[0]))
    writer.writeheader()
    writer.writerows(results)

x = np.arange(len(results))
tokens = [r["prefill_tokens"] for r in results]

# Figure 1: TTFT comparison
fig, ax = plt.subplots(figsize=(9, 5.2))

series = [
    ("baseline_ms", "Baseline: GEMM + re-layout"),
    ("facil_ideal_ms", "FACIL ideal: GEMM only"),
    ("facil_sensitivity_ms", "FACIL: mapping sensitivity"),
]

for i, (key, label) in enumerate(series):
    bars = ax.bar(
        x + (i-1)*0.25,
        [r[key] for r in results],
        width=0.25,
        label=label
    )
    ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=7, rotation=90)

ax.set_ylim(0, max(r["baseline_ms"] for r in results) * 1.18)
ax.set_xticks(x, tokens)
ax.set_xlabel("Prefill tokens")
ax.set_ylabel("Reduced-scope latency (ms)")
ax.set_title("Llama3-8B: analytical TTFT proxy")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.25)
fig.tight_layout()
fig.savefig(out / "ttft_comparison.png", dpi=220)
plt.close(fig)

# Figure 2: Speedup versus original FACIL paper
fig, ax = plt.subplots(figsize=(9, 5.2))

ax.plot(
    tokens,
    [r["ideal_speedup_x"] for r in results],
    marker="o", label="Our ideal FACIL scenario"
)

ax.plot(
    tokens,
    [r["sensitivity_speedup_x"] for r in results],
    marker="s", label="Our sequential-read sensitivity"
)

ax.axhline(
    2.89, linestyle="--", alpha=0.65,
    label="Paper Fig. 13: Jetson geomean 2.89x (not directly comparable)"
)

ax.set_xticks(tokens)
ax.set_ylim(bottom=1)
ax.set_xlabel("Prefill tokens")
ax.set_ylabel("Baseline / FACIL speedup")
ax.set_title("Reduced-scope speedup vs paper context")
ax.legend(fontsize=8)
ax.grid(alpha=0.25)
fig.tight_layout()
fig.savefig(out / "ttft_speedups.png", dpi=220)
plt.close(fig)

# Figure 3: Actual DRAMsim3 memory-access comparisons
fig, ax = plt.subplots(figsize=(9.5, 5.2))
names = list(details)
xx = np.arange(len(names))

for i, (key, label) in enumerate([
    ("relayout", "Baseline re-layout"),
    ("conventional", "Conventional read"),
    ("facil", "FACIL mapped read"),
]):
    bars = ax.bar(
        xx + (i-1)*0.25,
        [details[n][key] for n in names],
        width=0.25,
        label=label
    )
    ax.bar_label(bars, fmt="%.1f", padding=2, fontsize=7, rotation=90)

ax.set_ylim(0, max(d["facil"] for d in details.values()) * 1.18)
ax.set_xticks(xx, names)
ax.set_ylabel("DRAMsim3 completion upper bound (us)")
ax.set_title("Memory traffic cost per matrix")
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.25)
fig.tight_layout()
fig.savefig(out / "read_vs_relayout.png", dpi=220)
plt.close(fig)

notes = f"""# Step 6: FACIL comparison

Baseline re-layout: {copy_ms:.6f} ms across 32 blocks.
FACIL mapping sensitivity: {penalty_ms:.6f} ms across 32 blocks.

Original paper: Seo et al., HPCA 2025.
https://99dhl.github.io/assets/pdf/hpca25_facil.pdf

Paper Fig. 13: Jetson geometric-mean TTFT speedup = 2.89x.
Paper Table III: Worst-case measured Jetson GEMM slowdown
on PIM layout = 2.1%.
Paper Fig. 15: 2.37x and 2.63x TTFT speedups on real datasets.

Differences and limitations:
- Our results are analytical reduced-scope TTFT proxies.
- Our GEMM values use ideal peak roofline, not measured GPU kernels.
- Our DRAMsim3 uses LPDDR4 protocol with LPDDR5-style timing.
- Our baseline uses serialized DRAMsim3 re-layout estimates.
- The mapping sensitivity extrapolates sequential DRAM reads to
  GEMM and is NOT measured GEMM slowdown.
- The published 2.1% GEMM slowdown cannot be compared directly
  with our raw sequential-read slowdown.
- Attention, normalization, output head, runtime overhead omitted.
- No PIM GEMV or TTLT included yet.
- Different methodology prevents exact numerical reproduction.
"""

(out / "comparison_notes.md").write_text(notes)

print("\nSTEP 6: PASS")
print(f"Baseline re-layout: {copy_ms:.3f} ms")
print(f"FACIL mapping sensitivity: {penalty_ms:.3f} ms")

for r in results:
    print(
        f"P{r['prefill_tokens']:>3}: "
        f"baseline={r['baseline_ms']:.3f}, "
        f"ideal={r['facil_ideal_ms']:.3f}, "
        f"adjusted={r['facil_sensitivity_ms']:.3f} ms, "
        f"adjusted speedup={r['sensitivity_speedup_x']:.3f}x"
    )

print("\nSaved all Step 6 outputs in:", out)
