"""Tell the life story of one transfer in one recorded run: extraction -> plan -> events -> arrival.

Everything printed comes from the run's manifest settings, its decision log, and a fresh
deterministic re-run (which replay guarantees is identical to the recorded one).

Usage:
    python scripts/trace_transfer.py --run 1000genome-8ch__link_failure__seed3__agents \
        --transfer chr3n-4001-5001.tar.gz@FNAL
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att.decision_log import read_log  # noqa: E402
from att.experiment import RESULTS  # noqa: E402
from att.replay import ReplayPlanner  # noqa: E402
from att.runner import sim_from_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="1000genome-8ch__link_failure__seed3__agents")
    ap.add_argument("--transfer", default="chr3n-4001-5001.tar.gz@FNAL")
    a = ap.parse_args()
    man = json.loads((RESULTS / "manifests" / f"{a.run}.json").read_text())
    log = read_log(RESULTS / "logs" / f"{a.run}.jsonl.gz")
    sim = sim_from_settings(man["settings"])
    D = sim.D
    req = sim.req[a.transfer]
    task = sim.workflow["tasks"]
    print(f"Run {a.run}   (D = {D:.3f} s)")
    print(f"\n1. EXTRACTION  file {req['file']}: {req['bytes'] / 1e9:.3f} GB (after data_scale "
          f"x{man['settings']['data_scale']}), {req['src']} -> {req['dst']}")
    if req["after_task"]:
        t = task[req["after_task"]]
        print(f"   produced by task {req['after_task']} at {t['site']} (runtime {t['runtime_s']:.2f} s, "
              f"earliest finish {t['earliest_finish_s']:.2f} s)")
    users = [tid for tid, t in task.items() if req["file"] in t["inputs"] and t["site"] == req["dst"]]
    print(f"   needed at {req['dst']} by {', '.join(users)}; deadline {req['deadline_s']:.3f} s "
          f"(= latest start of the earliest of them)")
    untouched = 0
    for d in log:
        if a.transfer in d["decision"]:
            e = d["decision"][a.transfer]
            print(f"\n{'2. INITIAL PLAN' if d['seq'] == 0 else 'EVENT ' + d['trigger']['type']} at t = {d['t']:.3f} s "
                  f"({d['t'] / D:.3f} D) by {d['agent']}: path {' -> '.join(e['path'])}, priority {e['priority']}, "
                  f"start_s {e['start_s']:.3f}")
            print(f"   reason: {d['reason']}")
        elif d["trigger"]["type"] != "initial_plan":
            untouched += 1
    if untouched:
        print(f"\n   ({untouched} other planner decision(s) in this run did not change this transfer)")
    m = sim.run(ReplayPlanner(log))
    x = sim.by_id[a.transfer]
    print(f"\n3. IN THE SIMULATOR  data ready at {x.ready_t:.3f} s; last byte sent at {x.sent_t:.3f} s; "
          f"arrived at {x.arrive_t:.3f} s (deadline {x.deadline_s:.3f} s -> "
          f"{'on time' if x.arrive_t <= x.deadline_s else 'LATE'}); failed attempts {x.failed_attempts}")
    print(f"   final route {' -> '.join(x.path)}; run completed at {m['completion_s']:.3f} s ({m['completion_s'] / D:.3f} D)")


if __name__ == "__main__":
    main()
