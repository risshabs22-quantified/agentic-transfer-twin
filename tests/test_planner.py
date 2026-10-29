"""Plan validation (CLAUDE.md section 10)."""
from att.network import Link, Topology
from att.planner import validate_entry, validate_plan

TOPO = Topology(sites=["A", "B", "C"], links=[Link("A", "B", 100, 1), Link("B", "C", 100, 1), Link("A", "C", 100, 5)])
TR = {"x": {"id": "x", "src": "A", "dst": "C"}}


def check(entry, now=0.0, finished=frozenset()):
    return validate_entry("x", entry, TR, TOPO, now, finished)


def test_valid_entries():
    assert check({"path": ["A", "C"], "priority": 1, "start_s": 0.0}) is None
    assert check({"path": ["A", "B", "C"], "priority": 2, "start_s": 3}) is None


def test_invalid_entries():
    assert check({"path": ["A", "B"], "priority": 1, "start_s": 0}) is not None        # wrong end
    assert check({"path": ["B", "C"], "priority": 1, "start_s": 0}) is not None        # wrong start
    assert check({"path": ["A", "B", "A", "C"], "priority": 1, "start_s": 0}) is not None  # not simple
    assert check({"path": ["A", "C"], "priority": 3, "start_s": 0}) is not None
    assert check({"path": ["A", "C"], "priority": True, "start_s": 0}) is not None
    assert check({"path": ["A", "C"], "priority": 1, "start_s": 1.0}, now=2.0) is not None
    assert check({"path": ["A", "C"], "priority": 1, "start_s": float("nan")}) is not None
    assert check({"path": ["A", "C"], "priority": 1}) is not None
    assert check({"path": ["A", "C"], "priority": 1, "start_s": 0}, finished={"x"}) is not None
    assert validate_entry("y", {}, TR, TOPO, 0.0) == "unknown transfer id"
    topo2 = Topology(sites=["A", "B", "C"], links=[Link("A", "B", 100, 1), Link("B", "C", 100, 1)])
    assert validate_entry("x", {"path": ["A", "C"], "priority": 1, "start_s": 0}, TR, topo2, 0.0) == "no link A-C"


def test_validate_plan_splits():
    acc, rej = validate_plan({"x": {"path": ["A", "C"], "priority": 2, "start_s": 0},
                              "y": {"path": ["A", "C"], "priority": 1, "start_s": 0}}, TR, TOPO, 0.0)
    assert list(acc) == ["x"] and acc["x"]["start_s"] == 0.0 and list(rej) == ["y"]
    assert validate_plan(["not", "a", "dict"], TR, TOPO, 0.0)[1] == {"*": "plan is not an object"}
