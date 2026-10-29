"""Optional, costs money: run the agent team in LLM mode (`mode=llm`).

Same result workflows, scenarios and evaluation seeds as the main `agents` runs (60 runs), with
Claude (claude-opus-5-5) making the coordinator's final decision. Results go to results/llm/
(logs with every prompt and raw answer, manifests, summary.csv) and are reported separately.

Spending: every call is priced from its token usage into results/llm/spend.json; the run stops
before any call that could push the total past the cap (default $25, env ATT_LLM_CAP_USD).
Runs that already have a manifest are SKIPPED, so re-running never pays twice (use --force to redo).
Replaying LLM runs (scripts/replay.py --llm) makes no API calls.

Usage:
    python scripts/run_llm.py --workflows 1000genome-2ch --scenarios link_failure --seeds 100   # smoke test (dev)
    python scripts/run_llm.py                                                                    # the 60 runs
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.experiment import RESULTS, execute, git_commit, summary_row  # noqa: E402
from att.llm import BudgetExceeded, cap_usd, read_ledger  # noqa: E402
from att.runner import run_id, run_settings  # noqa: E402
from scripts.run_experiments import COLUMNS  # noqa: E402

OUT = RESULTS / "llm"


def llm_grid(exp: dict) -> list[tuple[str, str, int]]:
    wfs = [w for w, v in exp["workflows"].items() if v["role"] == "result"]
    return [(w, sc, seed) for w in wfs for sc in exp["scenarios"] for seed in exp["seeds"]["evaluation"]]


def write_summary(exp: dict) -> int:
    rows = []
    for w, sc, seed in llm_grid(exp):
        m = OUT / "manifests" / f"{run_id(w, sc, seed, 'agents', 'llm')}.json"
        if m.exists():
            rows.append(summary_row(json.loads(m.read_text())))
    with open(OUT / "summary.csv", "w", newline="") as fh:
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
    ap.add_argument("--force", action="store_true", help="re-run (and pay for) runs that already exist")
    args = ap.parse_args()
    exp = config.load_experiment()
    if args.workflows or args.scenarios or args.seeds:
        todo = [(w, sc, seed) for w in (args.workflows or []) for sc in (args.scenarios or exp["scenarios"])
                for seed in (args.seeds or exp["seeds"]["evaluation"])]
    else:
        todo = llm_grid(exp)
    commit = git_commit()
    print(f"cap ${cap_usd():.2f}; spent so far (upper bound) ${read_ledger()['usd_upper_bound']:.2f}")
    for w, sc, seed in todo:
        rid = run_id(w, sc, seed, "agents", "llm")
        if (OUT / "manifests" / f"{rid}.json").exists() and not args.force:
            print(f"skip   {rid} (already recorded)")
            continue
        s = run_settings(exp, w, sc, seed, planner="agents")
        s["mode"] = "llm"
        try:
            man = execute(s, results_dir=OUT, commit=commit)
        except BudgetExceeded as e:
            print(f"STOPPED: {e}")
            break
        m = man["metrics"]
        print(f"done   {rid}: {m['completion_s'] / m['deadline_D_s']:.3f} D, late {m['late']}, decisions "
              f"{m['decisions']}; spent so far ${read_ledger()['usd_upper_bound']:.2f}", flush=True)
    n = write_summary(exp)
    print(f"results/llm/summary.csv: {n} rows; total spend (upper bound) ${read_ledger()['usd_upper_bound']:.2f}")


if __name__ == "__main__":
    main()
