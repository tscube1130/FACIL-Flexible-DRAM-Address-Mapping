"""Read-only checks of the original coursework evidence and reported claims."""
from pathlib import Path
import configparser
import csv
import hashlib
import json
import unittest
ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
def load(path):
    return json.loads(path.read_text())
def rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))
class EvidenceTests(unittest.TestCase):
    def test_geometry_and_original_provenance(self):
        path = ROOT / "configs/LPDDR5_6400_APPROX_v1.ini"
        cfg = configparser.ConfigParser(); cfg.read(path)
        self.assertEqual((cfg["dram_structure"]["protocol"], cfg.getint("dram_structure", "columns"), cfg.getint("dram_structure", "rows")), ("LPDDR4", 256, 262144))
        self.assertEqual(cfg.getint("system", "channels"), 4)
        self.assertEqual(cfg.getint("dram_structure", "columns") * cfg.getint("system", "bus_width") // 8, 2048)
        self.assertEqual(cfg.getfloat("timing", "tCK"), 0.3125)
        mapper_hash = hashlib.sha256((ROOT / "mapping/facil_mapper.py").read_bytes()).hexdigest()
        cfg_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        total = 0.0
        for name, m, k, copies in [("q_o",4096,4096,2),("k_v",1024,4096,2),("ffn_gate_up",14336,4096,2),("ffn_down",4096,14336,1)]:
            directory = RESULTS / "baseline" / ("verified_baseline_" + name + "_2k")
            data = load(directory / "summary.json")
            manifest = load(ROOT / "traces" / ("verified_baseline_" + name + "_2k") / "manifest.json")
            count = m*k*2//128
            self.assertEqual(manifest["requests_per_stage"], count)
            self.assertEqual(manifest["config_sha256"], cfg_hash)
            self.assertEqual(manifest["facil_mapper_sha256"], mapper_hash)
            self.assertEqual(manifest["channel_read_requests"], [count//4]*4)
            self.assertEqual(data["matrix_bytes"], m*k*2)
            for stage, key in [("read","num_reads_done"),("write","num_writes_done")]:
                record = data[stage]
                self.assertEqual(record["completed_transactions"], count)
                native = load(directory / stage / "dramsim3.json")
                self.assertEqual(sum(int(c[key]) for c in native.values()), count)
                self.assertAlmostEqual(record["cycles_upper_bound"]*0.3125/1000, record["elapsed_us_upper_bound"], places=6)
            total += 32*copies*data["serialized_copy"]["estimated_time_us_upper_bound"]/1000
        self.assertAlmostEqual(total,447.28352,places=7)
    def test_ttft_component_table(self):
        for r in rows(RESULTS / "facil/facil_step6_comparison/ttft_comparison.csv"):
            self.assertAlmostEqual(float(r["baseline_ms"])-float(r["facil_ideal_ms"]),447.28352,places=5)
            self.assertAlmostEqual(float(r["facil_sensitivity_ms"])-float(r["facil_ideal_ms"]),308.96428,places=5)
    def test_batch_crossovers_and_minimum(self):
        base = RESULTS / "extension/facil_batch_exp12"
        data=rows(base/"batch_sweep.csv");self.assertEqual(len(data),1536)
        for r in data:
            self.assertAlmostEqual(float(r["adaptive_ms"]),min(float(r["pim_ms"]),float(r["soc_ms"])),places=6)
        for scenario,expected in [("optimistic_100ns",17),("illustrative_20ms",5)]:
            r=next(r for r in rows(base/"crossovers.csv") if r["scenario"]==scenario and float(r["eta_assumed"])==0.763 and float(r["rho_hypothetical"])==0)
            self.assertEqual(int(r["first_soc_batch"]),expected)
    def test_switching_and_conceptual_duplication(self):
        base=RESULTS/"extension/facil_batch_exp34"
        expected={"optimistic_100ns": [156.86848,156.86848,84.03698], "illustrative_20ms": [78.82422,78.82422,69.36178]}
        for scenario,limits in expected.items():
            for trace,limit in zip(["rising","falling","oscillating"],limits):
                r=next(r for r in rows(base/"switching_overhead_limits.csv") if r["scenario"]==scenario and float(r["eta"])==0.763 and float(r["rho"])==0 and r["trace"]==trace)
                self.assertAlmostEqual(float(r["offline_hmax_ms_per_switch"]),limit,places=5)
                self.assertAlmostEqual(float(r["facil_zero_overhead_ms"]),float(r["duplication_ideal_ms"]),places=5)
        for r in rows(base/"dynamic_policy_results.csv"):
            self.assertLessEqual(float(r["offline_optimal_ms"]),float(r["best_static_ms"])+1e-4)
            self.assertLessEqual(float(r["offline_optimal_ms"]),float(r["online_hysteresis_ms"])+1e-4)
        assumptions=load(base/"assumptions.json")
        self.assertEqual(assumptions["weight_bytes_per_copy"],13958643712)
        self.assertEqual(assumptions["facil_weight_copies"],1)
        self.assertEqual(assumptions["duplication_weight_copies"],2)
    def test_bandwidth_diagnostic_saved_evidence(self):
        base=RESULTS/"extension/facil_batch_exp5"
        data=rows(base/"bandwidth_diagnostic.csv");self.assertEqual(len(data),4)
        def trace(p):
            return [(int(t[0],0),t[1],int(t[2])) for line in p.read_text().splitlines() if (t:=line.split())]
        for stage in ["read","write"]:
            a=trace(base/"traces"/(stage+"_original.trace"));b=trace(base/"traces"/(stage+"_sequential.trace"))
            self.assertEqual(len(a),32768);self.assertEqual(len({x[0] for x in a}),32768)
            self.assertEqual(sorted(x[0] for x in a),[x[0] for x in b])
            self.assertEqual([(x[1],x[2]) for x in a],[(x[1],x[2]) for x in b])
            seen=set();sample=[]
            with (ROOT/"traces/llama3_k_v_permutation"/("copy_"+stage+".trace")).open() as f:
                for line in f:
                    t=line.split()
                    if not t: continue
                    address=int(t[0],0)&~127
                    if address not in seen:seen.add(address);sample.append((address,t[1],int(t[2])))
                    if len(sample)==32768:break
            start=sample[0][2]
            self.assertEqual(a,[(x,y,z-start) for x,y,z in sample])
        for r in data:
            n=int(r["transactions"]);cycles=int(r["cycles_approx"])
            self.assertEqual(n,32768);self.assertEqual(int(r["bytes"]),128*n)
            self.assertAlmostEqual(float(r["duration_us_approx"]),cycles*0.3125/1000,places=6)
            self.assertAlmostEqual(float(r["bandwidth_GBs_approx"]),128*n/(cycles*0.3125),places=3)
            counter="num_reads_done" if r["stage"]=="read" else "num_write_cmds"
            native=load(base/("native_"+r["stage"]+"_"+r["access_order"])/"dramsim3.json")
            self.assertEqual(sum(int(v[counter]) for v in native.values()),n)
            self.assertEqual(r["completion_definition"],"reads completed" if r["stage"]=="read" else "write commands issued")
        self.assertAlmostEqual(float(data[0]["bandwidth_GBs_approx"]),66.198,places=3)
        self.assertAlmostEqual(float(data[1]["bandwidth_GBs_approx"]),201.6492,places=3)
if __name__=="__main__": unittest.main()
