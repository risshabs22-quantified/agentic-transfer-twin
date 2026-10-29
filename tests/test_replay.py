"""Stage 7: decision logs, manifests and exact replay."""
import gzip
import json

import pytest

from att import config
from att.decision_log import read_log, write_log
from att.experiment import execute
from att.replay import ReplayMismatch, ReplayPlanner, replay_run
from att.runner import run_settings, sim_from_settings

EXP = config.load_experiment()


@pytest.mark.parametrize("planner", ["baseline", "agents"])
def test_replay_dev_run_exactly(tmp_path, planner):
    s = run_settings(EXP, "1000genome-2ch", "link_failure", 100, planner=planner)
    man = execute(s, results_dir=tmp_path, commit="test")
    entries = read_log(tmp_path / "logs" / f"{man['run_id']}.jsonl.gz")
    assert len(entries) == man["metrics"]["decisions"]
    assert entries[0]["trigger"]["type"] == "initial_plan"
    assert all(e["run_id"] == man["run_id"] for e in entries)
    assert replay_run(man, entries) == []


def test_log_and_manifest_are_byte_identical_when_rerun(tmp_path):
    s = run_settings(EXP, "montage-005d", "congestion", 101, planner="agents")
    a = execute(s, results_dir=tmp_path / "a", commit="x")
    b = execute(s, results_dir=tmp_path / "b", commit="x")
    rid = a["run_id"]
    assert (tmp_path / "a/logs" / f"{rid}.jsonl.gz").read_bytes() == (tmp_path / "b/logs" / f"{rid}.jsonl.gz").read_bytes()
    assert a["metrics"] == b["metrics"]


def test_replay_detects_a_tampered_log(tmp_path):
    s = run_settings(EXP, "1000genome-2ch", "link_failure", 100, planner="baseline_reroute")
    man = execute(s, results_dir=tmp_path, commit="test")
    entries = read_log(tmp_path / "logs" / f"{man['run_id']}.jsonl.gz")
    entries[1]["trigger"]["t"] += 1.0  # pretend the outage was logged a second later
    diffs = replay_run(man, entries)
    assert diffs and "diverged" in diffs[0]


def test_replay_planner_rejects_extra_event():
    planner = ReplayPlanner([{"trigger": {"type": "initial_plan", "seq": 0, "t": 0.0}, "decision": {}}])
    sim = sim_from_settings(run_settings(EXP, "1000genome-2ch", "link_failure", 100))
    with pytest.raises(ReplayMismatch):
        sim.run(planner)


def test_log_format(tmp_path):
    p = tmp_path / "x.jsonl.gz"
    write_log(p, "rid", [{"seq": 0, "t": 0.0, "agent": "a", "trigger": {"type": "initial_plan", "t": 0.0, "seq": 0},
                          "saw": {}, "tool_calls": [], "decision": {}, "rejected": {}, "reason": "r"}])
    lines = gzip.open(p, "rt").read().splitlines()
    rec = json.loads(lines[0])
    assert list(rec) == ["run_id", "seq", "t", "agent", "trigger", "saw", "tool_calls", "decision", "rejected", "reason"]
