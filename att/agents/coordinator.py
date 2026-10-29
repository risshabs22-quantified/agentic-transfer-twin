"""Coordinator (SciNet 2.2.6): turns the two agents' advice into one plan. It is the team's Planner.

Picture the shift supervisor in the airport control room. The workflow agent says who is urgent;
the network agent says which routes exist and how fast they are right now. The supervisor:

  Initial plan
    1. ranks transfers by (priority 2 first, then least slack);
    2. walks down that list and gives each transfer the route (among its top 3, none down) with
       the lowest PROJECTED BOTTLENECK LOAD: for each link, (bytes already assigned to it + this
       transfer's bytes) / the link's free bytes per second; the route's score is its worst link.
       This spreads big transfers over parallel routes instead of piling them on one;
    3. also builds the plain network-agent draft (everyone on their individually fastest route);
    4. forecasts both with simulate_plan and keeps the better one
       (completion time, then late transfers, then failed transfers);
    5. checks it with submit_plan.

  On events (re-plans only the transfers the event affects)
    link_down / transfer_failed  move unfinished transfers off down links, spreading them over
                                 the remaining routes by projected load;
    surge_start                  move transfers off the surged link when another route is
                                 projected faster (priority 2 first);
    link_up / surge_end          move transfers back onto the restored link if that is faster.
    Every event also refreshes priorities (slack changes as time passes).
    The change is kept only if a simulate_plan forecast says it is no worse than doing nothing.

Everything the coordinator knows comes from MCP tool calls; it never touches the simulator.
"""
from __future__ import annotations

import math
from typing import Any

from att.agents.network_agent import NetworkAgent
from att.agents.workflow_agent import FINISHED, WorkflowAgent
from att.mcp_server import build_server
from att.planner import Plan, Planner
from att.tool_client import ToolClient, run_with_tools


def _key(u: str, v: str) -> tuple[str, str]:
    """Undirected link key (alphabetical order, so A-B and B-A are the same link)."""
    return (u, v) if u <= v else (v, u)


def _links_of(path: list[str]) -> list[tuple[str, str]]:
    return [_key(u, v) for u, v in zip(path, path[1:])]


def forecast_key(f: dict[str, Any]) -> tuple:
    """Order forecasts: completes first, then earlier completion, fewer late, fewer failed."""
    c = f.get("completion_s")
    return (0 if f.get("completed") else 1, c if c is not None else math.inf, f.get("late", 0),
            f.get("failed_transfers", 0))


