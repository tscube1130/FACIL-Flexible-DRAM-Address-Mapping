
from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
import csv, json, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

base = RESULTS
src = base / "extension/facil_batch_exp12/batch_sweep.csv"
out = base / "extension/facil_batch_exp34"

assert src.is_file(), "STOP: Experiment 1-2 data missing"
assert not out.exists(), "STOP: Preserve existing experiment outputs"

with src.open() as f:
    records = list(csv.DictReader(f))

data = {}
for r in records:
    key = (
        r["scenario"],
        float(r["eta_assumed"]),
        float(r["rho_hypothetical"]),
        int(r["batch"])
    )
    assert key not in data, f"Duplicate row: {key}"
    data[key] = (
        float(r["pim_ms"]),
        float(r["soc_ms"])
    )

assert len(data) == 1536, "Incomplete experiment 1-2 data"

scenarios = ["optimistic_100ns", "illustrative_20ms"]
etas = [0.5, 0.763]
rhos = [0.0, 0.5]

traces = {
    "rising":      [1, 4, 16, 32, 64],
    "falling":     [64, 32, 16, 4, 1],
    "oscillating": [1, 32, 4, 64, 8, 48, 2, 64]
}

def curve_for(scenario, eta, rho, trace):
    return [data[(scenario, eta, rho, b)] for b in trace]

def static_costs(curve):
    return (
        sum(p for p, s in curve),
        sum(s for p, s in curve)
    )

def ideal_dispatch(curve):
    return sum(min(p, s) for p, s in curve)

# Offline optimal switching schedule.
# It knows the full future batch sequence and is an upper-bound policy,
# NOT a deployable online prediction algorithm.
def optimal_schedule(curve, overhead):
    p0, s0 = curve[0]
    states = {
        "PIM": (p0, ["PIM"], 0),
        "SoC": (s0, ["SoC"], 0)
    }

    for p, s in curve[1:]:
        next_states = {}
        for new_engine, step_cost in (("PIM", p), ("SoC", s)):
            options = []
            for old_engine, (total, path, switches) in states.items():
                switching = old_engine != new_engine
                options.append((
                    total + step_cost + (overhead if switching else 0),
                    path + [new_engine],
                    switches + int(switching)
                ))
            next_states[new_engine] = min(
                options, key=lambda x: (x[0], x[2])
            )
        states = next_states

    return min(states.values(), key=lambda x: (x[0], x[2]))

# Deployable, simple online hysteresis:
# switch only if this step's saving exceeds the transition cost.
def online_hysteresis(curve, overhead):
    p0, s0 = curve[0]
    engine = "PIM" if p0 <= s0 else "SoC"
    path = [engine]
    total = min(p0, s0)
    switches = 0

    for p, s in curve[1:]:
        current = p if engine == "PIM" else s
        alternative = s if engine == "PIM" else p

        if current - alternative > overhead:
            engine = "SoC" if engine == "PIM" else "PIM"
            total += alternative + overhead
            switches += 1
        else:
            total += current

        path.append(engine)

    return total, path, switches

# Exact maximum per-switch overhead for ANY offline schedule
# to strictly outperform the best static engine.
# Dynamic programming tracks minimum zero-overhead cost for
# each possible number of engine transitions.
def switching_limit(curve):
    p0, s0 = curve[0]
    dp = {("PIM", 0): p0, ("SoC", 0): s0}

    for p, s in curve[1:]:
        nxt = {}
        for (old, count), cost in dp.items():
            for new, step in (("PIM", p), ("SoC", s)):
                n = count + int(old != new)
                key = (new, n)
                candidate = cost + step
                nxt[key] = min(
                    nxt.get(key, math.inf), candidate
                )
        dp = nxt

    best_static = min(static_costs(curve))
    limits = [
        (best_static - cost) / n
        for (engine, n), cost in dp.items()
        if n > 0 and cost < best_static
    ]

    return max([0.0] + limits)

# On-demand conversion baseline:
# every selected SoC pass pays a full re-layout.
# No converted weight copy persists between steps.
def on_demand(curve, relayout_ms):
    decisions = [
        "SoC" if s + relayout_ms < p else "PIM"
        for p, s in curve
    ]
    total = sum(
        min(p, s + relayout_ms)
        for p, s in curve
    )
    return total, decisions.count("SoC")

# ---------- Mandatory sanity checks ----------

for scenario, expected in [
    ("optimistic_100ns", 5.3248),
    ("illustrative_20ms", 20.0)
]:
    for eta in etas:
        for rho in rhos:
            p, s = data[(scenario, eta, rho, 1)]
            assert abs(p - expected) < 1e-5

# Larger hypothetical reuse must not make PIM slower.
for scenario in scenarios:
    for eta in etas:
        for B in range(1, 65):
            p0 = data[(scenario, eta, 0.0, B)][0]
            p5 = data[(scenario, eta, 0.5, B)][0]
            assert p5 <= p0 + 1e-5

