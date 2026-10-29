"""Supplementary (outside the 180 main runs): both result workflows share the
network at the same time.

1000Genome 8ch and Montage 0.1° start together at t = 0 on the normal network (background
traffic only, no scripted events), each with its own frozen data_scale and its own deadline D.
3 planners x evaluation seeds 0-9 = 30 runs; all parameters frozen; nothing tuned here.

Writes results/competing/{logs,manifests}/ and results/competing/summary.csv, then replays every
run from its log (prints REPLAY OK).

Usage:
    python scripts/run_competing.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.decision_log import read_log  # noqa: E402
from att.experiment import RESULTS, execute, git_commit  # noqa: E402
from att.replay import replay_run  # noqa: E402
from att.runner import competing_settings  # noqa: E402

OUT = RESULTS / "competing"


def main() -> None:
    exp = config.load_experiment()
    members = [w for w, v in exp["workflows"].items() if v["role"] == "result"]
    cols = ["seed", "planner", "completed", "completion_s", "late", "failed_transfers"]
    for w in members:
        cols += [f"{w}:completion_s", f"{w}:completion_D", f"{w}:late", f"{w}:failed_transfers"]
    commit = git_commit()
    rows, bad = [], 0
    for seed in exp["seeds"]["evaluation"]:
        for p in exp["planners"]:
            man = execute(competing_settings(exp, seed, p), results_dir=OUT, commit=commit)
            m = man["metrics"]
            rows.append({"seed": seed, "planner": p, **{c: m[c] for c in cols[2:]}})
            diffs = replay_run(man, read_log(OUT / "logs" / f"{man['run_id']}.jsonl.gz"))
            bad += bool(diffs)
            print(("REPLAY OK " if not diffs else "REPLAY MISMATCH ") + man["run_id"]
                  + "".join(f"  {k.split(':')[0]} {m[k]:.3f} D" for k in cols if k.endswith("completion_D")))
    with open(OUT / "summary.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        wr.writeheader()
        for r in rows:
            wr.writerow({k: ("" if r[k] is None else r[k]) for k in cols})
    print(f"{len(rows)} runs -> {(OUT / 'summary.csv').relative_to(config.ROOT)}; replay mismatches: {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
