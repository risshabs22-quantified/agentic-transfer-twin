from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config
from att.decision_log import read_log
from att.experiment import RESULTS, grid
from att.replay import replay_run
from att.runner import run_id


def replay_one(rid: str, results_dir: Path = RESULTS) -> list[str]:
    manifest = json.loads((results_dir / "manifests" / f"{rid}.json").read_text())
    entries = read_log(results_dir / "logs" / f"{rid}.jsonl.gz")
    return replay_run(manifest, entries)


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run")
    g.add_argument("--all", action="store_true")
    g.add_argument("--dir", help="replay every recorded run in a results folder, e.g. results/ablation")
    args = ap.parse_args()
    results_dir = RESULTS
    if args.all:
        exp = config.load_experiment()
        ids = [run_id(*x) for x in grid(exp)]
    elif args.dir:
        results_dir = Path(args.dir).resolve()
        ids = sorted(p.name[:-5] for p in (results_dir / "manifests").glob("*.json"))
    else:
        ids = [args.run]
    bad = 0
    for rid in ids:
        diffs = replay_one(rid, results_dir)
        if diffs:
            bad += 1
            print(f"REPLAY MISMATCH {rid}")
            for d in diffs:
                print(f"    {d}")
        else:
            print(f"REPLAY OK {rid}")
    print(f"{len(ids) - bad}/{len(ids)} runs replayed exactly")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
