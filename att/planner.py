"""The interface every planner implements, and the plan validation shared by the simulator
and the `submit_plan` tool.

A plan is a dict keyed by transfer id:

    {"<transfer_id>": {"path": ["CERN", "StarLight", "Caltech"], "priority": 1, "start_s": 0.0}, ...}

  path      -- the sites the transfer goes through, from its src to its dst
  priority  -- 1 (normal) or 2 (gets twice the share of a busy link)
  start_s   -- don't start before this time (seconds); it can still wait longer for its producer
"""
from __future__ import annotations

from typing import Any

PlanEntry = dict[str, Any]
Plan = dict[str, PlanEntry]


class Planner:
    """Base class. Subclasses override plan() and, if they react to events, on_event().

    `note` is a scratch dict the simulator clears before every call and reads after it. A planner
    can put "agent", "saw", "tool_calls" and "reason" in it; they go into the decision log.
    """
    name: str = "planner"
    mode: str = "rule"

    def __init__(self) -> None:
        self.note: dict[str, Any] = {}

    def plan(self, transfers: list[dict[str, Any]], view: Any) -> Plan:
        """Return {transfer_id: {"path": [sites...], "priority": 1 or 2, "start_s": float}}."""
        raise NotImplementedError

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        """Return changed entries in the same shape, or {}."""
        return {}


def validate_entry(tid: str, entry: Any, transfers: dict[str, dict[str, Any]], topo: Any,
                   now: float, finished: set[str] | frozenset[str] = frozenset()) -> str | None:
    """Check one plan entry. Returns None if it is valid, otherwise a short reason.

    Rules: the transfer exists; the path is simple, starts at src, ends at
    dst and uses only existing links; priority is 1 or 2; start_s >= now. One extra rule: an
    entry for a transfer that has already sent all its bytes is rejected, because changing it
    would have no effect and would make "reroutes" counts misleading.
    """
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
    if isinstance(st, bool) or not isinstance(st, (int, float)) or st != st:  # st != st catches NaN
        return "start_s must be a number"
    if st < now:
        return f"start_s {st} is before now ({now})"
    return None


def validate_plan(plan: Any, transfers: dict[str, dict[str, Any]], topo: Any, now: float,
                  finished: set[str] | frozenset[str] = frozenset()) -> tuple[Plan, dict[str, str]]:
    """Split a plan into (accepted entries, {transfer_id: rejection reason})."""
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
