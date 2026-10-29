"""Part 2 simulator tests, including the three required by CLAUDE.md section 9."""
import json
import math

import pytest

from att import config
from att.baseline import Baseline, BaselineReroute
from att.network import Link, NetEvent, Topology
from att.planner import Planner
from att.runner import build_sim
from att.simulator import Simulator
from tests.helpers import run_python


def tiny_workflow(nbytes: float, deadline_s: float = 10.0, transfer_deadline: float = 5.0) -> dict:
    """One task at B that needs one raw file from A."""
    return {
        "workflow": "tiny", "deadline_s": deadline_s, "source_site": "A",
        "transfers": [{"id": "f@B", "file": "f", "bytes": nbytes, "src": "A", "dst": "B",
                       "after_task": None, "deadline_s": transfer_deadline}],
        "tasks": {"t": {"parents": [], "children": [], "inputs": ["f"], "outputs": [], "runtime_s": 1.0,
                        "site": "B", "earliest_finish_s": 1.0, "latest_start_s": 5.0}},
    }


def two_site_topo(ms: float = 10.0) -> Topology:
    return Topology(sites=["A", "B"], links=[Link("A", "B", 100.0, ms)])


class Recorder(Baseline):
    """Baseline that remembers every event it was sent."""
    def __init__(self):
        super().__init__()
        self.events = []

    def on_event(self, event, view):
        self.events.append(event)
        return {}


def test_units_sanity():
    """10 GB on an empty 100 Gbps link takes 0.8 s, then arrives after the one-way delay."""
    sim = Simulator(tiny_workflow(10e9), two_site_topo(ms=10.0), None, [], seed=0, dt=0.01)
    m = sim.run(Baseline())
    arrival = sim.by_id["f@B"].arrive_t
    assert arrival == pytest.approx(0.8 + 0.010, abs=0.01)
    assert m["completed"] and m["completion_s"] == pytest.approx(arrival + 1.0)
    assert m["gb_moved"] == pytest.approx(10.0)
    assert m["late"] == 0


def test_failure_path_counts_transfer_once():
    """The only path goes down at 1 s (0.1 D) and comes back at 3.5 s. Timeout = 0.1 D = 1 s,
    so the attempt fails at 2 s and again at 3 s; the transfer is counted once."""
    ev = [NetEvent("down", ("A", "B"), 0.1, 0.35)]
    sim = Simulator(tiny_workflow(100e9), two_site_topo(), None, ev, seed=0, dt=0.01)
    rec = Recorder()
    m = sim.run(rec)
    assert m["failed_attempts"] == 2
    assert m["failed_transfers"] == 1
    fails = [e for e in rec.events if e["type"] == "transfer_failed"]
    assert [round(e["t"], 9) for e in fails] == [2.0, 3.0]
    assert [e["type"] for e in rec.events] == ["link_down", "transfer_failed", "transfer_failed", "link_up"]
    assert [e["seq"] for e in rec.events] == [1, 2, 3, 4]
    # after the link returns, the full 100 GB is re-sent: 3.5 + 8.0 s, plus 10 ms delay
    assert sim.by_id["f@B"].arrive_t == pytest.approx(11.51)
    assert m["late"] == 1 and m["completed"]


def test_stall_shorter_than_timeout_does_not_fail():
    ev = [NetEvent("down", ("A", "B"), 0.1, 0.15)]  # 0.5 s outage < 1 s timeout
    sim = Simulator(tiny_workflow(100e9), two_site_topo(), None, ev, seed=0, dt=0.01)
    m = sim.run(Baseline())
    assert m["failed_attempts"] == 0
    assert sim.by_id["f@B"].arrive_t == pytest.approx(8.0 + 0.5 + 0.01)


def test_priority_shares_capacity_two_to_one():
    wf = tiny_workflow(10e9)
    wf["transfers"].append({"id": "g@B", "file": "g", "bytes": 10e9, "src": "A", "dst": "B",
                            "after_task": None, "deadline_s": 5.0})
    wf["tasks"]["t"]["inputs"].append("g")

    class Prio(Planner):
        def plan(self, transfers, view):
            return {"f@B": {"path": ["A", "B"], "priority": 2, "start_s": 0.0},
                    "g@B": {"path": ["A", "B"], "priority": 1, "start_s": 0.0}}

    sim = Simulator(wf, two_site_topo(ms=0.0), None, [], seed=0, dt=0.01)
    sim.run(Prio())
    # f gets 2/3 of 12.5 GB/s -> done at 1.2 s; then g has the link alone.
    assert sim.by_id["f@B"].arrive_t == pytest.approx(1.2)
    assert sim.by_id["g@B"].arrive_t == pytest.approx(1.6)


