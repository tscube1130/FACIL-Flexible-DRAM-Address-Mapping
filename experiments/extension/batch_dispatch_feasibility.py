
from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
import csv, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

res = RESULTS

soc_file = res / "analytical/llama3_soc_gemm_analytical/soc_gemm_roofline.csv"
pim_file = res / "analytical/facil_pim_gemv_analytical/pim_gemv_model.json"
ttft_file = res / "facil/facil_step6_comparison/ttft_comparison.csv"

for p in (soc_file, pim_file, ttft_file):
    assert p.is_file(), f"Missing validated input: {p}"

with soc_file.open() as f:
    soc_ref = {
        int(r["prefill_tokens"]): r
        for r in csv.DictReader(f)
    }

pim_ref = json.loads(pim_file.read_text())["shape_data"]

with ttft_file.open() as f:
    ttft_ref = {
        int(r["prefill_tokens"]): r
        for r in csv.DictReader(f)
    }

# Shape: output rows, input columns, copies per layer, PIM waves.
shapes = {
    "q_o": (4096, 4096, 2, 128),
    "k_v": (1024, 4096, 2, 32),
    "ffn_gate_up": (14336, 4096, 2, 448),
    "ffn_down": (4096, 14336, 1, 448)
}

assert set(shapes) == set(pim_ref)
assert sum(32 * x[2] for x in shapes.values()) == 224

for name, (m, k, copies, waves) in shapes.items():
    saved = pim_ref[name]
    assert saved["m"] == m and saved["k"] == k
    assert saved["waves_per_gemv"] == waves

# Use the SAME analytical SoC model as our existing prefill study.
# Eta is a hypothetical effective-resource fraction, not measured GEMM efficiency.
def soc_ms(m, k, B, eta):
    flops = 2 * m * k * B
    bytes_ = 2 * m * k + 2 * B * (m + k)

    compute_s = flops / 42.5e12
    memory_s = bytes_ / 204.8e9

    return 1000 * max(compute_s, memory_s) / eta

def evaluate(B, eta, wave_ns):
    soc_total = 0
    pim_total = 0
    dynamic_total = 0
    soc_projections = 0

    for name, (m, k, copies, waves) in shapes.items():
        soc = soc_ms(m, k, B, eta)
        pim = B * waves * wave_ns / 1e6

        count = 32 * copies

        soc_total += count * soc
        pim_total += count * pim
        dynamic_total += count * min(soc, pim)

        if soc <= pim:
            soc_projections += count

    return soc_total, pim_total, dynamic_total, soc_projections

# First verify our model reproduces the previously validated results.
assert set(soc_ref) == set(ttft_ref) == {8, 16, 32, 64, 128}

for B, record in soc_ref.items():
    soc = evaluate(B, 1.0, 100)[0]

    assert abs(
        soc - float(record["sum_per_gemm_ideal_roofline_ms"])
    ) < 0.00001

    assert abs(
        float(ttft_ref[B]["baseline_ms"])
        - soc - 447.28352
    ) < 0.003

print("PASS: Existing SoC model and baseline verified")

etas = (0.30, 0.50, 0.763, 1.0)
wave_times = (75, 100, 200)
results = []
crossovers = []

# A conventional baseline copy is charged ONCE for 32 steps,
# never once per decode step.
steps = 32
relayout_ms = 447.28352

for wave in wave_times:
    for eta in etas:
        first_soc = None
        all_soc = None

        for B in range(1, 65):
            soc, pim, dynamic, chosen = evaluate(B, eta, wave)

            if chosen > 0 and first_soc is None:
                first_soc = B

            if chosen == 224 and all_soc is None:
                all_soc = B

            baseline_total = min(
                steps * pim,
                relayout_ms + steps * soc
            )

            results.append({
                "batch": B,
                "eta_assumed": eta,
                "wave_ns_assumed": wave,
                "always_pim_step_ms": round(pim, 6),
                "always_soc_step_ms": round(soc, 6),
                "facil_dispatch_step_ms": round(dynamic, 6),
                "soc_projections_of_224": chosen,
                "dispatch_vs_pim_x": round(pim / dynamic, 5),
                "baseline_32steps_ms": round(baseline_total, 6),
                "facil_dispatch_32steps_ms": round(
                    steps * dynamic, 6
                )
            })

        crossovers.append({
            "wave_ns_assumed": wave,
            "eta_assumed": eta,
            "first_batch_using_soc": first_soc,
            "first_batch_all_soc": all_soc
        })

