"""Run one experiment run end to end and record it: metrics, decision log, manifest."""
from __future__ import annotations

import json
import math
import platform
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

from att import config
from att.decision_log import write_log
from att.runner import make_planner, run_id, run_settings, sim_from_settings
from att.simulator import SUMMARY_FIELDS

RESULTS = config.ROOT / "results"
PACKAGES = ["networkx", "numpy", "pandas", "matplotlib", "PyYAML", "mcp", "pytest"]


def git_commit() -> str:
    """Commit hash of the code that produced the run (+ "-dirty" if there were uncommitted changes)."""
    try:
        h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=config.ROOT, capture_output=True, text=True,
                           check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "att", "configs", "scripts", "data"],
                               cwd=config.ROOT, capture_output=True, text=True, check=True).stdout.strip()
        return h + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for p in PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = "not installed"
    return out


def json_metrics(m: dict[str, Any]) -> dict[str, Any]:
    """Metrics with NaN -> None so they can be stored as standard JSON."""
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in m.items()}


def execute(settings: dict[str, Any], results_dir: Path = RESULTS, commit: str | None = None) -> dict[str, Any]:
    """Run one configured run, write its log + manifest, and return the manifest."""
    rid = run_id(settings["workflow"], settings["scenario"], settings["seed"], settings["planner"], settings["mode"])
    sim = sim_from_settings(settings)
    planner = make_planner(settings["planner"], params=settings["planner_params"])
    metrics = sim.run(planner)
    log_path = results_dir / "logs" / f"{rid}.jsonl.gz"
    write_log(log_path, rid, sim.decisions)
    manifest = {
        "run_id": rid,
        "settings": settings,
        "metrics": json_metrics(metrics),
        "log": str(log_path.relative_to(results_dir.parent)) if results_dir.parent in log_path.parents else str(log_path),
        "git_commit": commit if commit is not None else git_commit(),
        "versions": versions(),
    }
    mpath = results_dir / "manifests" / f"{rid}.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=1, allow_nan=False) + "\n")
    return manifest


def summary_row(manifest: dict[str, Any]) -> dict[str, Any]:
    s, m = manifest["settings"], manifest["metrics"]
    row = {"workflow": s["workflow"], "scenario": s["scenario"], "seed": s["seed"], "planner": s["planner"],
           "mode": s["mode"]}
    for k in SUMMARY_FIELDS:
        row[k] = m[k]
    return row


def grid(exp: dict[str, Any]) -> list[tuple[str, str, int, str]]:
    """The final experiment: result workflows x scenarios x evaluation seeds x planners, in a fixed order."""
    wfs = [w for w, v in exp["workflows"].items() if v["role"] == "result"]
    return [(w, sc, seed, p) for w in wfs for sc in exp["scenarios"] for seed in exp["seeds"]["evaluation"]
            for p in exp["planners"]]


def settings_for(exp: dict[str, Any], w: str, sc: str, seed: int, p: str) -> dict[str, Any]:
    return run_settings(exp, w, sc, seed, planner=p)
