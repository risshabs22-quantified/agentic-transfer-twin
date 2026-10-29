"""Stage 4 tuning: choose data_scale per workflow and check each stress scenario really stresses it.

Uses ONLY the plain `baseline` planner and ONLY the tuning seeds (100-104), before any agent
exists, so nothing about the agents can leak into the network settings.

Rule:
 1. data_scale = the LARGEST value in SCALES where, in `normal`, the baseline's mean completion
    is <= D and its mean `late` is <= 1% of transfers.
 2. A stress scenario "stresses" a workflow if its mean completion is >= 10% worse than normal,
    or its mean (late + failed_transfers) > 0. If not, try in order:
      (a) move the event to the link that carries the most baseline bytes during the event
          window in `normal`;
      (b) for a surge, raise extra_load to 1.0 so the link sits at the 0.95 load cap;
      (c) keep the scenario as it was and report "no stress" as a finding.
    data_scale is never raised and nothing harsher is invented.

Usage:
    python scripts/tune.py            # print the tuning table, write results/tuning/tuning.json
    python scripts/tune.py --write    # ...and freeze the chosen values into configs/experiment.yaml
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.baseline import Baseline  # noqa: E402
from att.extract import extract_transfers  # noqa: E402
from att.network import NetEvent  # noqa: E402
from att.simulator import Simulator  # noqa: E402

SCALES = [10, 20, 50, 100, 200, 300, 500, 1000]
STRESS_SCENARIOS = ["congestion", "link_failure"]
OUT = config.ROOT / "results" / "tuning" / "tuning.json"


def make_sim(exp, workflow, events, seed, scale) -> Simulator:
    ex = extract_transfers(config.workflow_path(exp, workflow), exp["sites"], exp["source_site"],
                           exp["slack"], seed=seed, data_scale=scale)
    bg, _ = config.scenarios()
    s = exp["simulator"]
    return Simulator(ex, config.topology(), bg, events, seed, steps_per_deadline=s["steps_per_deadline"],
                     max_time_frac=s["max_time_frac"], timeout_frac=s["timeout_frac"])


def evaluate(exp, workflow, events, scale, seeds) -> dict:
    """Mean baseline metrics over the tuning seeds for one workflow/event list/scale."""
    runs = [make_sim(exp, workflow, events, s, scale).run(Baseline()) for s in seeds]
    D = runs[0]["deadline_D_s"]
    return {
        "completion_over_D": statistics.fmean(r["completion_s"] / D for r in runs),
        "late": statistics.fmean(r["late"] for r in runs),
        "late_frac": statistics.fmean(r["late"] / r["n_transfers"] for r in runs),
        "failed_transfers": statistics.fmean(r["failed_transfers"] for r in runs),
        "completed": sum(r["completed"] for r in runs),
        "n_transfers": statistics.fmean(r["n_transfers"] for r in runs),
        "D": D,
    }


def busiest_link_in_window(exp, workflow, ev: NetEvent, scale, seeds) -> tuple[str, str]:
    """Link carrying the most baseline bytes (summed over seeds) during ev's window in `normal`."""
    topo = config.topology()
    total = [0.0] * len(topo.links)
    for s in seeds:
        sim = make_sim(exp, workflow, [], s, scale)
        sim.count_window = (ev.start_frac * sim.D, ev.end_frac * sim.D)
        sim.run(Baseline())
        total = [a + b for a, b in zip(total, sim.window_bytes)]
    best = max(range(len(total)), key=lambda i: (total[i], -i))  # ties -> earlier link in YAML
    return tuple(topo.links[best].ends)


def stressed(normal: dict, stress: dict) -> bool:
    return (stress["completion_over_D"] >= 1.10 * normal["completion_over_D"]
            or stress["late"] + stress["failed_transfers"] > 0)


def event_dict(ev: NetEvent) -> dict:
    d = {"type": ev.type, "link": list(ev.link), "start_frac": ev.start_frac, "end_frac": ev.end_frac}
    if ev.type == "surge":
        d["extra_load"] = ev.extra_load
    return d


