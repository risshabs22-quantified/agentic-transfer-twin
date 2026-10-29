"""ReplayPlanner: re-run a logged run using only its decision log, with no agent code and no LLM calls.

It hands the simulator the logged initial plan, then at each on_event call the next logged
decision, after checking that the event the simulator is reporting is exactly the one that was
logged (type, seq, time). If the run diverges, it stops with a clear error instead of silently
producing a different run.
"""
from __future__ import annotations

import math
from typing import Any

from att.planner import Plan, Planner


class ReplayMismatch(RuntimeError):
    pass


def _same_t(a: float, b: float) -> bool:
    return a == b or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)


class ReplayPlanner(Planner):
    mode = "replay"

    def __init__(self, entries: list[dict[str, Any]], name: str = "replay"):
        super().__init__()
        self.entries = entries
        self.name = name
        self.pos = 0

    def _next(self, event: dict[str, Any]) -> Plan:
        if self.pos >= len(self.entries):
            raise ReplayMismatch(f"event {event['type']} seq {event['seq']} at t={event['t']} is not in the log "
                                 f"(log has only {len(self.entries)} decisions)")
        e = self.entries[self.pos]
        trig = e["trigger"]
        if trig["type"] != event["type"] or trig["seq"] != event["seq"] or not _same_t(trig["t"], event["t"]):
            raise ReplayMismatch(f"decision {self.pos}: simulator sent {event['type']} seq {event['seq']} at "
                                 f"t={event['t']!r}, log has {trig['type']} seq {trig['seq']} at t={trig['t']!r}")
        for k in ("link", "transfer_id"):
            if trig.get(k) != event.get(k):
                raise ReplayMismatch(f"decision {self.pos}: {k} differs ({event.get(k)} vs logged {trig.get(k)})")
        self.pos += 1
        self.note = {"agent": e.get("agent", "replay"), "saw": e.get("saw", {}),
                     "tool_calls": e.get("tool_calls", []), "reason": e.get("reason", "")}
        return e["decision"]

    def plan(self, transfers: list[dict[str, Any]], view: Any) -> Plan:
        return self._next({"type": "initial_plan", "seq": 0, "t": view.now})

    def on_event(self, event: dict[str, Any], view: Any) -> Plan:
        return self._next(event)

    def finished(self) -> bool:
        """True if every logged decision was used."""
        return self.pos == len(self.entries)


def same_value(a: Any, b: Any) -> bool:
    """Integers/booleans/strings exactly; floats within 1e-9 relative; None only equals None."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool) or (isinstance(a, int) and isinstance(b, int)):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b or math.isclose(a, b, rel_tol=1e-9, abs_tol=0.0)
    return a == b


def replay_run(manifest: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    """Re-run a recorded run from its manifest settings + decision log. Returns the list of
    differences against the manifest's metrics (empty list = exact replay)."""
    from att.experiment import json_metrics
    from att.runner import sim_from_settings

    sim = sim_from_settings(manifest["settings"])
    planner = ReplayPlanner(entries, name=manifest["settings"]["planner"])
    try:
        metrics = json_metrics(sim.run(planner))
    except ReplayMismatch as e:
        return [f"replay diverged: {e}"]
    diffs = [f"{k}: replay {metrics.get(k)!r} vs manifest {v!r}"
             for k, v in manifest["metrics"].items() if not same_value(metrics.get(k), v)]
    if not planner.finished():
        diffs.append(f"only {planner.pos} of {len(entries)} logged decisions were used")
    return diffs
