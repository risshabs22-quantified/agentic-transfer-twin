from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config
from att.experiment import RESULTS, execute, git_commit, summary_row
from att.runner import run_settings
from scripts.run_experiments import COLUMNS

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
