import argparse
import json
from pathlib import Path
from app.simulator.differential_drive import run_episode

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Ejecuta una simulación offline, claramente etiquetada como sintética.")
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--output",default="./artifacts/simulation.json")
    args=parser.parse_args()
    result=run_episode(seed=args.seed)
    path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="trace"},indent=2))
