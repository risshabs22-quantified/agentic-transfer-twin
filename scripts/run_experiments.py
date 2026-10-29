"""Run the final experiments and write results/summary.csv.

Default: 2 result workflows x 3 scenarios x 10 evaluation seeds (0-9) x 3 planners = 180 runs.
Each run writes results/logs/<run_id>.jsonl.gz (decision log) and results/manifests/<run_id>.json
(settings, metrics, git commit, package versions). Runs don't depend on each other.

summary.csv is rebuilt from the manifests of every run in the configured grid, in a fixed order,
so running a subset (with the filters below) refreshes only those runs and gives the same rows.

Usage:
    python scripts/run_experiments.py
    python scripts/run_experiments.py --workflows montage-01d --scenarios link_failure --seeds 3 --planners agents
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.experiment import RESULTS, execute, git_commit, grid, settings_for, summary_row  # noqa: E402
from att.runner import run_id  # noqa: E402
from att.simulator import SUMMARY_FIELDS  # noqa: E402

COLUMNS = ["workflow", "scenario", "seed", "planner", "mode"] + SUMMARY_FIELDS


def write_summary(exp: dict, path: Path = RESULTS / "summary.csv") -> int:
    rows = []
    for w, sc, seed, p in grid(exp):
        m = RESULTS / "manifests" / f"{run_id(w, sc, seed, p)}.json"
        if m.exists():
            rows.append(summary_row(json.loads(m.read_text())))
    with open(path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows", nargs="*")
    ap.add_argument("--scenarios", nargs="*")
    ap.add_argument("--seeds", nargs="*", type=int)
    ap.add_argument("--planners", nargs="*")
    args = ap.parse_args()
    exp = config.load_experiment()
    todo = [g for g in grid(exp)
            if (not args.workflows or g[0] in args.workflows) and (not args.scenarios or g[1] in args.scenarios)
            and (not args.seeds or g[2] in args.seeds) and (not args.planners or g[3] in args.planners)]
    commit = git_commit()
    t0 = time.perf_counter()
    for i, (w, sc, seed, p) in enumerate(todo, 1):
        man = execute(settings_for(exp, w, sc, seed, p), commit=commit)
        m = man["metrics"]
        c = f"{m['completion_s'] / m['deadline_D_s']:.3f} D" if m["completion_s"] is not None else "incomplete"
        print(f"[{i:3}/{len(todo)}] {man['run_id']:52} {c:>10}  late {m['late']:3}  failed {m['failed_transfers']:3}",
              flush=True)
    n = write_summary(exp)
    print(f"{len(todo)} runs in {time.perf_counter() - t0:.1f} s; results/summary.csv has {n} rows")


if __name__ == "__main__":
    main()
