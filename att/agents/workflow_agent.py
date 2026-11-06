from __future__ import annotations

import math
from typing import Any

from att.tool_client import ToolClient

FINISHED = ("sent", "arrived")


class WorkflowAgent:
    name = "workflow_agent"

    def __init__(self, priority_fraction: float = 0.3):
        self.priority_fraction = priority_fraction

    async def rank(self, tc: ToolClient, req: dict[str, Any] | None = None) -> dict[str, Any]:
        tc.agent = self.name
        if req is None:
            req = await tc.call("get_workflow_requirements")
        todo = [t for t in req["transfers"] if t["status"] not in FINISHED]
        pairs = sorted({(t["src"], t["dst"]) for t in todo})
        paths = await tc.call("get_paths_many", pairs=[list(p) for p in pairs], k=1, avoid_down=True) if pairs else {}
        items, index = [], []
        for t in todo:
            p = paths.get(f"{t['src']}->{t['dst']}") or [t["path"]]
            items.append({"bytes": t["remaining_bytes"], "path": p[0]})
            index.append(t)
        ests = await tc.call("estimate_many", items=items) if items else []
        now = req["now"]
        rows = []
        for pos, (t, e) in enumerate(zip(index, ests)):
            secs = e["seconds"] if e["seconds"] is not None else math.inf
            arrival = max(now, t["data_ready_s"]) + secs
            rows.append({"id": t["id"], "slack_s": t["deadline_s"] - arrival, "earliest_arrival_s": arrival, "_pos": pos})
        rows.sort(key=lambda r: (r["slack_s"], r["_pos"]))
        n_urgent = int(round(self.priority_fraction * len(rows)))
        for i, r in enumerate(rows):
            r["priority"] = 2 if i < n_urgent else 1
            r["reason"] = (f"slack {r['slack_s']:.1f} s, in the most urgent {self.priority_fraction:.0%}"
                           if r["priority"] == 2 else f"slack {r['slack_s']:.1f} s")
            del r["_pos"]
        return {"requirements": req, "ranked": rows, "by_id": {r["id"]: r for r in rows}}
