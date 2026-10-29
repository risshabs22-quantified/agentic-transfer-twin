"""Stretch goal 2: two workflows sharing the network."""
import pytest

from att import config
from att.decision_log import read_log
from att.experiment import execute
from att.replay import replay_run
from att.runner import competing_settings, make_planner, sim_from_settings

EXP = config.load_experiment()


def test_merged_workflow_keeps_ids_and_deadlines_apart():
    sim = sim_from_settings(competing_settings(EXP, 0))
    assert set(sim.members) == {"1000genome-8ch", "montage-01d"}
    assert all("/" in tid for tid in sim.tasks)
    assert {x.workflow for x in sim.transfers} == {"1000genome-8ch", "montage-01d"}
    # each transfer times out after 0.1 x ITS OWN workflow's D
    for x in sim.transfers:
        assert x.timeout == pytest.approx(0.1 * sim.members[x.workflow])
    assert sim.dt == pytest.approx(min(sim.members.values()) / 1000)


def test_competing_run_completes_and_replays(tmp_path):
    man = execute(competing_settings(EXP, 1, "agents"), results_dir=tmp_path, commit="t")
    m = man["metrics"]
    assert m["completed"]
    assert m["1000genome-8ch:completion_s"] <= m["completion_s"] and m["montage-01d:completion_s"] <= m["completion_s"]
    assert replay_run(man, read_log(tmp_path / "logs" / f"{man['run_id']}.jsonl.gz")) == []


def test_single_workflow_runs_have_no_member_metrics():
    from att.runner import build_sim
    m = build_sim(EXP, "1000genome-2ch", "normal", 0).run(make_planner("baseline", EXP))
    assert not any(":" in k for k in m)
