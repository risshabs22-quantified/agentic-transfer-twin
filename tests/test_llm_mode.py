"""LLM mode, tested OFFLINE: the Claude call is replaced by a fake, so tests never cost money."""
import json

import pytest

import att.agents.llm_coordinator as llmc
from att import config
from att.decision_log import read_log
from att.experiment import execute
from att.llm import LLMError
from att.replay import replay_run
from att.runner import build_sim, make_planner, run_settings

EXP = config.load_experiment()


def fake(answer_initial, answer_event=None, fail=False):
    async def ask_json(system, user, schema):
        if fail:
            raise LLMError("simulated outage")
        data = answer_initial if "draft" in schema["properties"] else answer_event
        return {"data": data, "raw": json.dumps(data), "usage": {}, "model": "fake", "request_id": None,
                "stop_reason": "end_turn"}
    return ask_json


def run(monkeypatch, scenario, **kw):
    monkeypatch.setattr(llmc, "ask_json", fake(**kw))
    sim = build_sim(EXP, "1000genome-2ch", scenario, 100)
    m = sim.run(make_planner("agents", EXP, mode="llm"))
    return m, sim


def test_llm_choice_is_applied(monkeypatch):
    m, sim = run(monkeypatch, "normal",
                 answer_initial={"draft": "lowest-delay", "priority_overrides": [], "reason": "keep it simple"})
    rev = sim.decisions[0]["saw"]["review"]
    assert rev["status"] == "ok" and rev["draft"] == "lowest-delay"
    assert sim.decisions[0]["reason"].startswith("[llm] chose the lowest-delay draft")
    assert m["completed"] and m["rejected_entries"] == 0


def test_llm_failure_falls_back_to_rules(monkeypatch):
    m_rule = build_sim(EXP, "1000genome-2ch", "link_failure", 100).run(make_planner("agents", EXP))
    m, sim = run(monkeypatch, "link_failure", answer_initial=None, fail=True)
    assert all(d["saw"].get("review", {}).get("status", "fallback").startswith("fallback") for d in sim.decisions)
    assert m["completion_s"] == m_rule["completion_s"]  # identical to rule mode


def test_invalid_llm_answers_are_ignored(monkeypatch):
    m, sim = run(monkeypatch, "link_failure",
                 answer_initial={"draft": "load-balanced", "priority_overrides": [{"id": "nope", "priority": 2}], "reason": "x"},
                 answer_event={"action": "custom", "custom_routes": [{"id": "nope", "option": 9, "priority": 2}], "reason": "y"})
    assert sim.decisions[0]["saw"]["review"]["overrides_ignored"] == ["nope"]
    assert m["completed"] and m["rejected_entries"] == 0


def test_llm_run_replays_without_calling_the_api(monkeypatch, tmp_path):
    monkeypatch.setattr(llmc, "ask_json", fake(
        answer_initial={"draft": "load-balanced", "priority_overrides": [], "reason": "fast"},
        answer_event={"action": "apply_proposal", "custom_routes": [], "reason": "ok"}))
    s = run_settings(EXP, "1000genome-2ch", "link_failure", 100, planner="agents")
    s["mode"] = "llm"
    man = execute(s, results_dir=tmp_path, commit="t")
    assert man["run_id"].endswith("__llm")

    async def forbidden(*a, **k):
        raise AssertionError("replay must not call the API")
    monkeypatch.setattr(llmc, "ask_json", forbidden)
    assert replay_run(man, read_log(tmp_path / "logs" / f"{man['run_id']}.jsonl.gz")) == []


def test_llm_mode_only_for_agents():
    with pytest.raises(ValueError):
        make_planner("baseline", EXP, mode="llm")
