"""LLM mode (optional, `mode=llm`): the coordinator asks Claude for the final say.

Everything up to the final decision is the rule-mode pipeline: the workflow and network agents
run, the coordinator builds its drafts / proposed changes and forecasts them, all through MCP tools.
Then, instead of the rule ("best forecast, with a margin" / "the forecast gate"), ONE Claude call
sees both agents' advice and the forecasts and decides:

  initial plan  pick one of the drafts, and optionally flip the priority of a few transfers;
  on an event   apply the coordinator's proposed reroutes, keep the current plan, or choose its own
                route (from the listed options) and priority for affected transfers.

The answer must match a JSON schema; it is validated with `submit_plan`. If the call fails, is
refused, or the answer is unusable, the rule decision is used and the log says so ("fallback").
Every prompt and raw answer is stored in the decision log, so a run can be audited and replayed
exactly without calling the API again.

Why one call per decision instead of letting Claude call the MCP tools itself: LLM mode is capped
at one call per plan and one per event, and a tool-using loop needs one API call per tool round. So the coordinator makes the tool calls and hands Claude their results.
"""
from __future__ import annotations

import json
from typing import Any

from att.agents.coordinator import AgentTeam, _links_of, forecast_key
from att.llm import BudgetExceeded, LLMError, ask_json, digest
from att.planner import Plan
from att.tool_client import ToolClient

SYSTEM = """You are the coordinator of a small team of software agents that plan data transfers for a \
scientific workflow over a simulated research network. Tasks run at different sites; a task can only \
start when its input files have arrived, so late files delay the whole workflow. The goal is to finish \
the workflow as early as possible (and before its deadline), with as few late transfers as possible.

Two other agents have already done the analysis using the network's tools:
- the workflow agent ranked transfers by slack (deadline minus earliest possible arrival; small or \
negative slack = urgent) and suggested priority 2 for the most urgent ones;
- the network agent listed route options for each transfer with estimated times at today's free capacity.
Priority 2 gives a transfer twice the share of a busy link compared with priority 1.

You also get forecasts from simulate_plan. A forecast assumes the network stays exactly as it is now \
(today's free capacity persists, a link that is down stays down forever, a congestion surge never \
ends). That is often wrong: outages and surges usually end. Forecast differences of a few percent are \
within forecast error.

Decide using the information given. Be concise: your "reason" must be one or two plain sentences."""

INITIAL_SCHEMA = {
    "type": "object",
    "properties": {
        "draft": {"type": "string", "enum": ["load-balanced", "fastest-route", "lowest-delay"]},
        "priority_overrides": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"id": {"type": "string"}, "priority": {"type": "integer", "enum": [1, 2]}},
                      "required": ["id", "priority"], "additionalProperties": False},
        },
        "reason": {"type": "string"},
    },
    "required": ["draft", "priority_overrides", "reason"],
    "additionalProperties": False,
}

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["apply_proposal", "keep_current_plan", "custom"]},
        "custom_routes": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"id": {"type": "string"}, "option": {"type": "integer"},
                                     "priority": {"type": "integer", "enum": [1, 2]}},
                      "required": ["id", "option", "priority"], "additionalProperties": False},
        },
        "reason": {"type": "string"},
    },
    "required": ["action", "custom_routes", "reason"],
    "additionalProperties": False,
}

MAX_LISTED = 60  # transfers listed individually in a prompt (most urgent first), to bound cost


def _fc(f: dict[str, Any]) -> dict[str, Any]:
    return {"completes": f["completed"], "completion_s": None if f["completion_s"] is None else round(f["completion_s"], 2),
            "late_transfers": f["late"], "failed_transfers": f["failed_transfers"]}


def _route(path: list[str]) -> str:
    return "-".join(path)


