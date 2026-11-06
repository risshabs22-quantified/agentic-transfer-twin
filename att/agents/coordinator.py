from __future__ import annotations

import math
from typing import Any

from att.agents.network_agent import NetworkAgent
from att.agents.workflow_agent import FINISHED, WorkflowAgent
from att.mcp_server import build_server
from att.planner import Plan, Planner
from att.tool_client import ToolClient, run_with_tools


def _key(u: str, v: str) -> tuple[str, str]:
    return (u, v) if u <= v else (v, u)


def _links_of(path: list[str]) -> list[tuple[str, str]]:
    return [_key(u, v) for u, v in zip(path, path[1:])]


def forecast_key(f: dict[str, Any]) -> tuple:
    c = f.get("completion_s")
    return (0 if f.get("completed") else 1, c if c is not None else math.inf, f.get("late", 0),
            f.get("failed_transfers", 0))


class AgentTeam(Planner):
    name = "agents"
    mode = "rule"

    def __init__(self, priority_fraction: float = 0.3, busy_threshold: float = 0.3, k_paths: int = 3,
                 move_margin: float = 0.1, draft_margin: float = 0.0, drafts: str = "all",
                 react: bool = True):
        super().__init__()
        self.react = react
        if not react:
            self.name = "agents_static"
        self.drafts = drafts
        self.workflow_agent = WorkflowAgent(priority_fraction)
        self.network_agent = NetworkAgent(k_paths, busy_threshold)
        self.move_margin = move_margin
        self.draft_margin = draft_margin
        self.params = {"priority_fraction": priority_fraction, "busy_threshold": busy_threshold,
                       "k_paths": k_paths, "move_margin": move_margin, "draft_margin": draft_margin,
                       "drafts": drafts}


    def plan(self, transfers: list[dict[str, Any]], view: Any) -> Plan:
        plan, calls = run_with_tools(build_server(view), self._initial_plan)
        self.note["tool_calls"] = calls
        return plan

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        if not self.react:
            self.note = {"agent": "coordinator", "reason": "ablation: agents_static never reacts to events"}
            return {}
        changes, calls = run_with_tools(build_server(view), lambda tc: self._react(tc, event))
        self.note["tool_calls"] = calls
        return changes


    @staticmethod
    def _free_Bps(net: dict[str, Any]) -> dict[tuple[str, str], float]:
        return {_key(*ln["link"]): (ln["free_gbps"] * 1e9 / 8 if ln["up"] else 0.0) for ln in net["links"]}

    @staticmethod
    def _score(path: list[str], nbytes: float, assigned: dict, free: dict) -> float:
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
        best, best_score = None, math.inf
        for o in opts:
            s = self._score(o["path"], nbytes, assigned, free)
            if s < best_score:
                best, best_score = o["path"], s
        return best

    @staticmethod
    def _order(ids: list[str], ranked: dict[str, dict[str, Any]]) -> list[str]:
        pos = {tid: i for i, tid in enumerate(ids)}
        return sorted(ids, key=lambda t: (-ranked[t]["priority"], ranked[t]["slack_s"], pos[t]))


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
        shortest: Plan = {t["id"]: {"path": (na["options"][t["id"]] or [{"path": t["path"]}])[0]["path"],
                                    "priority": ranked[t["id"]]["priority"], "start_s": now} for t in todo}
        drafts = {"load-balanced": balanced, "fastest-route": fastest, "lowest-delay": shortest}
        if self.drafts != "all":
            drafts = {k: v for k, v in drafts.items() if k in self.drafts.split(",")}

        forecasts = {}
        for name, draft in drafts.items():
            forecasts[name] = await tc.call("simulate_plan", plan=draft)
        name = min(drafts, key=lambda n: (forecast_key(forecasts[n]), list(drafts).index(n)))
        simple = "lowest-delay"
        if name != simple and simple in forecasts and forecasts[simple]["completed"] and forecasts[name]["completed"]:
            if forecasts[name]["completion_s"] > (1 - self.draft_margin) * forecasts[simple]["completion_s"]:
                name = simple
        name, chosen, review = await self._review_initial(
            tc, {"drafts": drafts, "forecasts": forecasts, "rule_choice": name, "ranked": ranked,
                 "todo": todo, "network": na, "now": now})
        check = await tc.call("submit_plan", plan=chosen)
        for tid in check["rejected"]:
            chosen.pop(tid, None)

        n2 = sum(1 for e in chosen.values() if e["priority"] == 2)
        saw = {"transfers": len(todo), "busy_links": na["busy_links"], "down_links": na["down_links"],
               "forecast_completion_s": {n: f["completion_s"] for n, f in forecasts.items()}}
        if review:
            saw["review"] = review
        self.note.update({
            "agent": "coordinator", "saw": saw,
            "reason": review.get("reason") or (f"kept the {name} draft (best forecast: " + ", ".join(
                f"{n} {forecast_key(f)[1]:.1f} s" for n, f in forecasts.items()) +
                f"); {n2} most urgent transfers get priority 2"),
        })
        return chosen

    async def _review_initial(self, tc: ToolClient, ctx: dict[str, Any]) -> tuple[str, Plan, dict[str, Any]]:
        return ctx["rule_choice"], ctx["drafts"][ctx["rule_choice"]], {}

    async def _review_event(self, tc: ToolClient, ctx: dict[str, Any]) -> tuple[Plan, bool, dict[str, Any]]:
        return ctx["changes"], forecast_key(ctx["forecast_change"]) <= forecast_key(ctx["forecast_keep"]), {}


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

        if etype in ("link_down", "transfer_failed"):
            affected = [t for t in todo if uses(t, down)]
        elif etype == "surge_start":
            affected = [t for t in todo if uses(t, {ev_link})]
        elif etype in ("link_up", "surge_end"):
            affected = [t for t in todo if not uses(t, {ev_link})]
        else:
            affected = []

        na = await self.network_agent.assess(tc, affected) if affected else {"options": {}, "busy_links": []}
        tc.agent = "coordinator"

        affected_ids = {t["id"] for t in affected}
        assigned: dict = {}
        for t in todo:
            if t["id"] not in affected_ids:
                self._assign(t["path"], t["remaining_bytes"], assigned)

        changes: Plan = {}
        by_id = {t["id"]: t for t in todo}
        for tid in self._order([t["id"] for t in affected], ranked):
            t = by_id[tid]
            nbytes = t["remaining_bytes"]
            opts = na["options"].get(tid, [])
            if etype in ("link_up", "surge_end"):
                opts = [o for o in opts if ev_link in _links_of(o["path"])] + [{"path": t["path"]}]
            best = self._pick(opts, nbytes, assigned, free) if opts else None
            cur = self._score(t["path"], nbytes, assigned, free)
            new = self._score(best, nbytes, assigned, free) if best else math.inf
            must_move = math.isinf(cur)
            if best and best != t["path"] and (must_move or new < (1 - self.move_margin) * cur):
                path = best
            else:
                path = t["path"]
            self._assign(path, nbytes, assigned)
            if path != t["path"]:
                changes[tid] = {"path": path, "priority": ranked[tid]["priority"], "start_s": now}

        for t in todo:
            p = ranked[t["id"]]["priority"]
            if t["id"] not in changes and p != t["priority"]:
                changes[t["id"]] = {"path": t["path"], "priority": p, "start_s": now}

        moved = sum(1 for tid, e in changes.items() if e["path"] != by_id[tid]["path"])
        saw = {"affected": len(affected), "busy_links": na["busy_links"],
               "down_links": [list(k) for k in sorted(down)]}
        if changes:
            f_new = await tc.call("simulate_plan", plan=changes)
            f_now = await tc.call("simulate_plan", plan={})
            saw.update({"forecast_change_s": f_new["completion_s"], "forecast_keep_s": f_now["completion_s"]})
            changes, apply, review = await self._review_event(
                tc, {"event": event, "affected": affected, "options": na["options"], "changes": changes,
                     "forecast_change": f_new, "forecast_keep": f_now, "by_id": by_id, "ranked": ranked,
                     "now": now, "network": net})
            if review:
                saw["review"] = review
            if not apply:
                self.note.update({"agent": "coordinator", "saw": saw,
                                  "reason": review.get("reason") or (f"{etype}: proposed {moved} reroute(s), but the "
                                                                     "forecast was worse than keeping the plan; no change")})
                return {}
            moved = sum(1 for tid, e in changes.items() if e["path"] != by_id[tid]["path"])
            check = await tc.call("submit_plan", plan=changes)
            for tid in check["rejected"]:
                changes.pop(tid, None)
        rule_reason = (f"{etype}: rerouted {moved} of {len(affected)} affected transfer(s) by projected "
                       f"load; {len(changes) - moved} priority update(s)" if changes else f"{etype}: nothing to change")
        self.note.update({"agent": "coordinator", "saw": saw,
                          "reason": (saw.get("review") or {}).get("reason") or rule_reason})
        return changes
