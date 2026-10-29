"""Synchronous wrapper the agents use to call the twin's tools THROUGH MCP.

The simulator is synchronous. Each planner call (plan() or on_event()) runs exactly one
`asyncio.run(...)`, which opens one MCP client session, makes all of that decision's tool calls
inside it, and closes it. Event loops are never nested.

Every call is recorded (tool name, arguments, short result summary) so it can go into the
decision log entry for that decision.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Awaitable, Callable, TypeVar

from mcp import Client

T = TypeVar("T")
MAX_ARG_CHARS = 300  # longer arguments (e.g. a whole plan) are logged as a size + hash


class ToolCallError(RuntimeError):
    pass


def _digest(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True).encode()).hexdigest()[:12]


def summarize_args(args: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in args.items():
        text = json.dumps(v, sort_keys=True)
        if len(text) <= MAX_ARG_CHARS:
            out[k] = v
        else:
            n = len(v) if isinstance(v, (list, dict)) else len(text)
            out[k] = f"<{n} items, sha256 {_digest(v)}>"
    return out


def summarize_result(tool: str, result: Any) -> str:
    """A one-line summary of a tool result, for the decision log."""
    if tool == "simulate_plan":
        c = result.get("completion_s")
        return (f"forecast: completion {c:.3f} s" if c is not None else "forecast: does not complete") + \
            f", late {result.get('late')}, failed {result.get('failed_transfers')}"
    if tool == "submit_plan":
        return f"valid={result['valid']}, accepted {result['accepted']}, rejected {len(result['rejected'])}"
    if tool == "get_network_state":
        down = [ln["link"] for ln in result["links"] if not ln["up"]]
        return f"{len(result['links'])} links, down: {down}"
    if tool == "get_workflow_requirements":
        return f"{len(result['transfers'])} transfers"
    if isinstance(result, list):
        return f"{len(result)} items" if tool != "get_paths" else f"{len(result)} paths"
    if isinstance(result, dict):
        if "seconds" in result:
            s = result["seconds"]
            return f"{s:.3f} s" if s is not None else "path down"
        return f"{len(result)} entries"
    return str(result)[:80]


class ToolClient:
    """Calls tools on an open MCP client session and records each call."""

    def __init__(self, client: Client):
        self._client = client
        self.calls: list[dict[str, Any]] = []

    async def call(self, tool: str, **args: Any) -> Any:
        res = await self._client.call_tool(tool, args)
        if res.is_error:
            text = res.content[0].text if res.content else ""
            raise ToolCallError(f"{tool} failed: {text}")
        sc = res.structured_content
        # Tools that return a list come back wrapped as {"result": [...]}; dicts come back as-is.
        result = sc["result"] if isinstance(sc, dict) and set(sc) == {"result"} else sc
        self.calls.append({"tool": tool, "args": summarize_args(args), "result": summarize_result(tool, result)})
        return result


def run_with_tools(server: Any, fn: Callable[[ToolClient], Awaitable[T]]) -> tuple[T, list[dict[str, Any]]]:
    """Open one MCP session to `server`, run `fn(tool_client)` in it, and return
    (fn's result, the list of recorded tool calls). `server` may be an MCPServer object
    (in-process) or StdioServerParameters (a separate process)."""
    async def main() -> tuple[T, list[dict[str, Any]]]:
        async with Client(server) as client:
            tc = ToolClient(client)
            out = await fn(tc)
            return out, tc.calls
    try:
        return asyncio.run(main())
    except BaseExceptionGroup as group:
        # The MCP client runs inside an anyio task group, which wraps errors in a group.
        # Re-raise the single real error so callers see e.g. ToolCallError directly.
        leaf: BaseException = group
        while isinstance(leaf, BaseExceptionGroup) and len(leaf.exceptions) == 1:
            leaf = leaf.exceptions[0]
        raise leaf from None
