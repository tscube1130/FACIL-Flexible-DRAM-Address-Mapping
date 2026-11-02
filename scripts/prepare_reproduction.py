#!/usr/bin/env python3
"""Seed immutable input summaries into a new scratch results root."""
from pathlib import Path
import argparse
import shutil
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--baseline-only",action="store_true")
    args=p.parse_args()
    target=args.output.resolve()
    if target.exists():p.error("Existing output preserved; choose a new scratch root")
    files=[]
    for shape in ["q_o","k_v","ffn_gate_up","ffn_down"]:
        files.append("baseline/verified_baseline_"+shape+"_2k/summary.json")
        if not args.baseline_only:
            files.append("facil/facil_step3_"+shape+"_2k/"+("matched_read_timing.json" if shape=="k_v" else "comparison.json"))
    if not args.baseline_only:
        files.extend("baseline/"+s+"/summary.json" for s in ["llama3_q_o","llama3_k_v","llama3_ffn_gate_up"])
        files.append("analytical/llama3_pim_workload/summary.json")
    for name in files:
        source=ROOT/"results"/name
        if not source.is_file():p.error("Missing required saved summary: "+str(source))
    for name in files:
        dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/"results"/name,dest)
    print(f"Copied {len(files)} immutable input summaries into {target}")
if __name__=="__main__":main()
