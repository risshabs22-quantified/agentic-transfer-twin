"""Supplementary ablation (not part of the 180 main runs): where does the agents' advantage come from?

`agents_static` = the agent team's initial plan (load balancing + priorities + forecast-checked
draft choice), but it NEVER reacts to events. Comparing it with `agents` separates
"planning well up front" from "coordinating when something happens".

Same result workflows, scenarios and evaluation seeds as the main runs; nothing is tuned here.
Writes results/ablation/{logs,manifests}/ and results/ablation/summary.csv (same columns).

Usage:
    python scripts/run_ablation.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.experiment import RESULTS, execute, git_commit, summary_row  # noqa: E402
from att.runner import run_settings  # noqa: E402
from scripts.run_experiments import COLUMNS  # noqa: E402

OUT = RESULTS / "ablation"


def main() -> None:
    exp = config.load_experiment()
    wfs = [w for w, v in exp["workflows"].items() if v["role"] == "result"]
    commit = git_commit()
    rows = []
    for w in wfs:
        for sc in exp["scenarios"]:
            for seed in exp["seeds"]["evaluation"]:
                man = execute(run_settings(exp, w, sc, seed, planner="agents_static"), results_dir=OUT, commit=commit)
                rows.append(summary_row(man))
    with open(OUT / "summary.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})
    print(f"{len(rows)} ablation runs -> {(OUT / 'summary.csv').relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
