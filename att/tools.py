from __future__ import annotations

import math
from typing import Any

from att.planner import validate_plan


def _clean(x: Any) -> Any:
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _data_ready_estimate(view: Any, after_task: str | None, tasks: dict[str, dict]) -> float:
    if after_task is None:
        return 0.0
    t = tasks[after_task]
    if t["status"] == "done":
        return t["finish_s"]
    if t["status"] == "running":
        return t["start_s"] + t["runtime_s"]
    return max(view.now, t["earliest_finish_s"])


def get_workflow_requirements(view: Any) -> dict[str, Any]:
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


def get_network_state(view: Any) -> dict[str, Any]:
    links = [{"link": ln["link"], "gbps": ln["gbps"], "ms": ln["ms"], "up": ln["up"],
              "free_gbps": ln["free_gbps"],
              "load": 1.0 - ln["free_gbps"] / ln["gbps"] if ln["up"] else None}
             for ln in view.links()]
    return _clean({"now": view.now, "links": links})


def get_paths(view: Any, src: str, dst: str, k: int = 3, avoid_down: bool = False) -> list[list[str]]:
    avoid = set(view.down_links()) if avoid_down else None
    return view.topology.k_shortest_paths(src, dst, int(k), avoid=avoid)


def get_paths_many(view: Any, pairs: list[list[str]], k: int = 3, avoid_down: bool = False) -> dict[str, list[list[str]]]:
    out: dict[str, list[list[str]]] = {}
    for src, dst in pairs:
        key = f"{src}->{dst}"
        if key not in out:
            out[key] = get_paths(view, src, dst, k, avoid_down)
    return out


def estimate_transfer_time(view: Any, bytes: float, path: list[str]) -> dict[str, Any]:
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
    return [estimate_transfer_time(view, it["bytes"], it["path"]) for it in items]


def simulate_plan(view: Any, plan: dict[str, Any], horizon_s: float | None = None) -> dict[str, Any]:
    m = view.forecast(plan, horizon_s)
    keep = ["completed", "completion_s", "late", "late_arrived", "failed_attempts", "failed_transfers",
            "transfers_arrived", "n_transfers", "end_s", "data_wait_s", "rejected"]
    return _clean({k: m[k] for k in keep})


def submit_plan(view: Any, plan: dict[str, Any]) -> dict[str, Any]:
    accepted, rejected = validate_plan(plan, view.requirements(), view.topology, view.now, view.finished_ids())
    return _clean({"valid": not rejected, "accepted": len(accepted), "rejected": rejected})


TOOL_FUNCTIONS = [get_workflow_requirements, get_network_state, get_paths, get_paths_many,
                  estimate_transfer_time, estimate_many, simulate_plan, submit_plan]
