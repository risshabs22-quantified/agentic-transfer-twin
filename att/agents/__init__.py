"""The agent team: a workflow agent, a network agent, and a coordinator (the team's Planner).

All three use the twin ONLY through MCP tool calls (att/tool_client.py); none of them imports
the simulator, the network model, or the scenario configs.
"""
from att.agents.coordinator import AgentTeam

__all__ = ["AgentTeam"]
