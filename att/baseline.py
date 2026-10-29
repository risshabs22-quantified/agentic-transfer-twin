"""The rule-based baselines the agents are compared against.

baseline          -- the reference method: lowest-delay path, everything priority 1, start as
                     soon as the data exists, and never react to anything.
baseline_reroute  -- an ablation: the same, but when a link goes down (or a transfer fails) it
                     moves every unfinished transfer that uses a down link onto the lowest-delay
                     path that avoids the links that are down right now. It ignores congestion
                     and never uses priorities. It answers "isn't this just rerouting?".

Both learn about the network only from the view (the present) and the events they are sent.
"""
from __future__ import annotations

from typing import Any

from att.planner import Plan, Planner


class Baseline(Planner):
    name = "baseline"

    def __init__(self) -> None:
        super().__init__()
        self._paths: dict[tuple[str, str], list[str]] = {}

    def _shortest(self, view: Any, src: str, dst: str) -> list[str]:
        key = (src, dst)
        if key not in self._paths:  # cache: the map itself never changes
            self._paths[key] = view.topology.shortest_path(src, dst)
        return list(self._paths[key])

    def plan(self, transfers: list[dict[str, Any]], view: Any) -> Plan:
        plan = {tr["id"]: {"path": self._shortest(view, tr["src"], tr["dst"]), "priority": 1,
                           "start_s": view.now} for tr in transfers}
        self.note = {"reason": "lowest-delay path for every transfer, priority 1, start when ready",
                     "saw": {"transfers": len(transfers)}}
        return plan

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        self.note = {"reason": "baseline never changes its plan"}
        return {}


class BaselineReroute(Baseline):
    name = "baseline_reroute"

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        if event["type"] not in ("link_down", "transfer_failed"):
            self.note = {"reason": f"ignores {event['type']}"}
            return {}
        topo = view.topology
        down = set(view.down_links())
        changes: Plan = {}
        for tr in view.transfers():
            if tr["status"] in ("sent", "arrived"):
                continue
            if not down.intersection(topo.path_links(tr["path"])):
                continue
            alts = topo.k_shortest_paths(tr["src"], tr["dst"], k=1, avoid=down)
            if alts and alts[0] != tr["path"]:
                changes[tr["id"]] = {"path": alts[0], "priority": tr["priority"], "start_s": view.now}
        self.note = {"saw": {"down_links": [topo.links[i].ends for i in sorted(down)]},
                     "reason": f"moved {len(changes)} unfinished transfer(s) off down links "
                               "to the lowest-delay path that avoids them"}
        return changes
