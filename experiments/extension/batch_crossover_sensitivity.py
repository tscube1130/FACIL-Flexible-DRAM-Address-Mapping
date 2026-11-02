
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

base = RESULTS
previous = base / "extension/facil_batch_decode_feasibility/batch_sweep.csv"
out = base / "extension/facil_batch_exp12"

assert previous.is_file(), "STOP: Prior validated experiment missing"
assert not out.exists(), "STOP: Output already exists; preserve old results"

# (output rows, input columns, copies per layer, PIM waves)
shapes = [
    (4096, 4096, 2, 128),
    (1024, 4096, 2, 32),
    (14336, 4096, 2, 448),
    (4096, 14336, 1, 448)
]
layers = 32
assert sum(layers*c for m,k,c,w in shapes) == 224

total_waves = sum(layers*c*w for m,k,c,w in shapes)
assert total_waves == 53248

optimistic_t1 = total_waves * 100 / 1e6
assert abs(optimistic_t1 - 5.3248) < 1e-10

# Same analytical SoC roofline as our validated experiment.
def soc_ms(B, eta):
    total = 0
    for m,k,c,w in shapes:
        flops = 2*m*k*B
        bytes_ = 2*m*k + 2*B*(m+k)
        t = max(flops/42.5e12, bytes_/204.8e9)
        total += layers*c*t*1000/eta
    return total

# rho=0: linear PIM scaling (main assumption).
# rho>0: hypothetical future PIM batch reuse, NOT measured AiM.
def pim_ms(B, t1, rho):
    return t1*(1+(B-1)*(1-rho))

# Cross-check against our previously verified run.
checked = 0
with previous.open() as f:
    for r in csv.DictReader(f):
        if float(r["wave_ns_assumed"]) != 100:
            continue
        B = int(r["batch"])
        eta = float(r["eta_assumed"])
        assert abs(
            soc_ms(B,eta) -
            float(r["always_soc_step_ms"])
        ) < 0.001
        assert abs(
            pim_ms(B,optimistic_t1,0) -
            float(r["always_pim_step_ms"])
        ) < 0.001
        checked += 1

assert checked == 256, f"Unexpected reference rows: {checked}"
print("PASS: 256 comparisons against previous validated run")

scenarios = {
    "optimistic_100ns": optimistic_t1,
    "illustrative_20ms": 20.0
}
etas = [0.30, 0.50, 0.763, 1.0]
rhos = [0, 0.25, 0.50]
batches = range(1,65)

rows = []
crossovers = []

for scenario,t1 in scenarios.items():
    for eta in etas:
        for rho in rhos:
            first_soc = None

            for B in batches:
                soc = soc_ms(B,eta)
                pim = pim_ms(B,t1,rho)
                engine = "SoC" if soc <= pim else "PIM"

                if engine == "SoC" and first_soc is None:
                    first_soc = B

                rows.append({
                    "scenario": scenario,
                    "batch": B,
                    "eta_assumed": eta,
                    "rho_hypothetical": rho,
                    "pim_ms": round(pim,6),
                    "soc_ms": round(soc,6),
                    "adaptive_ms": round(min(pim,soc),6),
                    "chosen_engine": engine,
                    "speedup_vs_always_pim": round(
                        pim/min(pim,soc),5
                    )
                })

            crossovers.append({
                "scenario": scenario,
                "eta_assumed": eta,
                "rho_hypothetical": rho,
                "first_soc_batch": first_soc
            })

out.mkdir(parents=True)

for filename,data in [
    ("batch_sweep.csv",rows),
    ("crossovers.csv",crossovers)
]:
    with (out/filename).open("w",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)

# Experiment 1: batch width versus latency.
for scenario,t1 in scenarios.items():
    eta = 0.763
    B = list(batches)
    soc = [soc_ms(b,eta) for b in B]
    pim = [pim_ms(b,t1,0) for b in B]

    fig,ax = plt.subplots(figsize=(8.5,5.5))
    ax.plot(B,pim,label="Always PIM")
    ax.plot(B,soc,label="Always SoC")
    ax.plot(B,[min(a,b) for a,b in zip(pim,soc)],
            "--",label="FACIL batch-aware dispatch")

    ax.set_xlabel("Decode batch width (tokens)")
    ax.set_ylabel("Analytical linear-layer latency (ms)")
    ax.set_title(f"{scenario}: eta=0.763, rho=0")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.text(
        0.5,0.01,
        "Analytical scenarios, not measured end-to-end decode",
        ha="center",fontsize=9
    )
    fig.tight_layout(rect=[0,0.04,1,1])
    fig.savefig(out/f"latency_{scenario}.png",dpi=220)
    plt.close(fig)

# Experiment 2: crossover sensitivity heatmaps.
for scenario,t1 in scenarios.items():
    matrix = []
    labels = []

    for rho in rhos:
        line = []
        label_line = []
        for eta in etas:
            found = next(
                (c["first_soc_batch"] for c in crossovers
                 if c["scenario"]==scenario
                 and c["eta_assumed"]==eta
                 and c["rho_hypothetical"]==rho),
                None
            )
            line.append(float("nan") if found is None else found)
            label_line.append("None" if found is None else str(found))
        matrix.append(line)
        labels.append(label_line)

    fig,ax = plt.subplots(figsize=(7,4.3))
    im = ax.imshow(matrix,aspect="auto")
    fig.colorbar(im,ax=ax,label="First SoC batch")
    ax.set_xticks(range(len(etas)),etas)
    ax.set_yticks(range(len(rhos)),rhos)
    ax.set_xlabel("Assumed SoC efficiency eta")
    ax.set_ylabel("Hypothetical PIM reuse rho")
    ax.set_title(f"Crossover sensitivity: {scenario}")

    for i in range(len(rhos)):
        for j in range(len(etas)):
            ax.text(j,i,labels[i][j],
                    ha="center",va="center")

    fig.tight_layout()
    fig.savefig(out/f"crossover_{scenario}.png",dpi=220)
    plt.close(fig)

(out/"assumptions.json").write_text(json.dumps({
    "scope": "Linear layers of batched decode only",
    "dispatch_granularity": "Entire decode step, not each matrix",
    "pim_scenarios_ms_per_token": scenarios,
    "optimistic_100ns": "Hypothetical wave latency",
    "illustrative_20ms": "Illustrative paper-informed scenario, not measured",
    "eta": "Assumed SoC GEMM efficiency multiplier",
    "rho": "Hypothetical PIM batch reuse; rho=0 main AiM-like assumption",
    "excluded": [
        "Attention and KV-cache",
        "PIM synchronization/reduction overhead",
        "SoC kernel launches",
        "Engine-switching overhead",
        "End-to-end decode latency"
    ]
},indent=2)+"\n")

print("\nCROSSOVER TABLE")
print("Scenario                 eta     rho    First SoC batch")
for c in crossovers:
    print(
        f"{c['scenario']:<23} "
        f"{c['eta_assumed']:<7} "
        f"{c['rho_hypothetical']:<6} "
        f"{c['first_soc_batch']}"
    )

print("\nEXPERIMENTS 1 AND 2: PASS")
print("Saved:",out)
