"""Part 3: expose the tools in att/tools.py through an MCP server (MCP Python SDK 2.x, v2 API).

    build_server(view) -> MCPServer   one tool wrapper per function in att/tools.py

The view is "live": it always shows the twin's present, so one server built at the start of a run
keeps answering correctly as the run moves forward.

Running this module starts a demo server over stdio, on a cheap demo twin (1000Genome 2ch,
`normal` scenario, seed 0, at t = 0 with the baseline's initial plan in place):

    python -m att.mcp_server                                   # stdio (used by scripts/mcp_demo_client.py)
    npx @modelcontextprotocol/inspector python -m att.mcp_server   # browse the tools in the MCP Inspector
"""
from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from att import tools


def build_server(view: Any, name: str = "transfer-twin") -> MCPServer:
    """Register one MCP tool per function in att/tools.py, bound to `view`."""
    mcp = MCPServer(name)

    @mcp.tool()
    def get_workflow_requirements() -> dict[str, Any]:
        """Every transfer the workflow needs: bytes, src, dst, when its data will be ready,
        its deadline (seconds), its current plan entry, and its status right now."""
        return tools.get_workflow_requirements(view)

    @mcp.tool()
    def get_network_state() -> dict[str, Any]:
        """Per link: capacity (Gbps), one-way delay (ms), up/down, free Gbps right now. Plus the clock."""
        return tools.get_network_state(view)

    @mcp.tool()
    def get_paths(src: str, dst: str, k: int = 3, avoid_down: bool = False) -> list[list[str]]:
        """Return up to k simple paths from src to dst, lowest delay first.
        avoid_down=True leaves out paths through links that are down right now."""
        return tools.get_paths(view, src, dst, k, avoid_down)

    @mcp.tool()
    def get_paths_many(pairs: list[list[str]], k: int = 3, avoid_down: bool = False) -> dict[str, list[list[str]]]:
        """Batch get_paths. pairs = [[src, dst], ...]; result keyed by "src->dst"."""
        return tools.get_paths_many(view, pairs, k, avoid_down)

    @mcp.tool()
    def estimate_transfer_time(bytes: float, path: list[str]) -> dict[str, Any]:
        """Seconds to move `bytes` along `path` at the current free capacity of its slowest link,
        plus one-way delay. seconds is null if a link on the path is down."""
        return tools.estimate_transfer_time(view, bytes, path)

    @mcp.tool()
    def estimate_many(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch estimate_transfer_time. items = [{"bytes": b, "path": [...]}, ...]."""
        return tools.estimate_many(view, items)

    @mcp.tool()
    def simulate_plan(plan: dict[str, Any], horizon_s: float | None = None) -> dict[str, Any]:
        """Forecast a plan on a copy of the present network (capacities frozen at today's values,
        down links stay down, no future events). plan = {transfer_id: {path, priority, start_s}}."""
        return tools.simulate_plan(view, plan, horizon_s)

    @mcp.tool()
    def submit_plan(plan: dict[str, Any]) -> dict[str, Any]:
        """Validate a plan: ids exist, paths are simple, start at src, end at dst and use real
        links, priority is 1 or 2, start_s >= now. Returns accepted count and rejection reasons."""
        return tools.submit_plan(view, plan)

    return mcp


def demo_view() -> Any:
    """A cheap demo twin: 1000Genome 2ch, normal, seed 0, at t = 0 with the baseline's plan."""
    from att import config
    from att.baseline import Baseline
    from att.runner import build_sim

    sim = build_sim(config.load_experiment(), "1000genome-2ch", "normal", 0)
    sim.start(Baseline())
    return sim.view()


def __getattr__(name: str) -> Any:
    # The module-level demo server is built lazily, so importing build_server stays cheap.
    if name == "mcp":
        global mcp
        mcp = build_server(demo_view(), name="transfer-twin-demo")
        return mcp
    raise AttributeError(name)


if __name__ == "__main__":
    build_server(demo_view(), name="transfer-twin-demo").run()
