from pathlib import Path as _Path
import sys as _sys
_sys.path.insert(0,str(_Path(__file__).resolve().parents[2]))
from experiments.paths import ROOT, RESULTS
from pathlib import Path
import csv, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

res = RESULTS
out = res / "analytical/facil_pim_gemv_analytical"
source = out / "pim_gemv_prefill_sensitivity.csv"
reference = res / "facil/facil_step6_comparison/ttft_comparison.csv"

assert source.is_file() and reference.is_file()

with source.open() as f:
    data = list(csv.DictReader(f))
with reference.open() as f:
    baseline = {
        int(x["prefill_tokens"]): x
        for x in csv.DictReader(f)
    }

assert len(data) == 15
tokens = [8, 16, 32, 64, 128]
assert set(baseline) == set(tokens)

for filename in (
    "pim_prefill_sensitivity.png",
    "pim_prefill_sensitivity.pdf",
    "pim_gemv_per_token.png"
):
    assert not (out / filename).exists(), \
        f"STOP: {filename} already exists"

fig, ax = plt.subplots(figsize=(10, 6))

ax.plot(
    tokens,
    [float(baseline[p]["baseline_ms"]) for p in tokens],
    "k--", marker="x",
    label="Baseline: SoC GEMM + re-layout"
)

ax.plot(
    tokens,
    [float(baseline[p]["facil_sensitivity_ms"]) for p in tokens],
    marker="s", linestyle="--",
    label="FACIL: SoC GEMM + mapping sensitivity"
)

for wave in (75, 100, 200):
    rows = sorted(
        (x for x in data if float(x["wave_ns"]) == wave),
        key=lambda x: int(x["prefill_tokens"])
    )

    assert [int(x["prefill_tokens"]) for x in rows] == tokens

    values = [
        float(x["facil_dynamic_penalty_sensitivity_ms"])
        for x in rows
    ]

    line, = ax.plot(
        tokens, values, marker="o",
        label=f"Dynamic SoC/PIM, assumed {wave} ns/wave"
    )

    ax.annotate(
        f"{values[0]:.1f} ms",
        (tokens[0], values[0]),
        xytext=(6, 6),
        textcoords="offset points",
        fontsize=8,
        color=line.get_color()
    )

ax.set_xticks(tokens)
ax.set_xlabel("Prefill length (tokens)")
ax.set_ylabel("Reduced-scope TTFT proxy (ms)")
ax.set_title("Llama3-8B: analytical PIM short-prefill sensitivity")
ax.grid(alpha=0.25)
ax.legend(fontsize=8)

fig.text(
    .5, .01,
    "PIM wave times are hypothetical; "
    "not measured PIM or end-to-end TTFT.",
    ha="center", fontsize=8
)

fig.tight_layout(rect=(0, .05, 1, 1))
fig.savefig(out / "pim_prefill_sensitivity.png", dpi=220)
fig.savefig(out / "pim_prefill_sensitivity.pdf")
plt.close(fig)

fig, ax = plt.subplots(figsize=(8, 5))

waves = [75, 100, 200]
times = []

for wave in waves:
    row = next(
        x for x in data
        if float(x["wave_ns"]) == wave
        and int(x["prefill_tokens"]) == 8
    )
    times.append(float(row["pim_one_token_gemv_ms"]))

ax.plot(waves, times, marker="o")

for x, y in zip(waves, times):
    ax.annotate(
        f"{y:.3f} ms", (x, y),
        xytext=(5, 7), textcoords="offset points"
    )

ax.set_xticks(waves)
ax.set_xlabel("Assumed PIM processing-wave latency (ns)")
ax.set_ylabel("All-layer GEMV latency per token (ms)")
ax.set_title("Analytical AiM GEMV timing sensitivity")
ax.grid(alpha=0.25)

fig.tight_layout()
fig.savefig(out / "pim_gemv_per_token.png", dpi=220)
plt.close(fig)

print("PIM FIGURES: PASS")
print("Saved figures to:", out)
