"""Network agent (SciNet 2.2.2, 2.2.3): what are the route options, and which links are busy?

Picture the person in the control room watching the highway cameras: for every transfer it looks
up the 3 lowest-delay routes, estimates how long the file would take on each one at today's free
capacity, recommends the fastest route with no closed link, and flags busy links.
"""
from __future__ import annotations

from typing import Any

from att.tool_client import ToolClient


class NetworkAgent:
    name = "network_agent"

    def __init__(self, k_paths: int = 3, busy_threshold: float = 0.3):
        self.k_paths = k_paths
        self.busy_threshold = busy_threshold

    async def assess(self, tc: ToolClient, transfers: list[dict[str, Any]]) -> dict[str, Any]:
        """For each transfer: candidate paths (no down links), estimated seconds on each, and the
        recommended (fastest) one. Also the link state and the list of busy links."""
        tc.agent = self.name
        net = await tc.call("get_network_state")
        busy = [ln["link"] for ln in net["links"]
                if ln["up"] and ln["free_gbps"] < self.busy_threshold * ln["gbps"]]
        down = [ln["link"] for ln in net["links"] if not ln["up"]]
        pairs = sorted({(t["src"], t["dst"]) for t in transfers})
        paths = await tc.call("get_paths_many", pairs=[list(p) for p in pairs], k=self.k_paths, avoid_down=True) if pairs else {}
        items, owners = [], []
        for t in transfers:
            for p in paths.get(f"{t['src']}->{t['dst']}", []):
                items.append({"bytes": t["remaining_bytes"], "path": p})
                owners.append(t["id"])
        ests = await tc.call("estimate_many", items=items) if items else []
        options: dict[str, list[dict[str, Any]]] = {t["id"]: [] for t in transfers}
        for tid, it, e in zip(owners, items, ests):
            options[tid].append({"path": it["path"], "seconds": e["seconds"]})
        recommended = {}
        for tid, opts in options.items():
            usable = [o for o in opts if o["seconds"] is not None]
            if usable:  # fastest; ties go to the lower-delay path (earlier in the list)
                recommended[tid] = min(usable, key=lambda o: o["seconds"])["path"]
        return {"network": net, "busy_links": busy, "down_links": down, "options": options,
                "recommended": recommended}