class LLMAgentTeam(AgentTeam):
    """Same agents and tools as AgentTeam; Claude makes the final decision (mode "llm")."""
    mode = "llm"

    async def _review_initial(self, tc: ToolClient, ctx: dict[str, Any]) -> tuple[str, Plan, dict[str, Any]]:
        rule_name = ctx["rule_choice"]
        drafts, forecasts, ranked, todo = ctx["drafts"], ctx["forecasts"], ctx["ranked"], ctx["todo"]
        urgent = sorted((t for t in todo), key=lambda t: (ranked[t["id"]]["slack_s"], t["id"]))[:MAX_LISTED]
        lowest = drafts["lowest-delay"]
        payload = {
            "now_s": ctx["now"],
            "transfers_total": len(todo),
            "network_now": [{"link": _route(ln["link"]), "capacity_gbps": ln["gbps"],
                             "free_gbps": round(ln["free_gbps"], 1), "up": ln["up"]}
                            for ln in ctx["network"]["network"]["links"]],
            "busy_links": [_route(x) for x in ctx["network"]["busy_links"]],
            "drafts": {n: {"forecast": _fc(forecasts[n]),
                           "transfers_not_on_lowest_delay_route": sum(1 for tid, e in d.items() if e["path"] != lowest[tid]["path"])}
                       for n, d in drafts.items()},
            "rule_coordinator_would_choose": rule_name,
            "most_urgent_transfers": [
                {"id": t["id"], "MB": round(t["bytes"] / 1e6, 1), "from": t["src"], "to": t["dst"],
                 "deadline_s": t["deadline_s"], "slack_s": round(ranked[t["id"]]["slack_s"], 2),
                 "suggested_priority": ranked[t["id"]]["priority"]} for t in urgent],
        }
        user = ("Choose the initial transfer plan. Pick one draft. Optionally override the suggested "
                "priority of some listed transfers (leave the list empty to keep the suggestions).\n\n"
                + json.dumps(payload))
        try:
            ans = await ask_json(SYSTEM, user, INITIAL_SCHEMA)
        except BudgetExceeded:
            raise
        except LLMError as e:
            return rule_name, drafts[rule_name], {"mode": "llm", "status": f"fallback: {e}", "prompt": user}
        data = ans["data"]
        name = data["draft"] if data.get("draft") in drafts else rule_name
        plan = {tid: dict(e) for tid, e in drafts[name].items()}
        ignored = []
        for o in data.get("priority_overrides", []):
            if o.get("id") in plan and o.get("priority") in (1, 2):
                plan[o["id"]]["priority"] = o["priority"]
            else:
                ignored.append(o.get("id"))
        review = {"mode": "llm", "status": "ok", "model": ans["model"], "request_id": ans["request_id"],
                  "usage": ans["usage"], "system_sha256": digest(SYSTEM), "prompt": user, "response": ans["raw"],
                  "draft": name, "rule_choice": rule_name, "overrides_applied": len(data.get("priority_overrides", [])) - len(ignored),
                  "overrides_ignored": ignored,
                  "reason": f"[llm] chose the {name} draft (rule would choose {rule_name}): {data.get('reason', '')}"}
        return name, plan, review

    async def _review_event(self, tc: ToolClient, ctx: dict[str, Any]) -> tuple[Plan, bool, dict[str, Any]]:
        event, changes, by_id, ranked, now = ctx["event"], ctx["changes"], ctx["by_id"], ctx["ranked"], ctx["now"]
        rule_apply = forecast_key(ctx["forecast_change"]) <= forecast_key(ctx["forecast_keep"])
        affected = sorted(ctx["affected"], key=lambda t: (ranked[t["id"]]["slack_s"], t["id"]))[:MAX_LISTED]
        options: dict[str, list[list[str]]] = {}
        listed = []
        for t in affected:
            opts = [o["path"] for o in ctx["options"].get(t["id"], [])]
            if t["path"] not in opts:
                opts.append(t["path"])
            options[t["id"]] = opts
            est = {_route(o["path"]): o["seconds"] for o in ctx["options"].get(t["id"], [])}
            listed.append({"id": t["id"], "MB": round(t["remaining_bytes"] / 1e6, 1), "status": t["status"],
                           "slack_s": round(ranked[t["id"]]["slack_s"], 2), "current_route": _route(t["path"]),
                           "proposed_route": _route(changes[t["id"]]["path"]) if t["id"] in changes else None,
                           "suggested_priority": ranked[t["id"]]["priority"],
                           "options": [{"option": i, "route": _route(p),
                                        "est_seconds_now": None if est.get(_route(p)) is None else round(est[_route(p)], 2)}
                                       for i, p in enumerate(opts)]})
        payload = {
            "event": {k: v for k, v in event.items() if k != "seq"},
            "network_now": [{"link": _route(ln["link"]), "free_gbps": round(ln["free_gbps"], 1), "up": ln["up"]}
                            for ln in ctx["network"]["links"]],
            "proposal": {"reroutes": sum(1 for tid, e in changes.items() if e["path"] != by_id[tid]["path"]),
                         "priority_changes": sum(1 for tid, e in changes.items() if e["path"] == by_id[tid]["path"])},
            "forecast_if_proposal_applied": _fc(ctx["forecast_change"]),
            "forecast_if_plan_kept": _fc(ctx["forecast_keep"]),
            "rule_coordinator_would": "apply_proposal" if rule_apply else "keep_current_plan",
            "affected_transfers": listed,
        }
        user = (f"A network event happened: {event['type']}. Decide: apply the coordinator's proposal, keep the "
                "current plan, or choose 'custom' and give a route option and priority for some affected "
                "transfers (others keep the proposal).\n\n" + json.dumps(payload))
        try:
            ans = await ask_json(SYSTEM, user, EVENT_SCHEMA)
        except BudgetExceeded:
            raise
        except LLMError as e:
            return changes, rule_apply, {"mode": "llm", "status": f"fallback: {e}", "prompt": user}
        data = ans["data"]
        action = data.get("action")
        out: Plan = dict(changes)
        ignored = []
        if action == "custom":
            for r in data.get("custom_routes", []):
                opts = options.get(r.get("id"))
                if opts and isinstance(r.get("option"), int) and 0 <= r["option"] < len(opts) and r.get("priority") in (1, 2):
                    out[r["id"]] = {"path": opts[r["option"]], "priority": r["priority"], "start_s": now}
                else:
                    ignored.append(r.get("id"))
            # drop entries that would change nothing
            out = {tid: e for tid, e in out.items()
                   if e["path"] != by_id[tid]["path"] or e["priority"] != by_id[tid]["priority"]}
        apply = action in ("apply_proposal", "custom")
        if action not in ("apply_proposal", "keep_current_plan", "custom"):
            apply, ignored = rule_apply, ["invalid action"]
        review = {"mode": "llm", "status": "ok", "model": ans["model"], "request_id": ans["request_id"],
                  "usage": ans["usage"], "system_sha256": digest(SYSTEM), "prompt": user, "response": ans["raw"],
                  "action": action, "rule_would": "apply_proposal" if rule_apply else "keep_current_plan",
                  "custom_ignored": ignored,
                  "reason": f"[llm] {event['type']}: {action}: {data.get('reason', '')}"}
        moved_links = sorted({_route(list(k)) for e in out.values() for k in _links_of(e["path"])})
        review["routes_used"] = moved_links[:20]
        return out, apply, review
