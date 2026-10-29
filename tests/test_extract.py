"""Part 1 acceptance tests: transfer counts, GB moved and deadlines for the four traces."""
import pytest

from att.extract import extract_transfers, latest_start_times, load_instance, place_tasks, summarize
from tests.helpers import RAW, SITES, SOURCE, run_python

# file stem -> (transfers, GB moved to 2 decimals, D to 3 decimals); seed 0, slack 1.5, data_scale 1
EXPECTED = {
    "1000genome-chameleon-2ch-100k-001": (62, 8.67, 307.029),
    "montage-chameleon-2mass-005d-001": (140, 0.34, 32.078),
    "1000genome-chameleon-8ch-100k-001": (179, 38.97, 601.916),
    "montage-chameleon-2mass-01d-001": (248, 0.68, 31.683),
}


def extract(stem, **kw):
    return extract_transfers(RAW / f"{stem}.json", SITES, SOURCE, **kw)


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_acceptance_table(stem):
    n, gb, d = EXPECTED[stem]
    s = summarize(extract(stem, slack=1.5, seed=0))
    assert s["transfers"] == n
    assert round(s["gb_moved"], 2) == gb
    assert round(s["deadline_s"], 3) == d


@pytest.mark.parametrize("stem", sorted(EXPECTED))
def test_transfer_invariants(stem):
    ex = extract(stem)
    ids = [t["id"] for t in ex["transfers"]]
    assert len(ids) == len(set(ids)), "transfer ids must be unique"
    for t in ex["transfers"]:
        assert t["src"] != t["dst"]
        assert t["bytes"] > 0
        assert 0 <= t["deadline_s"] <= ex["deadline_s"] + 1e-9
        # a produced file starts where its producer runs; a raw input starts at the source
        if t["after_task"] is None:
            assert t["src"] == SOURCE
        else:
            assert t["src"] == ex["placement"][t["after_task"]]


def test_data_scale_multiplies_bytes_only():
    stem = "montage-chameleon-2mass-005d-001"
    base, scaled = extract(stem), extract(stem, data_scale=100)
    assert [t["id"] for t in base["transfers"]] == [t["id"] for t in scaled["transfers"]]
    for a, b in zip(base["transfers"], scaled["transfers"]):
        assert b["bytes"] == round(a["bytes"] * 100)
        assert a["deadline_s"] == b["deadline_s"]  # runtimes are never scaled
    assert base["deadline_s"] == scaled["deadline_s"]


def test_placement_depends_on_seed_and_is_stable():
    _, tasks, _, _ = load_instance(RAW / "1000genome-chameleon-2ch-100k-001.json")
    assert place_tasks(tasks, SITES, 0) == place_tasks(tasks, SITES, 0)
    assert place_tasks(tasks, SITES, 0) != place_tasks(tasks, SITES, 1)
    assert set(place_tasks(tasks, SITES, 0).values()) <= set(SITES)


def test_critical_path_tiny_dag():
    # a -> b -> d and a -> c -> d; runtimes 1, 2, 5, 1. Critical path a-c-d = 7, D = 1.5 * 7 = 10.5.
    tasks = {
        "a": {"parents": [], "children": ["b", "c"]},
        "b": {"parents": ["a"], "children": ["d"]},
        "c": {"parents": ["a"], "children": ["d"]},
        "d": {"parents": ["b", "c"], "children": []},
    }
    runtime = {"a": 1, "b": 2, "c": 5, "d": 1}
    ls, D = latest_start_times(tasks, runtime, slack=1.5)
    assert D == pytest.approx(10.5)
    assert ls["d"] == pytest.approx(9.5)
    assert ls["c"] == pytest.approx(4.5)
    assert ls["b"] == pytest.approx(7.5)
    assert ls["a"] == pytest.approx(3.5)


def test_extract_identical_across_processes():
    """Same seed -> byte-identical output in two processes with different PYTHONHASHSEED."""
    code = (
        "import json, hashlib\n"
        "from att.extract import extract_transfers\n"
        "out = {}\n"
        f"for stem in {sorted(EXPECTED)!r}:\n"
        f"    ex = extract_transfers('data/raw/' + stem + '.json', {SITES!r}, {SOURCE!r}, seed=3, data_scale=7)\n"
        "    out[stem] = hashlib.sha256(json.dumps(ex, sort_keys=False).encode()).hexdigest()\n"
        "print(json.dumps(out))\n"
    )
    a = run_python(code, hashseed="1")
    b = run_python(code, hashseed="98765")
    assert a == b and len(a) > 10
