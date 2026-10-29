"""Build and run one experiment run: (workflow, scenario, seed, planner).

Every run is described by a self-contained `settings` dict (workflow file + its sha256, sites,
slack, data_scale, the scenario's events, the background model, the whole topology, simulator
settings, planner name and parameters). The same dict is stored in the run's manifest, and
`sim_from_settings` rebuilds the identical simulator from it -- that is how replay works.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from typing import Any

from att import config
from att.extract import extract_transfers
from att.network import Background, Link, Topology, parse_event
from att.planner import Planner
from att.simulator import Simulator


def run_id(workflow: str, scenario: str, seed: int, planner: str, mode: str = "rule") -> str:
    rid = f"{workflow}__{scenario}__seed{seed}__{planner}"
    return rid if mode == "rule" else f"{rid}__{mode}"


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_settings(exp: dict[str, Any], workflow: str, scenario: str, seed: int, planner: str = "baseline",
                 data_scale: float | None = None) -> dict[str, Any]:
    """Everything needed to rebuild this run exactly, as plain JSON data."""
    wf = exp["workflows"][workflow]
    scale = data_scale if data_scale is not None else wf["data_scale"]
    if scale is None:
        raise ValueError(f"data_scale for {workflow} is not set (run scripts/tune.py)")
    topo = config.topology()
    bg, _ = config.scenarios()
    events = config.scenario_events(exp, workflow, scenario)
    path = config.workflow_path(exp, workflow)
    return {
        "workflow": workflow,
        "workflow_file": wf["file"],
        "workflow_sha256": _sha256(path),
        "scenario": scenario,
        "seed": seed,
        "planner": planner,
        "mode": "rule",
        "planner_params": dict(exp["agents"]) if planner == "agents" else {},
        "sites": list(exp["sites"]),
        "source_site": exp["source_site"],
        "slack": exp["slack"],
        "data_scale": scale,
        "simulator": dict(exp["simulator"]),
        "background": asdict(bg),
        "events": [{"type": e.type, "link": list(e.link), "start_frac": e.start_frac, "end_frac": e.end_frac,
                    **({"extra_load": e.extra_load} if e.type == "surge" else {})} for e in events],
        "topology": {"sites": topo.sites,
                     "links": [{"a": ln.a, "b": ln.b, "gbps": ln.gbps, "ms": ln.ms} for ln in topo.links]},
    }


def sim_from_settings(s: dict[str, Any]) -> Simulator:
    """Rebuild a run's simulator from its settings dict alone."""
    path = config.ROOT / s["workflow_file"]
    if _sha256(path) != s["workflow_sha256"]:
        raise ValueError(f"{s['workflow_file']} has changed since this run was recorded")
    ex = extract_transfers(path, s["sites"], s["source_site"], s["slack"], seed=s["seed"], data_scale=s["data_scale"])
    topo = Topology(sites=list(s["topology"]["sites"]),
                    links=[Link(x["a"], x["b"], float(x["gbps"]), float(x["ms"])) for x in s["topology"]["links"]])
    events = [parse_event(e) for e in s["events"]]
    sim_cfg = s["simulator"]
    return Simulator(ex, topo, Background(**s["background"]), events, s["seed"],
                     steps_per_deadline=sim_cfg["steps_per_deadline"], max_time_frac=sim_cfg["max_time_frac"],
                     timeout_frac=sim_cfg["timeout_frac"])


def build_sim(exp: dict[str, Any], workflow: str, scenario: str, seed: int,
              data_scale: float | None = None) -> Simulator:
    """Create the simulator for one run. The seed drives task placement AND network noise,
    and is the same for every planner, so planners are compared on identical conditions."""
    return sim_from_settings(run_settings(exp, workflow, scenario, seed, data_scale=data_scale))


def make_planner(name: str, exp: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Planner:
    """Build a planner by name. Agent parameters come from `params`, else experiment.yaml."""
    from att.agents import AgentTeam
    from att.baseline import Baseline, BaselineReroute
    if name == "baseline":
        return Baseline()
    if name == "baseline_reroute":
        return BaselineReroute()
    if name == "agents":
        return AgentTeam(**(params if params is not None else exp["agents"]))
    raise ValueError(f"unknown planner {name!r}")


def run_one(exp: dict[str, Any], workflow: str, scenario: str, seed: int, planner: Planner,
            data_scale: float | None = None) -> tuple[dict[str, Any], Simulator]:
    sim = build_sim(exp, workflow, scenario, seed, data_scale)
    return sim.run(planner), sim