results = []
summaries = []

for scenario in scenarios:
    for eta in etas:
        for rho in rhos:
            for trace_name, batches in traces.items():
                curve = curve_for(scenario, eta, rho, batches)

                always_pim, always_soc = static_costs(curve)
                best_static = min(always_pim, always_soc)

                # Weight duplication: both layouts already exist.
                # At zero transition overhead, dispatch = ideal minimum.
                duplication = ideal_dispatch(curve)

                # FACIL has no second weight copy.
                zero_cost, zero_path, zero_switches = (
                    optimal_schedule(curve, 0.0)
                )

                assert abs(zero_cost - duplication) < 1e-4
                assert duplication <= best_static + 1e-4

                h_max = switching_limit(curve)

                # A sufficiently large transition cost makes the
                # OFFLINE optimal policy choose a static engine.
                huge_cost, huge_path, huge_switches = (
                    optimal_schedule(curve, 1e9)
                )

                assert abs(huge_cost - best_static) < 1e-4
                assert huge_switches == 0

                # Check that computed h_max really is the boundary.
                above, _, _ = optimal_schedule(
                    curve, h_max + max(0.001, h_max * 0.001)
                )
                assert abs(above - best_static) < 1e-4

                if h_max > 0.01:
                    below, _, _ = optimal_schedule(
                        curve, h_max * 0.5
                    )
                    assert below < best_static - 1e-5

                demand447, n447 = on_demand(
                    curve, 447.28352
                )
                demand200, n200 = on_demand(
                    curve, 200.0
                )

                assert demand447 <= always_pim + 1e-4
                assert demand200 <= demand447 + 1e-4

                summary = {
                    "scenario": scenario,
                    "eta": eta,
                    "rho": rho,
                    "trace": trace_name,
                    "steps": len(batches),
                    "always_pim_ms": round(always_pim, 5),
                    "always_soc_ms": round(always_soc, 5),
                    "best_static_ms": round(best_static, 5),
                    "duplication_ideal_ms": round(duplication, 5),
                    "facil_zero_overhead_ms": round(zero_cost, 5),
                    "ideal_switches": zero_switches,
                    "offline_hmax_ms_per_switch": round(h_max, 5),
                    "on_demand_447ms": round(demand447, 5),
                    "on_demand_447_soc_steps": n447,
                    "on_demand_200ms": round(demand200, 5),
                    "on_demand_200_soc_steps": n200,
                    "zero_overhead_path": "-".join(zero_path)
                }
                summaries.append(summary)

                overheads = sorted(set([
                    0.0, 0.5, 2.0, 5.0,
                    10.0, 25.0, 50.0,
                    h_max / 2,
                    h_max,
                    h_max * 1.1,
                    1e9
                ]))

                for h in overheads:
                    offline, path, switches = (
                        optimal_schedule(curve, h)
                    )
                    online, opath, oswitches = (
                        online_hysteresis(curve, h)
                    )

                    assert offline <= best_static + 1e-4
                    assert offline <= online + 1e-4

                    results.append({
                        "scenario": scenario,
                        "eta": eta,
                        "rho": rho,
                        "trace": trace_name,
                        "overhead_ms_per_switch": round(h, 6),
                        "offline_optimal_ms": round(offline, 5),
                        "offline_switches": switches,
                        "offline_path": "-".join(path),
                        "online_hysteresis_ms": round(online, 5),
                        "online_switches": oswitches,
                        "online_path": "-".join(opath),
                        "best_static_ms": round(best_static, 5),
                        "duplication_ideal_ms": round(duplication, 5),
                        "on_demand_447ms": round(demand447, 5),
                        "on_demand_200ms": round(demand200, 5)
                    })

# Weight memory, exact from Llama3 linear matrix dimensions.
shapes = [
    (4096, 4096, 2),
    (1024, 4096, 2),
    (14336, 4096, 2),
    (4096, 14336, 1)
]

weights_bytes = 32 * sum(
    m * k * copies * 2
    for m, k, copies in shapes
)

assert weights_bytes == 13958643712
weight_gb = weights_bytes / 1e9

out.mkdir(parents=True)

def save_csv(filename, rows):
    with (out / filename).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

save_csv("dynamic_policy_results.csv", results)
save_csv("switching_overhead_limits.csv", summaries)

memory_rows = [
    {
        "policy": "Always PIM",
        "linear_weight_copies": 1,
        "weight_storage_GB": round(weight_gb, 4),
        "additional_weight_storage_GB": 0,
        "note": "Static PIM execution"
    },
    {
        "policy": "Weight duplication + ideal dispatch",
        "linear_weight_copies": 2,
        "weight_storage_GB": round(2 * weight_gb, 4),
        "additional_weight_storage_GB": round(weight_gb, 4),
        "note": "Same ideal latency as zero-overhead FACIL"
    },
    {
        "policy": "FACIL batch-aware dispatch",
        "linear_weight_copies": 1,
        "weight_storage_GB": round(weight_gb, 4),
        "additional_weight_storage_GB": 0,
        "note": "Page mapping metadata not included"
    },
    {
        "policy": "On-demand re-layout",
        "linear_weight_copies": 1,
        "weight_storage_GB": round(weight_gb, 4),
        "additional_weight_storage_GB": 0,
        "note": "Temporary conversion buffers not included"
    }
]
save_csv("weight_memory_comparison.csv", memory_rows)

