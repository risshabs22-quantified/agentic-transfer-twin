from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config
from att.decision_log import read_log
from att.experiment import RESULTS, execute, git_commit, grid, settings_for, summary_row
from att.replay import replay_run
from scripts.run_experiments import COLUMNS

OUT = RESULTS / "maxmin"


def main() -> None:
    exp = config.load_experiment()
    commit = git_commit()
    rows, bad = [], 0
    for w, sc, seed, p in grid(exp):
        s = settings_for(exp, w, sc, seed, p)
        s["simulator"] = {**s["simulator"], "sharing": "maxmin"}
        man = execute(s, results_dir=OUT, commit=commit)
        bad += bool(replay_run(man, read_log(OUT / "logs" / f"{man['run_id']}.jsonl.gz")))
        rows.append(summary_row(man))
    with open(OUT / "summary.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})
    print(f"{len(rows)} max-min runs -> {(OUT / 'summary.csv').relative_to(config.ROOT)}; "
          f"replayed exactly: {len(rows) - bad}/{len(rows)}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
