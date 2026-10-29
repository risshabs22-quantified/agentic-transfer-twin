"""Talk to the twin's MCP server OUT OF PROCESS, over stdio, the way any MCP client would.

Starts `python -m att.mcp_server` (a demo twin: 1000Genome 2ch, normal, seed 0, t = 0), lists its
tools, and calls each one once.

Usage:
    python scripts/mcp_demo_client.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parent.parent


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "att.mcp_server"], cwd=str(ROOT))
    async with Client(params) as client:
        listed = await client.list_tools()
        print("tools:", ", ".join(t.name for t in listed.tools))

        async def call(name: str, args: dict) -> object:
            res = await client.call_tool(name, args)
            assert not res.is_error, res.content
            sc = res.structured_content
            return sc["result"] if isinstance(sc, dict) and set(sc) == {"result"} else sc

        req = await call("get_workflow_requirements", {})
        tr = req["transfers"][0]
        print(f"\nget_workflow_requirements: {len(req['transfers'])} transfers; first: "
              f"{tr['id']} {tr['bytes'] / 1e9:.2f} GB {tr['src']}->{tr['dst']}, deadline {tr['deadline_s']} s")
        net = await call("get_network_state", {})
        print("get_network_state:", ", ".join(f"{'-'.join(ln['link'])} {ln['free_gbps']:.0f}G" for ln in net["links"]))
        paths = await call("get_paths", {"src": "CERN", "dst": "UCSD", "k": 3})
        print("get_paths CERN->UCSD:", paths)
        many = await call("get_paths_many", {"pairs": [["CERN", "ORNL"], ["FNAL", "Caltech"]], "k": 2})
        print("get_paths_many:", json.dumps(many))
        est = await call("estimate_transfer_time", {"bytes": tr["bytes"], "path": tr["path"]})
        print("estimate_transfer_time:", est)
        ests = await call("estimate_many", {"items": [{"bytes": 1e10, "path": p} for p in paths]})
        print("estimate_many (10 GB on each path):", [round(e["seconds"], 3) for e in ests])
        alt = {tr["id"]: {"path": paths[-1] if tr["dst"] == "UCSD" else tr["path"], "priority": 2, "start_s": 0.0}}
        sim = await call("simulate_plan", {"plan": alt})
        print("simulate_plan:", {k: sim[k] for k in ("completed", "completion_s", "late", "failed_transfers")})
        print("submit_plan (valid):", await call("submit_plan", {"plan": alt}))
        bad = {tr["id"]: {"path": ["CERN", "UCSD"], "priority": 3, "start_s": -1}}
        print("submit_plan (invalid):", await call("submit_plan", {"plan": bad}))


if __name__ == "__main__":
    asyncio.run(main())
