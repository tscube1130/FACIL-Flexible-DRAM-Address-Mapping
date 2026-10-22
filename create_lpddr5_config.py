
from configparser import ConfigParser
from math import ceil
from pathlib import Path

source = Path("configs/LPDDR4_8Gb_x16_2400.ini")
target = Path("configs/LPDDR5_6400_APPROX.ini")

cfg = ConfigParser()
cfg.optionxform = str
cfg.read(source)

# LPDDR4 protocol remains: LPDDR5 is unsupported.
cfg["dram_structure"]["protocol"] = "LPDDR4"
cfg["dram_structure"]["bankgroups"] = "4"
cfg["dram_structure"]["banks_per_group"] = "4"

# Four modeled 64-bit channels = 256 bits total.
cfg["system"]["channels"] = "4"
cfg["system"]["bus_width"] = "64"

# DRAMsim3 DDR-style equivalent tick for 6400 MT/s.
# NOT the real LPDDR5 command clock (1.25 ns).
old_tick_ns = float(cfg["timing"]["tCK"])
sim_tick_ns = 0.3125

# Preserve approximate physical time for fields where
# we have not yet substituted LPDDR5 references.
timing_ns = {
    k: float(v) * old_tick_ns
    for k, v in cfg["timing"].items()
    if k != "tCK"
}

# Selected LPDDR5-6400 timing references in nanoseconds,
# adapted from gem5's LPDDR5 BG/BL16 model.
timing_ns.update({
    "CL": 21.25,
    "CWL": 21.25,  # proxy assumption
    "tRCD": 18,
    "tRP": 18,
    "tRAS": 42,
    "tRFC": 210,
    "tREFI": 3900,
    "tRRD_S": 5,
    "tRRD_L": 5,
    "tWTR_S": 6.25,
    "tWTR_L": 12,
    "tFAW": 20,
    "tWR": 34,
    "tRTP": 4.59,
    "tCCD_S": 2.5,
    "tCCD_L": 5,
    "tXP": 7,
    "tXS": 217.5,
})

for key, ns in timing_ns.items():
    cfg["timing"][key] = str(max(1, ceil(ns / sim_tick_ns)))

cfg["timing"]["tCK"] = str(sim_tick_ns)

with target.open("w") as f:
    f.write("# LPDDR5-6400 timing proxy using LPDDR4 protocol\n")
    f.write("# Experimental approximation; NOT native LPDDR5\n")
    cfg.write(f)

print(f"Created: {target}")
print("Aggregate theoretical bandwidth: 204.8 GB/s")
print("Model: LPDDR4 protocol with LPDDR5 timing estimates")
