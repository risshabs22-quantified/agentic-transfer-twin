"""The agent team runs end to end, uses only MCP tools, and is deterministic."""
import ast
import json

import pytest

from att import config
from att.runner import build_sim, make_planner
from tests.helpers import ROOT, run_python

EXP = config.load_experiment()
FORBIDDEN = {"att.simulator", "att.network", "att.config", "att.runner", "att.extract", "yaml"}


@pytest.mark.parametrize("workflow", ["1000genome-2ch", "montage-005d"])
@pytest.mark.parametrize("scenario", ["normal", "congestion", "link_failure"])
def test_agents_run_end_to_end(workflow, scenario):
    sim = build_sim(EXP, workflow, scenario, 100)
    m = sim.run(make_planner("agents", EXP))
    assert m["completed"]
    assert m["rejected_entries"] == 0  # agents only submit valid entries
    first = sim.decisions[0]
    assert first["agent"] == "coordinator" and first["trigger"]["type"] == "initial_plan"
    tools_used = {c["tool"] for c in first["tool_calls"]}
    assert {"get_workflow_requirements", "get_network_state", "estimate_many", "simulate_plan",
            "submit_plan"} <= tools_used
    assert {c["agent"] for c in first["tool_calls"]} == {"workflow_agent", "network_agent", "coordinator"}
    if scenario != "normal":
        assert len(sim.decisions) >= 3  # initial plan + event on + event off
        assert all(d["reason"] for d in sim.decisions)


def _imports(path):
    tree = ast.parse(path.read_text())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


def test_planners_cannot_import_the_future():
    """No-peeking, structurally: planners never import the simulator, network model or configs."""
    files = list((ROOT / "att" / "agents").glob("*.py")) + [ROOT / "att" / "baseline.py"]
    for f in files:
        bad = {m for m in _imports(f) if any(m == x or m.startswith(x + ".") for x in FORBIDDEN)}
        assert not bad, f"{f.name} imports {bad}"


def test_agents_use_view_only_through_mcp():
    """The agents never read the view directly; they only hand it to build_server()."""
    for f in (ROOT / "att" / "agents").glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "view":
                pytest.fail(f"{f.name} reads view.{node.attr} directly")


def test_agent_params_frozen_from_tuning():
    tuning = json.loads((ROOT / "results" / "tuning" / "agent_tuning.json").read_text())
    for k, v in tuning["chosen"].items():
        assert EXP["agents"][k] == v
    assert tuning["seeds"] == EXP["seeds"]["tuning"]
    assert set(tuning["dev_workflows"]) == {w for w, v in EXP["workflows"].items() if v["role"] == "dev"}


def test_agents_deterministic_across_processes():
    code = (
        "import json\n"
        "from att import config\n"
        "from att.runner import build_sim, make_planner\n"
        "exp = config.load_experiment()\n"
        "sim = build_sim(exp, 'montage-005d', 'link_failure', 101)\n"
        "m = sim.run(make_planner('agents', exp))\n"
        "print(json.dumps([m, [[d['decision'], d['tool_calls'], d['reason']] for d in sim.decisions]], sort_keys=True))\n"
    )
    a = run_python(code, hashseed="11")
    b = run_python(code, hashseed="777")
    assert a == b and "simulate_plan" in a
