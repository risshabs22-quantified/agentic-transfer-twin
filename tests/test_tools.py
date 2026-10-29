"""Tools work directly, in-process over MCP, and over stdio; simulate_plan can't see the future."""
import json
import sys

import pytest
from mcp import StdioServerParameters

from att import config, tools
from att.baseline import Baseline
from att.mcp_server import build_server
from att.runner import build_sim
from att.tool_client import run_with_tools
from tests.helpers import ROOT

EXP = config.load_experiment()


def started(scenario="normal", seed=0, workflow="1000genome-2ch"):
    sim = build_sim(EXP, workflow, scenario, seed)
    sim.start(Baseline())
    return sim


async def call_every_tool(tc):
    out = {}
    req = await tc.call("get_workflow_requirements")
    tr = req["transfers"][0]
    out["req"] = req
    out["net"] = await tc.call("get_network_state")
    out["paths"] = await tc.call("get_paths", src="CERN", dst="UCSD", k=3)
    out["many"] = await tc.call("get_paths_many", pairs=[["CERN", "ORNL"], ["CERN", "UCSD"]], k=2)
    out["est"] = await tc.call("estimate_transfer_time", bytes=tr["bytes"], path=tr["path"])
    out["ests"] = await tc.call("estimate_many", items=[{"bytes": 1e9, "path": p} for p in out["paths"]])
    out["sim"] = await tc.call("simulate_plan", plan={})
    out["submit"] = await tc.call("submit_plan", plan={tr["id"]: {"path": tr["path"], "priority": 2, "start_s": 0.0}})
    out["bad"] = await tc.call("submit_plan", plan={tr["id"]: {"path": tr["path"], "priority": 5, "start_s": 0.0}})
    return out


def check_results(out):
    assert len(out["req"]["transfers"]) > 0
    assert len(out["net"]["links"]) == 7 and all(ln["up"] for ln in out["net"]["links"])
    assert out["paths"][0] == ["CERN", "StarLight", "Caltech", "UCSD"] and len(out["paths"]) == 3
    assert set(out["many"]) == {"CERN->ORNL", "CERN->UCSD"}
    assert out["est"]["seconds"] > out["est"]["delay_s"] > 0
    assert len(out["ests"]) == 3
    assert out["sim"]["completed"] is True and out["sim"]["late"] == 0
    assert out["submit"] == {"valid": True, "accepted": 1, "rejected": {}}
    assert out["bad"]["valid"] is False


def test_tools_direct_match_mcp():
    sim = started()
    v = sim.view()
    direct = {
        "net": tools.get_network_state(v),
        "paths": tools.get_paths(v, "CERN", "UCSD", 3),
        "sim": tools.simulate_plan(v, {}),
    }
    out, calls = run_with_tools(build_server(v), call_every_tool)
    check_results(out)
    assert out["net"] == direct["net"] and out["paths"] == direct["paths"] and out["sim"] == direct["sim"]
    assert [c["tool"] for c in calls][:3] == ["get_workflow_requirements", "get_network_state", "get_paths"]
    assert len(calls) == 9 and all("result" in c for c in calls)


def test_tools_over_stdio():
    params = StdioServerParameters(command=sys.executable, args=["-m", "att.mcp_server"], cwd=str(ROOT))
    out, _ = run_with_tools(params, call_every_tool)
    check_results(out)


def test_estimate_and_paths_respect_down_links():
    sim = started("link_failure")
    # move the twin to just after the link goes down, with the baseline (it won't react)
    sim.stop_time = 0.2 * sim.D
    sim._loop()
    v = sim.view()
    net = tools.get_network_state(v)
    down = [ln["link"] for ln in net["links"] if not ln["up"]]
    assert down == [["StarLight", "Caltech"]]
    assert tools.estimate_transfer_time(v, 1e9, ["CERN", "StarLight", "Caltech"])["seconds"] is None
    for p in tools.get_paths(v, "CERN", "Caltech", 3, avoid_down=True):
        assert ["StarLight", "Caltech"] != p[1:3]


def test_simulate_plan_cannot_see_the_future():
    """A failure scheduled for the future must not change simulate_plan's output (via MCP)."""
    outs = []
    for scenario in ("normal", "link_failure"):
        sim = started(scenario, seed=2)
        out, _ = run_with_tools(build_server(sim.view()), lambda tc: tc.call("simulate_plan", plan={}))
        outs.append(out)
    assert json.dumps(outs[0], sort_keys=True) == json.dumps(outs[1], sort_keys=True)
    assert outs[0]["completed"]


def test_simulate_plan_sees_the_present_outage():
    """Once the link IS down, the forecast must show it (it stays down forever in the forecast)."""
    sim = started("link_failure", seed=2)
    sim.stop_time = 0.2 * sim.D
    sim._loop()
    out = tools.simulate_plan(sim.view(), {})
    assert out["failed_transfers"] > 0 or out["completed"] is False


def test_tool_error_is_reported():
    from att.tool_client import ToolCallError
    sim = started()
    with pytest.raises(ToolCallError):
        run_with_tools(build_server(sim.view()), lambda tc: tc.call("estimate_transfer_time", bytes=1, path=["X", "Y"]))
