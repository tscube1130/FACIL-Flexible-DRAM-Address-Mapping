
from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
import sys, json, hashlib, os, re, subprocess, tempfile

sys.path.insert(0, str(ROOT / "mapping"))
from facil_mapper import Geometry, AiMMapper, choose_mapid

shapes = {
    "ffn_gate_up": (14336, 4096, 2),
    "ffn_down": (4096, 14336, 3),
}

assert len(sys.argv) == 2 and sys.argv[1] in shapes, \
    "Use: ffn_gate_up or ffn_down"

name = sys.argv[1]
rows, cols, mid = shapes[name]

root = ROOT
inp = TRACES / f"verified_baseline_{name}_2k"
prior = RESULTS / f"baseline/verified_baseline_{name}_2k/summary.json"
out = RESULTS / f"facil/facil_step3_{name}_2k"
cfg = CONFIG
sim = SIMULATOR

N = rows * cols * 2 // 128
tck = 0.3125

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

for p in (
    inp / "manifest.json",
    inp / "copy_read.trace",
    inp / "copy_write.trace",
    prior, cfg, sim,
):
    assert p.is_file(), f"Missing: {p}"

m = json.loads((inp / "manifest.json").read_text())
old = json.loads(prior.read_text())

assert m["matrix_shape"] == [rows, cols]
assert m["mapid"] == mid
assert m["transactions_per_stage"] == N
assert m["config_sha256"] == sha(cfg)
assert m["facil_mapper_sha256"] == sha(root / "mapping/facil_mapper.py")
assert m["read_trace_sha256"] == sha(inp / "copy_read.trace")
assert m["write_trace_sha256"] == sha(inp / "copy_write.trace")
assert old["read"]["completed_transactions"] == N
assert old["write"]["completed_transactions"] == N
assert old["tCK_ns"] == tck

geo = Geometry(channels=4, ranks=2, banks_per_rank=16)
assert choose_mapid(cols, geo)[0] == mid

assert not out.exists(), f"STOP: Results already exist: {out}"
out.mkdir(parents=True)

mapper = AiMMapper(geo, mid)

def encode(loc):
    vals = (
        loc.row, loc.rank, loc.bank // 4,
        loc.bank % 4, loc.column // 4, loc.channel
    )
    bits = (18, 1, 2, 2, 4, 2)
    word = 0

    for v, b in zip(vals, bits):
        assert 0 <= v < (1 << b)
        word = (word << b) | v

    return word << 7

facil_trace = out / "facil_read.trace"
baseline_trace = out / "baseline_soc_read.trace"
pages = out / "pages.txt"

with (inp / "copy_read.trace").open() as src, \
     (inp / "copy_write.trace").open() as dst, \
     facil_trace.open("w") as f, \
     baseline_trace.open("w") as b:

    for i in range(N):
        logical = i * 128
        loc = mapper.decode(logical)

        assert loc.byte_offset == 0
        assert loc.column % 4 == 0

        assert src.readline().split() == [
            f"{encode(loc):#x}", "READ", str(i)
        ], f"FACIL source mismatch at {i}"

        assert dst.readline().split() == [
            f"{0x10000000 + logical:#x}", "WRITE", str(i)
        ], f"Baseline destination mismatch at {i}"

        f.write(f"{logical:#x} READ {i}\n")
        b.write(f"{0x10000000 + logical:#x} READ {i}\n")

    assert not src.readline() and not dst.readline()

num_pages = rows * cols * 2 // (2 * 1024 * 1024)

pages.write_text(
    "".join(f"{i} {mid}\n" for i in range(num_pages))
)

print(
    f"PASS: {name}, {N:,} matched reads, "
    f"MapID {mid}, {num_pages} huge pages",
    flush=True
)

def counts(folder):
    text = (folder / "dramsim3.txt").read_text()

    reads = list(map(int, re.findall(
        r"(?m)^\s*num_reads_done\s*=\s*(\d+)", text
    )))
    writes = list(map(int, re.findall(
        r"(?m)^\s*num_writes_done\s*=\s*(\d+)", text
    )))

    assert len(reads) == len(writes) == 4
    return sum(reads), sum(writes)

def measure(label, trace, mapped, seed):
    env = os.environ.copy()
    env.pop("FACIL_PAGE_MAP_FILE", None)

    if mapped:
        env["FACIL_PAGE_MAP_FILE"] = str(pages)

    final = out / label

    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)

        def run(cycles, folder):
            folder.mkdir(parents=True, exist_ok=True)

            cmd = [
                str(sim), str(cfg),
                "-t", str(trace),
                "-c", str(cycles),
                "-o", str(folder)
            ]

            p = subprocess.run(
                cmd, env=env,
                capture_output=True, text=True
            )

            if p.returncode:
                raise RuntimeError(p.stdout + p.stderr)

            r, w = counts(folder)
            assert w == 0 and r <= N
            return r

        lo = max(0, seed - 20000)
        hi = seed + 20000

        while run(lo, scratch) == N and lo > 0:
            hi = lo
            lo = max(0, lo - 40000)

        while run(hi, scratch) != N:
            lo = hi
            hi += 40000
            assert hi < 30000000

        while hi - lo > 1024:
            midcycle = (lo + hi) // 2

            if run(midcycle, scratch) == N:
                hi = midcycle
            else:
                lo = midcycle

        assert run(hi, final) == N
        assert counts(final) == (N, 0)

    us = hi * tck / 1000

    print(f"{name} {label}: {N:,} READs, 0 WRITEs")
    print(
        f"  Completion <= {hi:,} cycles = {us:.3f} us",
        flush=True
    )

    return {
        "cycles_upper_bound": hi,
        "time_us_upper_bound": us
    }

baseline = measure(
    "conventional",
    baseline_trace,
    False,
    old["write"]["cycles_upper_bound"]
)

facil = measure(
    "facil",
    facil_trace,
    True,
    old["read"]["cycles_upper_bound"]
)

report = {
    "matrix": name,
    "shape": [rows, cols],
    "mapid": mid,
    "transactions": N,
    "baseline_conventional_read": baseline,
    "facil_native_read": facil,
    "previous_baseline_relayout_us":
        old["serialized_copy"]["estimated_time_us_upper_bound"],
    "config_sha256": sha(cfg),
    "note": "Sequential DRAM read proxy, not GEMM or TTFT"
}

(out / "comparison.json").write_text(
    json.dumps(report, indent=2) + "\n"
)

print(f"{name.upper()} STEP 3: PASS")
print("Saved:", out / "comparison.json")
