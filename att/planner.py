from __future__ import annotations

from typing import Any

PlanEntry = dict[str, Any]
Plan = dict[str, PlanEntry]


class Planner:
    name: str = "planner"
    mode: str = "rule"

    def __init__(self) -> None:
        self.note: dict[str, Any] = {}

    def plan(self, transfers: list[dict[str, Any]], view: Any) -> Plan:
        raise NotImplementedError

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        return {}


def validate_entry(tid: str, entry: Any, transfers: dict[str, dict[str, Any]], topo: Any,
                   now: float, finished: set[str] | frozenset[str] = frozenset()) -> str | None:
    if tid not in transfers:
        return "unknown transfer id"
    if tid in finished:
        return "transfer already sent all its bytes"
    if not isinstance(entry, dict):
        return "entry is not an object"
    missing = [k for k in ("path", "priority", "start_s") if k not in entry]
    if missing:
        return f"missing field(s): {', '.join(missing)}"
    tr = transfers[tid]
    path = entry["path"]
    if not isinstance(path, list) or len(path) < 2 or not all(isinstance(s, str) for s in path):
        return "path must be a list of at least two site names"
    if path[0] != tr["src"] or path[-1] != tr["dst"]:
        return f"path must start at {tr['src']} and end at {tr['dst']}"
    if len(set(path)) != len(path):
        return "path is not simple (repeats a site)"
    for u, v in zip(path, path[1:]):
        if not topo.has_link(u, v):
            return f"no link {u}-{v}"
    pr = entry["priority"]
    if isinstance(pr, bool) or pr not in (1, 2) or not isinstance(pr, int):
        return "priority must be 1 or 2"
    st = entry["start_s"]
    if isinstance(st, bool) or not isinstance(st, (int, float)) or st != st:
        return "start_s must be a number"
    if st < now:
        return f"start_s {st} is before now ({now})"
    return None


def validate_plan(plan: Any, transfers: dict[str, dict[str, Any]], topo: Any, now: float,
                  finished: set[str] | frozenset[str] = frozenset()) -> tuple[Plan, dict[str, str]]:
    accepted: Plan = {}
    rejected: dict[str, str] = {}
    if not isinstance(plan, dict):
        return accepted, {"*": "plan is not an object"}
    for tid, entry in plan.items():
        reason = validate_entry(tid, entry, transfers, topo, now, finished)
        if reason is None:
            accepted[tid] = {"path": list(entry["path"]), "priority": int(entry["priority"]),
                             "start_s": float(entry["start_s"])}
        else:
            rejected[str(tid)] = reason
    return accepted, rejected
