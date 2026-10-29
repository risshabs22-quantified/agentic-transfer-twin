"""Part 1: turn a WfInstances (WfFormat 1.6) JSON file into a list of network transfers.

Pipeline (each step is a small function so it can be tested and explained on its own):

    load_instance  ->  place_tasks  ->  latest_start_times  ->  extract_transfers

What is real and what is synthetic:
  * real (from the trace): the task graph (parents/children), which files each task reads
    and writes, file sizes in bytes, and task runtimes in seconds.
  * synthetic (made up by us, and labeled so): which site each task runs at (a seeded hash),
    the deadlines (critical path x slack), and the optional `data_scale` multiplier on sizes.
"""
from __future__ import annotations

import hashlib
import json
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any


def load_instance(path: str | Path) -> tuple[str, dict[str, dict], dict[str, int], dict[str, float]]:
    """Read a WfFormat 1.6 file.

    Returns (workflow name, tasks by id, file size in bytes by file id, runtime in seconds by task id).
    Only the fields listed in CLAUDE.md section 5 are used.
    """
    with open(path) as fh:
        d = json.load(fh)
    spec = d["workflow"]["specification"]
    exe = d["workflow"]["execution"]
    tasks = {t["id"]: t for t in spec["tasks"]}
    size = {f["id"]: f["sizeInBytes"] for f in spec["files"]}
    runtime = {t["id"]: t["runtimeInSeconds"] for t in exe["tasks"]}
    return d["name"], tasks, size, runtime


def place_tasks(tasks: dict[str, Any], sites: list[str], seed: int = 0) -> dict[str, str]:
    """Give every task a site. Same seed -> same placement, so runs are repeatable.

    Uses sha256, not Python's hash(), because hash() of a string changes between processes.
    This placement is SYNTHETIC: the traces don't say where tasks ran in a multi-site setting.
    """
    def pick(tid: str) -> str:
        h = int(hashlib.sha256(f"{seed}:{tid}".encode()).hexdigest(), 16)
        return sites[h % len(sites)]
    return {tid: pick(tid) for tid in tasks}


def topological_order(tasks: dict[str, Any]) -> list[str]:
    """Task ids ordered so every parent comes before its children (deterministic for a given file)."""
    return list(TopologicalSorter({tid: t["parents"] for tid, t in tasks.items()}).static_order())


def earliest_finish_times(tasks: dict[str, Any], runtime: dict[str, float]) -> dict[str, float]:
    """Forward pass of the critical-path method: earliest finish of each task if data moved instantly."""
    finish: dict[str, float] = {}
    for tid in topological_order(tasks):
        finish[tid] = max((finish[p] for p in tasks[tid]["parents"]), default=0) + runtime[tid]
    return finish


def latest_start_times(tasks: dict[str, Any], runtime: dict[str, float],
                       slack: float) -> tuple[dict[str, float], float]:
    """Critical-path method: the latest each task can start without the workflow missing its deadline.

    The workflow deadline D = slack x (critical path length if data moved instantly).
    Returns (latest start by task id, D).
    """
    order = topological_order(tasks)
    finish = earliest_finish_times(tasks, runtime)
    deadline = slack * max(finish.values())
    latest_finish: dict[str, float] = {}
    for tid in reversed(order):  # backward pass
        latest_finish[tid] = min((latest_finish[c] - runtime[c] for c in tasks[tid]["children"]),
                                 default=deadline)
    return {tid: latest_finish[tid] - runtime[tid] for tid in order}, deadline


