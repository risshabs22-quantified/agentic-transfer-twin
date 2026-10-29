"""agentic-transfer-twin: agents plan workflow data transfers over a simulated network (a "twin").

Modules (in pipeline order):
  extract      workflow trace -> transfers with sizes, dependencies, deadlines
  network      synthetic topology, background load, scenario events
  simulator    the twin: runs a plan, reports metrics, takes snapshots
  planner      interface every planner implements + plan validation
  baseline     the rule-based baselines
  tools        tool functions over a read-only view of the twin
  mcp_server   exposes the tools through an MCP server
  tool_client  synchronous wrapper the agents use to call the tools over MCP
  agents/      workflow, network and coordinator agents
  decision_log one JSON line per decision, for audit and replay
  replay       ReplayPlanner: re-runs a logged run without any agent code
"""

__version__ = "0.1.0"
