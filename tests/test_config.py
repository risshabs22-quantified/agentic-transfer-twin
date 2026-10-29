"""The frozen experiment config matches what network tuning chose."""
import json

from att import config


def test_data_scale_frozen_from_tuning():
    exp = config.load_experiment()
    tuning = json.loads((config.ROOT / "results" / "tuning" / "tuning.json").read_text())
    for wf, rec in tuning["workflows"].items():
        assert exp["workflows"][wf]["data_scale"] == rec["data_scale"], wf
        assert (exp.get("scenario_overrides") or {}).get(wf, {}) == rec["overrides"], wf


def test_tuning_used_only_tuning_seeds():
    exp = config.load_experiment()
    tuning = json.loads((config.ROOT / "results" / "tuning" / "tuning.json").read_text())
    assert tuning["seeds"] == exp["seeds"]["tuning"] == [100, 101, 102, 103, 104]
    assert not set(exp["seeds"]["tuning"]) & set(exp["seeds"]["evaluation"])
