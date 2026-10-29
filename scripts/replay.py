"""Replay logged runs from their decision logs (no agent code, no LLM) and check the metrics.

For each run: rebuild the simulator from the manifest's settings, drive it with a ReplayPlanner
fed from results/logs/<run_id>.jsonl.gz, and compare the metrics with the manifest: integers and
booleans exactly, floats within 1e-9 relative. Prints "REPLAY OK <run_id>" or the differing fields.
Exits non-zero if any run mismatches.

Usage:
    python scripts/replay.py --all
    python scripts/replay.py --run 1000genome-8ch__link_failure__seed3__agents
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.decision_log import read_log  # noqa: E402
from att.experiment import RESULTS, grid  # noqa: E402
from att.replay import replay_run  # noqa: E402
from att.runner import run_id  # noqa: E402


def replay_one(rid: str, results_dir: Path = RESULTS) -> list[str]:
    """Return a list of differences (empty = OK)."""
    manifest = json.loads((results_dir / "manifests" / f"{rid}.json").read_text())
    entries = read_log(results_dir / "logs" / f"{rid}.jsonl.gz")
    return replay_run(manifest, entries)


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--run")
    g.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.all:
        exp = config.load_experiment()
        ids = [run_id(*x) for x in grid(exp)]
    else:
        ids = [args.run]
    bad = 0
    for rid in ids:
        diffs = replay_one(rid)
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