def extract_transfers(path: str | Path, sites: list[str], source_site: str, slack: float = 1.5,
                      seed: int = 0, data_scale: float = 1) -> dict[str, Any]:
    """Turn one workflow trace into the network transfers it needs.

    One transfer per (file, destination site): if several tasks at one site read the same file,
    it is moved once, by the deadline of the earliest of those tasks.

    Returns a dict with:
      workflow    -- workflow name from the trace
      deadline_s  -- workflow deadline D (seconds)
      transfers   -- list of {id, file, bytes, src, dst, after_task, deadline_s}
      placement   -- task id -> site (synthetic)
      tasks       -- task id -> {parents, children, inputs, outputs, runtime_s, site,
                                 earliest_finish_s, latest_start_s}
      file_bytes  -- file id -> size in bytes (after data_scale)
      data_scale, slack, seed, source_site -- the settings used, for the record
    """
    name, tasks, size, runtime = load_instance(path)
    place = place_tasks(tasks, sites, seed)
    producer = {f: tid for tid, t in tasks.items() for f in t["outputFiles"]}
    latest_start, deadline = latest_start_times(tasks, runtime, slack)
    earliest_finish = earliest_finish_times(tasks, runtime)

    def scaled(f: str) -> int:
        # Integer bytes keep every later sum exact; data_scale=1 leaves sizes untouched.
        return int(round(size[f] * data_scale))

    transfers: dict[tuple[str, str], dict[str, Any]] = {}
    for tid, t in tasks.items():
        for f in t["inputFiles"]:
            src = place[producer[f]] if f in producer else source_site
            dst = place[tid]
            if src == dst:
                continue  # same site: no network transfer needed
            key = (f, dst)  # one copy per destination site, even if several tasks there need it
            need_by = latest_start[tid]
            if key not in transfers or need_by < transfers[key]["deadline_s"]:
                transfers[key] = {
                    "id": f"{f}@{dst}", "file": f, "bytes": scaled(f),
                    "src": src, "dst": dst,
                    "after_task": producer.get(f),  # None = raw input, ready at t=0
                    "deadline_s": need_by,
                }
    out = list(transfers.values())
    for tr in out:
        tr["deadline_s"] = round(tr["deadline_s"], 3)

    task_info = {
        tid: {
            "parents": list(t["parents"]),
            "children": list(t["children"]),
            "inputs": list(t["inputFiles"]),
            "outputs": list(t["outputFiles"]),
            "runtime_s": float(runtime[tid]),
            "site": place[tid],
            "earliest_finish_s": float(earliest_finish[tid]),
            "latest_start_s": float(latest_start[tid]),
        }
        for tid, t in tasks.items()
    }
    used_files = sorted({f for t in tasks.values() for f in t["inputFiles"] + t["outputFiles"]})
    return {
        "workflow": name,
        "deadline_s": round(deadline, 3),
        "transfers": out,
        "placement": place,
        "tasks": task_info,
        "file_bytes": {f: scaled(f) for f in used_files},
        "data_scale": data_scale,
        "slack": slack,
        "seed": seed,
        "source_site": source_site,
    }


def summarize(extracted: dict[str, Any]) -> dict[str, Any]:
    """Headline numbers used by the acceptance test and the docs."""
    return {
        "workflow": extracted["workflow"],
        "transfers": len(extracted["transfers"]),
        "gb_moved": sum(t["bytes"] for t in extracted["transfers"]) / 1e9,
        "deadline_s": extracted["deadline_s"],
    }


def merge_workflows(parts: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Combine several extracted workflows into one, so they share the network at the same time.

    Every task id and file id is prefixed with "<name>/" so nothing collides; each transfer and
    task remembers which workflow it belongs to; each workflow keeps its own deadline under
    "members". The combined "deadline_s" is the longest of them (it only sets the max run time).
    """
    def pre(name: str, x: str | None) -> str | None:
        return None if x is None else f"{name}/{x}"

    tasks: dict[str, Any] = {}
    transfers: list[dict[str, Any]] = []
    file_bytes: dict[str, int] = {}
    placement: dict[str, str] = {}
    members: dict[str, Any] = {}
    sources = {ex["source_site"] for _, ex in parts}
    if len(sources) != 1:
        raise ValueError("all workflows must share one source site")
    for name, ex in parts:
        members[name] = {"workflow": ex["workflow"], "deadline_s": ex["deadline_s"], "data_scale": ex["data_scale"]}
        for tid, t in ex["tasks"].items():
            tasks[pre(name, tid)] = {**t, "parents": [pre(name, p) for p in t["parents"]],
                                     "children": [pre(name, c) for c in t["children"]],
                                     "inputs": [pre(name, f) for f in t["inputs"]],
                                     "outputs": [pre(name, f) for f in t["outputs"]], "workflow": name}
            placement[pre(name, tid)] = ex["placement"][tid]
        for tr in ex["transfers"]:
            f = pre(name, tr["file"])
            transfers.append({**tr, "id": f"{f}@{tr['dst']}", "file": f, "after_task": pre(name, tr["after_task"]),
                              "workflow": name})
        file_bytes.update({pre(name, f): b for f, b in ex["file_bytes"].items()})
    return {
        "workflow": "+".join(name for name, _ in parts),
        "deadline_s": max(ex["deadline_s"] for _, ex in parts),
        "transfers": transfers, "placement": placement, "tasks": tasks, "file_bytes": file_bytes,
        "data_scale": None, "slack": parts[0][1]["slack"], "seed": parts[0][1]["seed"],
        "source_site": sources.pop(), "members": members,
    }