def tune(exp) -> dict:
    seeds = exp["seeds"]["tuning"]
    _, base_scen = config.scenarios()
    report: dict = {"seeds": seeds, "scales": SCALES, "workflows": {}}
    for wf in exp["workflows"]:
        rec: dict = {"scale_sweep": {}, "scenarios": {}, "overrides": {}}
        for scale in SCALES:
            rec["scale_sweep"][scale] = evaluate(exp, wf, [], scale, seeds)
            m = rec["scale_sweep"][scale]
            print(f"{wf:15} scale {scale:5}  normal: completion {m['completion_over_D']:.3f} D, "
                  f"late {m['late']:.1f} ({100 * m['late_frac']:.1f}%)", flush=True)
        ok = [s for s in SCALES if rec["scale_sweep"][s]["completion_over_D"] <= 1.0
              and rec["scale_sweep"][s]["late_frac"] <= 0.01]
        if not ok:
            raise SystemExit(f"no data_scale satisfies the rule for {wf}")
        scale = max(ok)
        rec["data_scale"] = scale
        normal = rec["scale_sweep"][scale]
        print(f"  -> {wf}: data_scale = {scale}")

        for scen in STRESS_SCENARIOS:
            events = list(base_scen[scen])
            attempts = []
            res = evaluate(exp, wf, events, scale, seeds)
            attempts.append({"step": "as configured", "events": [event_dict(e) for e in events], **res,
                             "stressed": stressed(normal, res)})
            final_events = events
            if not attempts[-1]["stressed"]:
                # (a) move the event to the busiest link in its window
                ev = events[0]
                link = busiest_link_in_window(exp, wf, ev, scale, seeds)
                moved = [replace(ev, link=link)]
                res = evaluate(exp, wf, moved, scale, seeds)
                attempts.append({"step": "(a) moved to busiest link", "events": [event_dict(e) for e in moved],
                                 **res, "stressed": stressed(normal, res)})
                final_events = moved
                if not attempts[-1]["stressed"] and ev.type == "surge":
                    # (b) push the surge to the load cap
                    capped = [replace(moved[0], extra_load=1.0)]
                    res = evaluate(exp, wf, capped, scale, seeds)
                    attempts.append({"step": "(b) extra_load 1.0 (load cap)", "events": [event_dict(e) for e in capped],
                                     **res, "stressed": stressed(normal, res)})
                    final_events = capped
                if not attempts[-1]["stressed"]:
                    # (c) keep the original scenario and report it
                    attempts.append({"step": "(c) kept as configured; reported as a finding",
                                     "events": [event_dict(e) for e in events], "stressed": False})
                    final_events = events
            for a in attempts:
                if "completion_over_D" in a:
                    print(f"  {scen:12} {a['step']:32} {a['events'][0]['link']} completion "
                          f"{a['completion_over_D']:.3f} D, late {a['late']:.1f}, failed {a['failed_transfers']:.1f}"
                          f" -> {'stressed' if a['stressed'] else 'NOT stressed'}")
                else:
                    print(f"  {scen:12} {a['step']}")
            rec["scenarios"][scen] = attempts
            if final_events != events:
                rec["overrides"][scen] = {"events": [event_dict(e) for e in final_events]}
        report["workflows"][wf] = rec
    return report


def write_experiment(report: dict, path: Path = config.CONFIGS / "experiment.yaml") -> None:
    """Freeze data_scale (and any scenario overrides) into experiment.yaml, keeping its comments."""
    text = path.read_text()
    for wf, rec in report["workflows"].items():
        text, n = re.subn(rf"(\n  {re.escape(wf)}:\s*\{{[^}}]*data_scale:\s*)[^}}\s]+", rf"\g<1>{rec['data_scale']}", text)
        assert n == 1, wf
    text = re.sub(r"\n# --- scenario overrides from Stage 4 tuning ---.*\Z", "", text, flags=re.S)
    overrides = {wf: rec["overrides"] for wf, rec in report["workflows"].items() if rec["overrides"]}
    if overrides:
        text = text.rstrip("\n") + "\n\n# --- scenario overrides from Stage 4 tuning ---\n" + \
            "scenario_overrides:\n" + "".join(
                f"  {wf}:\n" + "".join(f"    {sc}: {json.dumps(body)}\n" for sc, body in ov.items())
                for wf, ov in overrides.items())
    path.write_text(text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="freeze results into configs/experiment.yaml")
    args = ap.parse_args()
    exp = config.load_experiment()
    report = tune(exp)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=1, sort_keys=False) + "\n")
    print(f"wrote {OUT.relative_to(config.ROOT)}")
    if args.write:
        write_experiment(report)
        print("froze data_scale / overrides into configs/experiment.yaml")


if __name__ == "__main__":
    main()
