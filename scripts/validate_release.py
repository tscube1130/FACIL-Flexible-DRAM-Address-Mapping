#!/usr/bin/env python3
"""Validate the release without rerunning full DRAM workloads.

Requires a fresh CMake build in build/ and installed requirements.txt.
Optional --regenerate-traces checks all four large input streams without simulation.
"""
from pathlib import Path
import argparse
import ast
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regenerate-traces",action="store_true")
    args=parser.parse_args()
    scratch=ROOT/".validation";scratch.mkdir(exist_ok=True)
    checks=[];logs=[]
    with tempfile.TemporaryDirectory(prefix="run_",dir=scratch) as td:
        work=Path(td)
        env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE="1",MPLCONFIGDIR=str(work/"mpl"),MPLBACKEND="Agg")
        env.pop("FACIL_PAGE_MAP_FILE",None);env.pop("FACIL_CHANNEL_XOR",None)
        env.pop("FACIL_RESULTS_ROOT",None);env.pop("FACIL_TRACES_ROOT",None);env.pop("FACIL_CONFIG",None);env.pop("FACIL_SIM_BINARY",None)
        def run(label,cmd,extra=None,timeout=120,cwd=ROOT):
            callenv=env.copy();callenv.update(extra or {})
            started=time.monotonic()
            p=subprocess.run([str(x) for x in cmd],cwd=cwd,env=callenv,capture_output=True,text=True,timeout=timeout)
            checks.append({"check":label,"passed":p.returncode==0,"seconds":round(time.monotonic()-started,2)})
            logs.append("\n=== "+label+" ===\n"+p.stdout+p.stderr)
            print(label+": "+("PASS" if p.returncode==0 else "FAIL"),flush=True)
            if p.returncode:raise RuntimeError(p.stdout+p.stderr)
            return p
        py=sys.executable
        for directory in ["experiments","mapping","tests"]:
            for path in (ROOT/directory).rglob("*.py"):ast.parse(path.read_text(),filename=str(path))
        checks.append({"check":"Active Python syntax","passed":True})
        run("Mapper and saved-evidence tests",[py,"-B","-m","unittest","discover","-s","tests","-v"])
        run("Original C++ tests",["cmake","--build","build","--target","dramsim3test","-j","2"],timeout=180)
        verifier=work/"verify"
        run("Compile native MapID verifier",["g++","-std=c++11","-I"+str(ROOT/"src"),"-I"+str(ROOT/"ext/headers"),"-I"+str(ROOT/"ext/fmt/include"),ROOT/"tests/native/verify_facil_decoder.cc","-L"+str(ROOT),"-ldramsim3","-Wl,-rpath,"+str(ROOT),"-o",verifier])
        fixture=ROOT/"results/facil/facil_native_validation"
        run("Native MapID 2/3 and conventional fallback",[verifier,ROOT/"configs/LPDDR5_6400_APPROX_v1.ini",fixture/"pages.txt",fixture/"expected.tsv",work/"channels.txt"])
        assert (work/"channels.txt").read_text().split()==(fixture/"channels_expected.txt").read_text().split()
        for label,trace,cycles,extra,expected in [
            ("Mixed-page channel-routing smoke",fixture/"mixed.trace",10000,{"FACIL_PAGE_MAP_FILE":str(fixture/"pages.txt")},[72,8,8,8]),
            ("One-WRITE EOF regression",work/"one_write.trace",3000,{},[0,0,0,0])]:
            if label.startswith("One"):(work/"one_write.trace").write_text("0x0 WRITE 0\n")
            dest=work/("mixed" if label.startswith("Mixed") else "eof");dest.mkdir()
            run(label,[ROOT/"build/dramsim3main",ROOT/"configs/LPDDR5_6400_APPROX_v1.ini","-t",trace,"-c",str(cycles),"-o",dest],extra=extra)
            data=json.loads((dest/"dramsim3.json").read_text())
            assert [int(data[str(i)]["num_reads_done"]) for i in range(4)]==expected
            if label.startswith("One"):
                assert sum(int(x["num_writes_done"]) for x in data.values())==1
                issued=sum(int(x["num_write_cmds"]) for x in data.values())
                assert issued<=1
                checks.append({"check":"EOF callback/command distinction","passed":True,"write_callbacks":1,"write_commands_issued":issued,"note":"A lone acknowledged write may remain buffered; this is not a write-drain test"})
        run("Baseline byte-layout correctness",[py,"-B","experiments/baseline/verify_baseline_relayout.py"])
        isolated=work/"results"
        for group in ["baseline","facil"]:
            for p in (ROOT/"results"/group).rglob("*.json"):
                # Native statistics are not required by analytical reproduction.
                if p.name not in ["summary.json","comparison.json","matched_read_timing.json"]:continue
                dest=isolated/p.relative_to(ROOT/"results");dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        budget=isolated/"analytical/llama3_pim_workload";budget.mkdir(parents=True)
        shutil.copy2(ROOT/"results/analytical/llama3_pim_workload/summary.json",budget/"summary.json")
        # Output guards must see no previous TTFT plots or model outputs.
        pipeline=[
            ("SoC roofline self-test","experiments/analytical/soc_gemm_roofline.py",["--self-test"]),
            ("SoC roofline reproduction","experiments/analytical/soc_gemm_roofline.py",[]),
            ("FACIL TTFT and comparison figures","experiments/facil/facil_comparison_figures.py",[]),
            ("Analytical PIM GEMV reproduction","experiments/analytical/pim_gemv_analytical.py",[]),
            ("PIM sensitivity figures","experiments/analytical/plot_pim_sensitivity.py",[]),
            ("Batch feasibility","experiments/extension/batch_dispatch_feasibility.py",[]),
            ("Experiments 1-2 crossover/sensitivity","experiments/extension/batch_crossover_sensitivity.py",[]),
            ("Experiments 3-4 switching/policies","experiments/extension/batch_trace_switching.py",[]),
            ("PIM timing budget","experiments/analytical/pim_llama3_timing_budget.py",[]),
            ("Earlier TTFT scenario preservation","experiments/analytical/ttft_llama3_baseline.py",[]),
            ("Placement audit","mapping/validate_placement.py",[]),
            ("Structural lockstep audit","mapping/check_lockstep_groups.py",[])]
        for label,script,options in pipeline:
            run(label,[py,"-B",ROOT/script]+options,extra={"FACIL_RESULTS_ROOT":str(isolated)},cwd=work)
        matches=[]
        for folder in ["extension/facil_batch_decode_feasibility","extension/facil_batch_exp12","extension/facil_batch_exp34","analytical/facil_pim_gemv_analytical","analytical/llama3_soc_gemm_analytical","facil/facil_step6_comparison","analytical/llama3_ttft","mapping/llama3_validation/placement_audit","mapping/llama3_validation/lockstep_grouping"]:
            for original in (ROOT/"results"/folder).iterdir():
                generated=isolated/folder/original.name
                if original.suffix not in [".csv",".json"] or not generated.is_file():continue
                a=original.read_bytes();b=generated.read_bytes()
                if folder=="mapping/llama3_validation/placement_audit" and original.name=="summary.json":
                    old=json.loads(a);new=json.loads(b)
                    for obj in [old,new]:
                        for case in obj["cases"]:case.pop("csv",None)
                    assert old==new,folder+"/"+original.name
                elif original.name=="assumptions_and_results.json":
                    old=json.loads(a);new=json.loads(b);old.pop("script_sha256",None);new.pop("script_sha256",None)
                    assert old==new,folder+"/"+original.name
                else:assert a==b,"Saved output differs: "+folder+"/"+original.name
                matches.append(folder+"/"+original.name)
        checks.append({"check":"Saved numerical outputs reproduced exactly","passed":True,"files":matches})
        # Mechanical regeneration of all matched-read traces (no simulator).
        inventory={x["path"]:x for x in json.loads((ROOT/"docs/provenance/TRACE_CHECKSUMS.json").read_text())}
        for shape in ["q_o","k_v","ffn_gate_up","ffn_down"]:
            dest=work/("matched_"+shape)
            run("Regenerate matched trace: "+shape,[py,"-B",ROOT/"experiments/facil/generate_matched_read_traces.py",shape,"--output",dest])
            for name in ["facil_read.trace","baseline_soc_read.trace"]:
                key="results/facil/facil_step3_"+shape+"_2k/"+name
                assert sha(dest/name)==inventory[key]["sha256"],key
        if args.regenerate_traces:
            for name,m,k in [("q_o",4096,4096),("k_v",1024,4096),("ffn_gate_up",14336,4096),("ffn_down",4096,14336)]:
                dest=work/("baseline_"+name)
                run("Regenerate baseline trace: "+name,[py,"-B",ROOT/"experiments/baseline/generate_verified_baseline_traces_2k.py","--rows",m,"--cols",k,"--output",dest],timeout=180)
                original=json.loads((ROOT/"traces"/("verified_baseline_"+name+"_2k")/"manifest.json").read_text())
                for filename,key in [("copy_read.trace","read_trace_sha256"),("copy_write.trace","write_trace_sha256")]:assert sha(dest/filename)==original[key],name+" "+key
                generated=json.loads((dest/"manifest.json").read_text())
                assert generated["request_mapping_sha256"]==original["request_mapping_sha256"]
        # Output/root/bootstrap checks above run experiments from a non-repository CWD.
    (scratch/"validation.log").write_text("".join(logs))
    (scratch/"validation.json").write_text(json.dumps(checks,indent=2)+"\n")
    print(f"Validation complete: {len(checks)} checks; logs in .validation/",flush=True)
if __name__=="__main__":main()
