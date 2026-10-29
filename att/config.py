"""Load the YAML configs into plain Python objects, resolving paths relative to the repo root."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from att.network import Background, NetEvent, Topology, load_scenarios, load_topology, parse_event

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"


def load_experiment(path: str | Path = CONFIGS / "experiment.yaml") -> dict[str, Any]:
    with open(path) as fh:
        return yaml.safe_load(fh)


def topology(path: str | Path = CONFIGS / "topology.yaml") -> Topology:
    return load_topology(path)


def scenarios(path: str | Path = CONFIGS / "scenarios.yaml") -> tuple[Background, dict[str, list[NetEvent]]]:
    return load_scenarios(path)


def scenario_events(exp: dict[str, Any], workflow: str, scenario: str,
                    path: str | Path = CONFIGS / "scenarios.yaml") -> list[NetEvent]:
    """Events for (workflow, scenario): the shared scenario, unless network tuning (scripts/tune.py) recorded a
    per-workflow override in experiment.yaml under `scenario_overrides`."""
    _, all_events = load_scenarios(path)
    override = (exp.get("scenario_overrides") or {}).get(workflow, {}).get(scenario)
    if override is not None:
        return [parse_event(e) for e in override["events"]]
    return all_events[scenario]


def workflow_path(exp: dict[str, Any], workflow: str) -> Path:
    return ROOT / exp["workflows"][workflow]["file"]
