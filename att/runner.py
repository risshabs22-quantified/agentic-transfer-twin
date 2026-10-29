"""Build and run one experiment run: (workflow, scenario, seed, planner)."""
from __future__ import annotations

from typing import Any

from att import config
from att.extract import extract_transfers
from att.planner import Planner
from att.simulator import Simulator


def run_id(workflow: str, scenario: str, seed: int, planner: str, mode: str = "rule") -> str:
    rid = f"{workflow}__{scenario}__seed{seed}__{planner}"
    return rid if mode == "rule" else f"{rid}__{mode}"


def build_sim(exp: dict[str, Any], workflow: str, scenario: str, seed: int,
              data_scale: float | None = None) -> Simulator:
    """Create the simulator for one run. The seed drives task placement AND network noise,
    and is the same for every planner, so planners are compared on identical conditions."""
    wf = exp["workflows"][workflow]
    scale = data_scale if data_scale is not None else wf["data_scale"]
    if scale is None:
        raise ValueError(f"data_scale for {workflow} is not set (run scripts/tune.py)")
    ex = extract_transfers(config.workflow_path(exp, workflow), exp["sites"], exp["source_site"],
                           exp["slack"], seed=seed, data_scale=scale)
    topo = config.topology()
    bg, _ = config.scenarios()
    events = config.scenario_events(exp, workflow, scenario)
    s = exp["simulator"]
    return Simulator(ex, topo, bg, events, seed, steps_per_deadline=s["steps_per_deadline"],
                     max_time_frac=s["max_time_frac"], timeout_frac=s["timeout_frac"])


def run_one(exp: dict[str, Any], workflow: str, scenario: str, seed: int, planner: Planner,
            data_scale: float | None = None) -> tuple[dict[str, Any], Simulator]:
    sim = build_sim(exp, workflow, scenario, seed, data_scale)
    return sim.run(planner), sim