def test_invalid_entries_rejected_and_logged():
    class Bad(Planner):
        def plan(self, transfers, view):
            return {"f@B": {"path": ["B", "A"], "priority": 1, "start_s": 0.0},
                    "nope": {"path": ["A", "B"], "priority": 1, "start_s": 0.0}}

    sim = Simulator(tiny_workflow(10e9), two_site_topo(), None, [], seed=0, dt=0.01)
    m = sim.run(Bad())
    assert m["completed"]  # the default (lowest-delay) entry stayed in place
    rej = sim.decisions[0]["rejected"]
    assert set(rej) == {"f@B", "nope"}
    assert m["rejected_entries"] == 2


def test_start_s_delays_transfer():
    class Later(Planner):
        def plan(self, transfers, view):
            return {"f@B": {"path": ["A", "B"], "priority": 1, "start_s": 2.0}}

    sim = Simulator(tiny_workflow(10e9), two_site_topo(ms=0.0), None, [], seed=0, dt=0.01)
    sim.run(Later())
    assert sim.by_id["f@B"].arrive_t == pytest.approx(2.8)


def test_baseline_completes_dev_workflow_normal():
    exp = config.load_experiment()
    sim = build_sim(exp, "1000genome-2ch", "normal", 0, data_scale=1)  # seed 0 = acceptance-table placement
    m = sim.run(Baseline())
    assert m["completed"]
    assert m["n_transfers"] == 62
    assert m["late"] == 0 and m["failed_transfers"] == 0
    assert m["gb_moved"] == pytest.approx(sum(t["bytes"] for t in sim.workflow["transfers"]) / 1e9)


def test_reroute_avoids_down_link():
    exp = config.load_experiment()
    m_base = build_sim(exp, "1000genome-2ch", "link_failure", 100, data_scale=100).run(Baseline())
    sim = build_sim(exp, "1000genome-2ch", "link_failure", 100, data_scale=100)
    m = sim.run(BaselineReroute())
    assert m_base["failed_transfers"] > 0
    assert m["failed_transfers"] == 0 and m["reroutes"] > 0
    assert m["completion_s"] <= m_base["completion_s"]


def test_forecast_does_not_change_the_run():
    """Calling forecasts (snapshots) during a run must not change the run's result."""
    exp = config.load_experiment()

    class Peeker(BaselineReroute):
        def on_event(self, event, view):
            view.forecast(view.plan())
            return super().on_event(event, view)

    a = build_sim(exp, "1000genome-2ch", "link_failure", 7, data_scale=100).run(BaselineReroute())
    b = build_sim(exp, "1000genome-2ch", "link_failure", 7, data_scale=100).run(Peeker())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_forecast_ignores_future_events():
    """A failure scheduled in the future must not affect a forecast made before it."""
    exp = config.load_experiment()
    normal = build_sim(exp, "1000genome-2ch", "normal", 4, data_scale=100)
    failing = build_sim(exp, "1000genome-2ch", "link_failure", 4, data_scale=100)
    for sim in (normal, failing):  # make the initial plan, then forecast at t = 0
        sim.planner = Baseline()
        sim._call_planner({"type": "initial_plan", "t": 0.0, "seq": 0})
    fa = normal.view().forecast(normal.view().plan())
    fb = failing.view().forecast(failing.view().plan())
    assert json.dumps(fa, sort_keys=True) == json.dumps(fb, sort_keys=True)
    assert fa["completed"]


def test_max_time_gives_incomplete_run():
    ev = [NetEvent("down", ("A", "B"), 0.0, 100.0)]  # down forever (past max time)
    sim = Simulator(tiny_workflow(1e9), two_site_topo(), None, ev, seed=0, dt=0.01, max_time_frac=2.0)
    m = sim.run(Baseline())
    assert m["completed"] is False and math.isnan(m["completion_s"])
    assert m["late"] == 1
    assert m["end_s"] == pytest.approx(20.0)


def test_determinism_across_processes():
    code = (
        "import json\n"
        "from att import config\n"
        "from att.runner import build_sim\n"
        "from att.baseline import Baseline, BaselineReroute\n"
        "exp = config.load_experiment()\n"
        "out = []\n"
        "for sc in ['congestion', 'link_failure']:\n"
        "    for P in (Baseline, BaselineReroute):\n"
        "        sim = build_sim(exp, '1000genome-2ch', sc, 3, data_scale=100)\n"
        "        out.append(sim.run(P()))\n"
        "        out.append([d['decision'] for d in sim.decisions])\n"
        "print(json.dumps(out, sort_keys=True))\n"
    )
    a = run_python(code, hashseed="0")
    b = run_python(code, hashseed="4242")
    assert a == b and "completion_s" in a
