"""Part 3: the tools agents use, as plain functions over a twin view.

Every tool reveals only the PRESENT: the clock, today's free capacity, which links are up, and the
status of transfers. None of them can see future noise or scheduled events, because the view they
receive doesn't contain any. `simulate_plan` runs a persistence forecast: "if the network stayed
exactly as it is right now, how would this plan play out?"

All inputs and outputs are JSON types (dict, list, str, int, float, bool, None), so the same
functions can be served over MCP unchanged (see att/mcp_server.py). Infinity and NaN are not valid
JSON, so "never" / "unknown" are returned as None.

The "SciNet task" next to each tool is the task in the SciNet plan it corresponds to.
"""
from __future__ import annotations

import math
from typing import Any

from att.planner import validate_plan


def _clean(x: Any) -> Any:
    """Make a value JSON-safe: NaN/inf -> None, tuples -> lists, recursively."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _data_ready_estimate(view: Any, after_task: str | None, tasks: dict[str, dict]) -> float:
    """Best present estimate of when a transfer's data will exist at its source.

    raw input -> 0; producer done -> its finish time; producer running -> start + runtime;
    producer not started -> the later of now and its critical-path earliest finish.
    Task runtimes come from the workflow trace (workflow knowledge, not network knowledge).
    """
    if after_task is None:
        return 0.0
    t = tasks[after_task]
    if t["status"] == "done":
        return t["finish_s"]
    if t["status"] == "running":
        return t["start_s"] + t["runtime_s"]
    return max(view.now, t["earliest_finish_s"])


# ------------------------------------------------------------------------------------------------
# SciNet 1.1.3 -- workflow requirements
# ------------------------------------------------------------------------------------------------

def get_workflow_requirements(view: Any) -> dict[str, Any]:
    """Every transfer the workflow needs: size, source, destination, readiness, deadline, status.

    `data_ready_s` is the best present estimate of when the data will exist at the source.
    """
    tasks = view.tasks()
    out = []
    for tr in view.transfers():
        out.append({
            "id": tr["id"], "file": tr["file"], "bytes": tr["bytes"], "src": tr["src"], "dst": tr["dst"],
            "after_task": tr["after_task"], "deadline_s": tr["deadline_s"],
            "data_ready_s": _data_ready_estimate(view, tr["after_task"], tasks),
            "ready": tr["ready"], "status": tr["status"], "remaining_bytes": tr["remaining_bytes"],
            "failed_attempts": tr["failed_attempts"],
            "path": tr["path"], "priority": tr["priority"], "start_s": tr["start_s"],
        })
    return _clean({"now": view.now, "workflow_deadline_s": view.deadline_s, "transfers": out})


# ------------------------------------------------------------------------------------------------
# SciNet 3.1.5 -- network state
# ------------------------------------------------------------------------------------------------

def get_network_state(view: Any) -> dict[str, Any]:
    """Per link: capacity, free Gbps right now, up/down. Plus the current time."""
    links = [{"link": ln["link"], "gbps": ln["gbps"], "ms": ln["ms"], "up": ln["up"],
              "free_gbps": ln["free_gbps"],
              "load": 1.0 - ln["free_gbps"] / ln["gbps"] if ln["up"] else None}
             for ln in view.links()]
    return _clean({"now": view.now, "links": links})


# ------------------------------------------------------------------------------------------------
# SciNet 2.2.3 -- path options
# ------------------------------------------------------------------------------------------------

def get_paths(view: Any, src: str, dst: str, k: int = 3, avoid_down: bool = False) -> list[list[str]]:
    """Up to k simple paths from src to dst, lowest total delay first.

    With avoid_down=True, paths through links that are down right now are left out.
    """
    avoid = set(view.down_links()) if avoid_down else None
    return view.topology.k_shortest_paths(src, dst, int(k), avoid=avoid)


def get_paths_many(view: Any, pairs: list[list[str]], k: int = 3, avoid_down: bool = False) -> dict[str, list[list[str]]]:
    """Batch version of get_paths. `pairs` is [[src, dst], ...]; result keys are "src->dst"."""
    out: dict[str, list[list[str]]] = {}
    for src, dst in pairs:
        key = f"{src}->{dst}"
        if key not in out:
            out[key] = get_paths(view, src, dst, k, avoid_down)
    return out


# ------------------------------------------------------------------------------------------------
# SciNet 1.3.4 -- simple performance estimate
# ------------------------------------------------------------------------------------------------

def estimate_transfer_time(view: Any, bytes: float, path: list[str]) -> dict[str, Any]:
    """Seconds to move `bytes` along `path` at the current free capacity of its slowest link,
    plus the path's one-way delay. Ignores sharing with other transfers (a lower bound).
    `seconds` is None if a link on the path is down right now."""
    topo = view.topology
    links = view.links()
    idx = topo.path_links(path)
    free = [links[i]["free_Bps"] for i in idx]
    delay = topo.path_delay_s(path)
    bottleneck = min(free)
    down = [links[i]["link"] for i in idx if not links[i]["up"]]
    seconds = (bytes / bottleneck + delay) if bottleneck > 0 else None
    return _clean({"seconds": seconds, "bottleneck_free_gbps": bottleneck * 8 / 1e9,
                   "delay_s": delay, "down_links": down})


def estimate_many(view: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Batch version of estimate_transfer_time. `items` is [{"bytes": b, "path": [...]}, ...]."""
    return [estimate_transfer_time(view, it["bytes"], it["path"]) for it in items]


# ------------------------------------------------------------------------------------------------
# SciNet 3.1.5 -- what-if simulation on the twin
# ------------------------------------------------------------------------------------------------

def simulate_plan(view: Any, plan: dict[str, Any], horizon_s: float | None = None) -> dict[str, Any]:
    """Run `plan` (changed entries only; everything else keeps its current entry) on a
    persistence-forecast copy of the present: free capacities stay as they are now, down links
    stay down, and there is no future noise or event. Returns the forecast run's metrics."""
    m = view.forecast(plan, horizon_s)
    keep = ["completed", "completion_s", "late", "late_arrived", "failed_attempts", "failed_transfers",
            "transfers_arrived", "n_transfers", "end_s", "data_wait_s", "rejected"]
    return _clean({k: m[k] for k in keep})


# ------------------------------------------------------------------------------------------------
# SciNet 3.2.4 -- plan validation
# ------------------------------------------------------------------------------------------------

def submit_plan(view: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a plan against the present (same rules as the simulator). The planner then returns
    the plan to the simulator, which validates it again before applying it."""
    accepted, rejected = validate_plan(plan, view.requirements(), view.topology, view.now, view.finished_ids())
    return _clean({"valid": not rejected, "accepted": len(accepted), "rejected": rejected})


TOOL_FUNCTIONS = [get_workflow_requirements, get_network_state, get_paths, get_paths_many,
                  estimate_transfer_time, estimate_many, simulate_plan, submit_plan]