class AgentTeam(Planner):
    """The agents' Planner (name "agents", mode "rule")."""
    name = "agents"
    mode = "rule"

    def __init__(self, priority_fraction: float = 0.3, busy_threshold: float = 0.3, k_paths: int = 3,
                 move_margin: float = 0.1, draft_margin: float = 0.0, drafts: str = "all"):
        super().__init__()
        self.drafts = drafts  # "all", or a comma list of draft names to consider (for ablations)
        self.workflow_agent = WorkflowAgent(priority_fraction)
        self.network_agent = NetworkAgent(k_paths, busy_threshold)
        self.move_margin = move_margin  # move a transfer only if projected >= this much faster
        # Forecasts are only persistence guesses, so leave the simple lowest-delay plan only when
        # another draft is forecast at least this fraction faster.
        self.draft_margin = draft_margin
        self.params = {"priority_fraction": priority_fraction, "busy_threshold": busy_threshold,
                       "k_paths": k_paths, "move_margin": move_margin, "draft_margin": draft_margin,
                       "drafts": drafts}

    # ------------------------------------------------------------------ Planner interface

    def plan(self, transfers: list[dict[str, Any]], view: Any) -> Plan:
        plan, calls = run_with_tools(build_server(view), self._initial_plan)
        self.note["tool_calls"] = calls
        return plan

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        changes, calls = run_with_tools(build_server(view), lambda tc: self._react(tc, event))
        self.note["tool_calls"] = calls
        return changes

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _free_Bps(net: dict[str, Any]) -> dict[tuple[str, str], float]:
        return {_key(*ln["link"]): (ln["free_gbps"] * 1e9 / 8 if ln["up"] else 0.0) for ln in net["links"]}

    @staticmethod
    def _score(path: list[str], nbytes: float, assigned: dict, free: dict) -> float:
        """Projected bottleneck load of putting nbytes on path: worst link's (assigned + nbytes) / free."""
        worst = 0.0
        for k in _links_of(path):
            if free[k] <= 0:
                return math.inf
            worst = max(worst, (assigned.get(k, 0.0) + nbytes) / free[k])
        return worst

    @staticmethod
    def _assign(path: list[str], nbytes: float, assigned: dict) -> None:
        for k in _links_of(path):
            assigned[k] = assigned.get(k, 0.0) + nbytes

    def _pick(self, opts: list[dict[str, Any]], nbytes: float, assigned: dict, free: dict) -> list[str] | None:
        """Lowest projected bottleneck load among the options (ties -> lower delay = earlier)."""
        best, best_score = None, math.inf
        for o in opts:
            s = self._score(o["path"], nbytes, assigned, free)
            if s < best_score:
                best, best_score = o["path"], s
        return best

    @staticmethod
    def _order(ids: list[str], ranked: dict[str, dict[str, Any]]) -> list[str]:
        """Priority 2 first, then least slack; ties keep the given (workflow) order."""
        pos = {tid: i for i, tid in enumerate(ids)}
        return sorted(ids, key=lambda t: (-ranked[t]["priority"], ranked[t]["slack_s"], pos[t]))

    # ------------------------------------------------------------------ initial plan

    async def _initial_plan(self, tc: ToolClient) -> Plan:
        wf = await self.workflow_agent.rank(tc)
        req, ranked = wf["requirements"], wf["by_id"]
        todo = [t for t in req["transfers"] if t["status"] not in FINISHED]
        na = await self.network_agent.assess(tc, todo)
        tc.agent = "coordinator"
        now, free = req["now"], self._free_Bps(na["network"])
        by_id = {t["id"]: t for t in todo}

        balanced: Plan = {}
        assigned: dict = {}
        for tid in self._order([t["id"] for t in todo], ranked):
            t = by_id[tid]
            path = self._pick(na["options"][tid], t["remaining_bytes"], assigned, free) or t["path"]
            self._assign(path, t["remaining_bytes"], assigned)
            balanced[tid] = {"path": path, "priority": ranked[tid]["priority"], "start_s": now}
        fastest: Plan = {t["id"]: {"path": na["recommended"].get(t["id"], t["path"]),
                                   "priority": ranked[t["id"]]["priority"], "start_s": now} for t in todo}
        # the simple option: every transfer on its lowest-delay route that is up (plus priorities)
        shortest: Plan = {t["id"]: {"path": (na["options"][t["id"]] or [{"path": t["path"]}])[0]["path"],
                                    "priority": ranked[t["id"]]["priority"], "start_s": now} for t in todo}
        drafts = {"load-balanced": balanced, "fastest-route": fastest, "lowest-delay": shortest}
        if self.drafts != "all":
            drafts = {k: v for k, v in drafts.items() if k in self.drafts.split(",")}

        forecasts = {}
        for name, draft in drafts.items():
            forecasts[name] = await tc.call("simulate_plan", plan=draft)
        # best forecast wins; ties go to the earlier draft in the list above
        name = min(drafts, key=lambda n: (forecast_key(forecasts[n]), list(drafts).index(n)))
        simple = "lowest-delay"
        if name != simple and simple in forecasts and forecasts[simple]["completed"] and forecasts[name]["completed"]:
            if forecasts[name]["completion_s"] > (1 - self.draft_margin) * forecasts[simple]["completion_s"]:
                name = simple  # the gain is within forecast error: keep the simple plan
        chosen = drafts[name]
        check = await tc.call("submit_plan", plan=chosen)
        for tid in check["rejected"]:  # never expected; keep the plan safe anyway
            chosen.pop(tid, None)

        n2 = sum(1 for e in chosen.values() if e["priority"] == 2)
        self.note.update({
            "agent": "coordinator",
            "saw": {"transfers": len(todo), "busy_links": na["busy_links"], "down_links": na["down_links"],
                    "forecast_completion_s": {n: f["completion_s"] for n, f in forecasts.items()}},
            "reason": f"kept the {name} draft (best forecast: " + ", ".join(
                f"{n} {forecast_key(f)[1]:.1f} s" for n, f in forecasts.items()) +
                f"); {n2} most urgent transfers get priority 2",
        })
        return chosen

    # ------------------------------------------------------------------ events

    async def _react(self, tc: ToolClient, event: dict[str, Any]) -> Plan:
        etype = event["type"]
        wf = await self.workflow_agent.rank(tc)
        req, ranked = wf["requirements"], wf["by_id"]
        todo = [t for t in req["transfers"] if t["status"] not in FINISHED]
        tc.agent = "coordinator"
        net = await tc.call("get_network_state")
        free, now = self._free_Bps(net), req["now"]
        down = {k for k, f in free.items() if f <= 0}
        ev_link = _key(*event["link"]) if "link" in event else None

        def uses(t: dict[str, Any], keys: set) -> bool:
            return bool(keys.intersection(_links_of(t["path"])))

        # 1. which transfers does this event affect?
        if etype in ("link_down", "transfer_failed"):
            affected = [t for t in todo if uses(t, down)]
        elif etype == "surge_start":
            affected = [t for t in todo if uses(t, {ev_link})]
        elif etype in ("link_up", "surge_end"):
            affected = [t for t in todo if not uses(t, {ev_link})]  # candidates to move back
        else:
            affected = []

        na = await self.network_agent.assess(tc, affected) if affected else {"options": {}, "busy_links": []}
        tc.agent = "coordinator"

        # 2. bytes already committed to each link by the transfers we are NOT moving
        affected_ids = {t["id"] for t in affected}
        assigned: dict = {}
        for t in todo:
            if t["id"] not in affected_ids:
                self._assign(t["path"], t["remaining_bytes"], assigned)

        # 3. re-route affected transfers, most urgent first, spreading them by projected load
        changes: Plan = {}
        by_id = {t["id"]: t for t in todo}
        for tid in self._order([t["id"] for t in affected], ranked):
            t = by_id[tid]
            nbytes = t["remaining_bytes"]
            opts = na["options"].get(tid, [])
            if etype in ("link_up", "surge_end"):
                # only routes that use the restored link are new options
                opts = [o for o in opts if ev_link in _links_of(o["path"])] + [{"path": t["path"]}]
            best = self._pick(opts, nbytes, assigned, free) if opts else None
            cur = self._score(t["path"], nbytes, assigned, free)
            new = self._score(best, nbytes, assigned, free) if best else math.inf
            must_move = math.isinf(cur)  # current route has a down link
            if best and best != t["path"] and (must_move or new < (1 - self.move_margin) * cur):
                path = best
            else:
                path = t["path"]
            self._assign(path, nbytes, assigned)
            if path != t["path"]:
                changes[tid] = {"path": path, "priority": ranked[tid]["priority"], "start_s": now}

        # 4. refresh priorities (slack changes as time passes)
        for t in todo:
            p = ranked[t["id"]]["priority"]
            if t["id"] not in changes and p != t["priority"]:
                changes[t["id"]] = {"path": t["path"], "priority": p, "start_s": now}

        # 5. keep the change only if the forecast says it is no worse than doing nothing
        moved = sum(1 for tid, e in changes.items() if e["path"] != by_id[tid]["path"])
        saw = {"affected": len(affected), "busy_links": na["busy_links"],
               "down_links": [list(k) for k in sorted(down)]}
        if changes:
            f_new = await tc.call("simulate_plan", plan=changes)
            f_now = await tc.call("simulate_plan", plan={})
            saw.update({"forecast_change_s": f_new["completion_s"], "forecast_keep_s": f_now["completion_s"]})
            if forecast_key(f_new) > forecast_key(f_now):
                self.note.update({"agent": "coordinator", "saw": saw,
                                  "reason": f"{etype}: proposed {moved} reroute(s), but the forecast "
                                            "was worse than keeping the plan; no change"})
                return {}
            check = await tc.call("submit_plan", plan=changes)
            for tid in check["rejected"]:
                changes.pop(tid, None)
        self.note.update({
            "agent": "coordinator", "saw": saw,
            "reason": f"{etype}: rerouted {moved} of {len(affected)} affected transfer(s) by projected "
                      f"load; {len(changes) - moved} priority update(s)" if changes else f"{etype}: nothing to change",
        })
        return changes