out = res / "extension/facil_batch_decode_feasibility"

assert not (out / "batch_sweep.csv").exists(), \
    "STOP: Existing output preserved"

out.mkdir(parents=True, exist_ok=True)

for filename, data in (
    ("batch_sweep.csv", results),
    ("crossovers.csv", crossovers)
):
    with (out / filename).open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(data[0])
        )
        writer.writeheader()
        writer.writerows(data)

(out / "assumptions.json").write_text(json.dumps({
    "classification": "ANALYTICAL FEASIBILITY, NOT MEASURED DECODE",
    "batch_range": "1 to 64 tokens per decode step",
    "pim_model": "B * processing waves * assumed wave latency",
    "soc_model": "Existing ideal roofline divided by assumed eta",
    "eta": "Hypothetical effective SoC resource fraction",
    "dispatch": "Choose faster engine independently per projection",
    "baseline": "Always PIM, or one full re-layout followed by SoC",
    "baseline_example_steps": steps,
    "excluded": [
        "Attention and KV cache",
        "Actual batch memory pressure",
        "PIM command, broadcast and reduction overhead",
        "Engine switching and synchronization overhead",
        "Actual GPU kernel utilization"
    ]
}, indent=2) + "\n")

# Clearly labeled sensitivity graph.
selected = [
    r for r in results
    if r["eta_assumed"] == 0.5
    and r["wave_ns_assumed"] == 100
]

fig, ax = plt.subplots(figsize=(9, 5.5))

for key, label in (
    ("always_pim_step_ms", "Always PIM"),
    ("always_soc_step_ms", "Always SoC"),
    ("facil_dispatch_step_ms", "FACIL batch-aware dispatch")
):
    ax.plot(
        [r["batch"] for r in selected],
        [r[key] for r in selected],
        label=label
    )

ax.set_xlabel("Batch width B (tokens per decode step)")
ax.set_ylabel("Analytical linear-projection latency per step (ms)")
ax.set_title(
    "Decode dispatch sensitivity: 100 ns/wave, SoC eta = 0.50"
)
ax.legend()
ax.grid(alpha=0.25)

fig.text(
    0.5, 0.01,
    "Hypothetical PIM and SoC efficiency; "
    "not measured LLM decode latency.",
    ha="center", fontsize=8
)

fig.tight_layout(rect=(0, 0.055, 1, 1))
fig.savefig(out / "batch_dispatch_feasibility.png", dpi=220)
plt.close(fig)

print("\nCROSSOVER RESULTS")
print("Wave(ns)  Eta    First SoC batch   All SoC batch")

for r in crossovers:
    print(
        f"{r['wave_ns_assumed']:>7.0f}"
        f"  {r['eta_assumed']:>5.3f}"
        f"  {str(r['first_batch_using_soc']):>16}"
        f"  {str(r['first_batch_all_soc']):>14}"
    )

print("\nEXAMPLE: 100 ns PIM wave, eta = 0.50")

for r in selected:
    if r["batch"] in (1, 4, 8, 16, 32, 64):
        print(
            f"B={r['batch']:>2} | "
            f"PIM={r['always_pim_step_ms']:>7.2f} ms | "
            f"SoC={r['always_soc_step_ms']:>7.2f} ms | "
            f"Dispatch={r['facil_dispatch_step_ms']:>7.2f} ms | "
            f"SoC projections={r['soc_projections_of_224']}"
        )

print("\nBATCH FEASIBILITY: PASS")
print("Saved:", out)
