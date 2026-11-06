from __future__ import annotations

import itertools
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config
from att.agents import AgentTeam
from att.runner import run_one

GRID = {
    "priority_fraction": [0.1, 0.2, 0.3, 0.5],
    "move_margin": [0.0, 0.1, 0.25],
    "draft_margin": [0.0, 0.05, 0.1],
}
OUT = config.ROOT / "results" / "tuning" / "agent_tuning.json"


def main() -> None:
    exp = config.load_experiment()
    seeds = exp["seeds"]["tuning"]
    dev = [w for w, v in exp["workflows"].items() if v["role"] == "dev"]
    rows = []
    for values in itertools.product(*GRID.values()):
        params = dict(zip(GRID, values))
        per = {}
        for wf in dev:
            for sc in exp["scenarios"]:
                ms = [run_one(exp, wf, sc, s, AgentTeam(**params))[0] for s in seeds]
                per[f"{wf}/{sc}"] = {
                    "completion_D": statistics.fmean(m["completion_s"] / m["deadline_D_s"] for m in ms),
                    "late_frac": statistics.fmean(m["late"] / m["n_transfers"] for m in ms),
                }
        row = {**params,
               "mean_completion_D": statistics.fmean(v["completion_D"] for v in per.values()),
               "mean_late_frac": statistics.fmean(v["late_frac"] for v in per.values()),
               "per_case": per}
        rows.append(row)
        print(" ".join(f"{k}={v}" for k, v in params.items()),
              f"-> {row['mean_completion_D']:.4f} D, late {100 * row['mean_late_frac']:.2f}%", flush=True)
    best = min(rows, key=lambda r: (r["mean_completion_D"], r["mean_late_frac"]))
    chosen = {k: best[k] for k in GRID}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"dev_workflows": dev, "seeds": seeds, "grid": GRID, "chosen": chosen,
                               "rows": rows}, indent=1) + "\n")
    print("chosen:", chosen)
    print(f"wrote {OUT.relative_to(config.ROOT)}  (copy 'chosen' into configs/experiment.yaml -> agents)")


if __name__ == "__main__":
    main()