# Figures: overhead tolerance for each workload.
# Main presentation uses rho=0 and eta=0.763.
for scenario in scenarios:
    for trace_name, batches in traces.items():
        curve = curve_for(
            scenario, 0.763, 0.0, batches
        )

        static_pim, static_soc = static_costs(curve)
        duplication = ideal_dispatch(curve)
        limit = switching_limit(curve)
        d447, _ = on_demand(curve, 447.28352)
        d200, _ = on_demand(curve, 200.0)

        upper = max(10.0, 1.25 * limit)
        xs = [upper * i / 100 for i in range(101)]

        offline = [
            optimal_schedule(curve, h)[0] for h in xs
        ]
        online = [
            online_hysteresis(curve, h)[0] for h in xs
        ]

        fig, ax = plt.subplots(figsize=(9, 5.8))
        ax.plot(xs, offline, label="FACIL offline optimal")
        ax.plot(xs, online, "--", label="Online hysteresis")
        ax.axhline(
            duplication, label="Duplication: ideal, 2x weights",
            linestyle=":"
        )
        ax.axhline(
            min(static_pim, static_soc),
            label="Best static engine", linestyle="-."
        )
        ax.axhline(
            d200, label="On-demand: 200 ms/pass",
            linestyle=":"
        )
        ax.axhline(
            d447, label="On-demand: 447 ms/pass",
            linestyle=":"
        )

        ax.set_xlabel("Assumed FACIL transition overhead (ms/switch)")
        ax.set_ylabel("Total linear-layer decode latency (ms)")
        ax.set_title(
            f"{scenario} | {trace_name} batches | "
            "eta=0.763, rho=0"
        )
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)

        fig.text(
            0.5, 0.01,
            "Analytical model; offline optimal knows future batches. "
            "Not measured end-to-end decode.",
            ha="center", fontsize=8
        )
        fig.tight_layout(rect=(0, 0.05, 1, 1))
        fig.savefig(
            out / f"overhead_{scenario}_{trace_name}.png",
            dpi=220
        )
        plt.close(fig)

(out / "assumptions.json").write_text(
    json.dumps({
        "scope": "Llama3-8B linear projections only",
        "decode_batch_traces": traces,
        "engines": "PIM and SoC",
        "policy": "One engine per entire decode step",
        "offline_optimal": "Knows future steps; an upper bound",
        "online_hysteresis":
            "Switch when current-step saving exceeds overhead",
        "initial_engine": "Free choice at first step",
        "facil_weight_copies": 1,
        "duplication_weight_copies": 2,
        "weight_bytes_per_copy": weights_bytes,
        "conversion_per_soc_pass_ms": {
            "our_D​RAMsim3_estimate": 447.28352,
            "illustrative_paper_scale": 200
        },
        "on_demand_baseline":
            "Converts linear weights for every selected SoC pass; "
            "no persistent converted copy",
        "switching_overhead":
            "Unmeasured; swept as a parameter",
        "hmax":
            "Largest uniform transition overhead for which "
            "some offline mixed-engine schedule beats best static",
        "excluded": [
            "Attention",
            "KV-cache traffic",
            "Kernel launches",
            "Actual PIM hardware switching cost",
            "Memory capacity constraints on real devices",
            "End-to-end decoding latency"
        ]
    }, indent=2
    ) + "\n"
)

print("PASS: Batch-1 PIM latency")
print("PASS: PIM reuse monotonicity")
print("PASS: Zero-overhead FACIL = duplication latency")
print("PASS: Offline adaptive never exceeds best static")
print("PASS: Huge overhead reduces offline optimum to static")
print("PASS: Exact switching-overhead boundaries")
print("PASS: On-demand conversion ordering")

print("\nLINEAR WEIGHT STORAGE:")
print(f"One copy:  {weight_gb:.3f} GB")
print(f"Two copies: {2*weight_gb:.3f} GB")
print(f"Duplication adds: {weight_gb:.3f} GB")

print("\nMAIN RESULTS: eta=0.763, rho=0")
print("Scenario                  Trace         h_max(ms)  switches")
for r in summaries:
    if r["eta"] == 0.763 and r["rho"] == 0.0:
        print(
            f"{r['scenario']:<25}"
            f"{r['trace']:<14}"
            f"{r['offline_hmax_ms_per_switch']:<11}"
            f"{r['ideal_switches']}"
        )

print("\nEXPERIMENTS 3 AND 4: PASS")
print("Saved:", out)
