from __future__ import annotations

import hashlib
import json
from graphlib import TopologicalSorter
from pathlib import Path
from typing import Any


def load_instance(path: str | Path) -> tuple[str, dict[str, dict], dict[str, int], dict[str, float]]:
    with open(path) as fh:
        d = json.load(fh)
    spec = d["workflow"]["specification"]
    exe = d["workflow"]["execution"]
    tasks = {t["id"]: t for t in spec["tasks"]}
    size = {f["id"]: f["sizeInBytes"] for f in spec["files"]}
    runtime = {t["id"]: t["runtimeInSeconds"] for t in exe["tasks"]}
    return d["name"], tasks, size, runtime


def place_tasks(tasks: dict[str, Any], sites: list[str], seed: int = 0) -> dict[str, str]:
    def pick(tid: str) -> str:
        h = int(hashlib.sha256(f"{seed}:{tid}".encode()).hexdigest(), 16)
        return sites[h % len(sites)]
    return {tid: pick(tid) for tid in tasks}


def topological_order(tasks: dict[str, Any]) -> list[str]:
    return list(TopologicalSorter({tid: t["parents"] for tid, t in tasks.items()}).static_order())


def earliest_finish_times(tasks: dict[str, Any], runtime: dict[str, float]) -> dict[str, float]:
    finish: dict[str, float] = {}
    for tid in topological_order(tasks):
        finish[tid] = max((finish[p] for p in tasks[tid]["parents"]), default=0) + runtime[tid]
    return finish


def latest_start_times(tasks: dict[str, Any], runtime: dict[str, float],
                       slack: float) -> tuple[dict[str, float], float]:
    order = topological_order(tasks)
    finish = earliest_finish_times(tasks, runtime)
    deadline = slack * max(finish.values())
    latest_finish: dict[str, float] = {}
    for tid in reversed(order):
        latest_finish[tid] = min((latest_finish[c] - runtime[c] for c in tasks[tid]["children"]),
                                 default=deadline)
    return {tid: latest_finish[tid] - runtime[tid] for tid in order}, deadline


def extract_transfers(path: str | Path, sites: list[str], source_site: str, slack: float = 1.5,
                      seed: int = 0, data_scale: float = 1) -> dict[str, Any]:
    name, tasks, size, runtime = load_instance(path)
    place = place_tasks(tasks, sites, seed)
    producer = {f: tid for tid, t in tasks.items() for f in t["outputFiles"]}
    latest_start, deadline = latest_start_times(tasks, runtime, slack)
    earliest_finish = earliest_finish_times(tasks, runtime)

    def scaled(f: str) -> int:
        return int(round(size[f] * data_scale))

    transfers: dict[tuple[str, str], dict[str, Any]] = {}
    for tid, t in tasks.items():
        for f in t["inputFiles"]:
            src = place[producer[f]] if f in producer else source_site
            dst = place[tid]
            if src == dst:
                continue
            key = (f, dst)
            need_by = latest_start[tid]
            if key not in transfers or need_by < transfers[key]["deadline_s"]:
                transfers[key] = {
                    "id": f"{f}@{dst}", "file": f, "bytes": scaled(f),
                    "src": src, "dst": dst,
                    "after_task": producer.get(f),
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
    return {
        "workflow": extracted["workflow"],
        "transfers": len(extracted["transfers"]),
        "gb_moved": sum(t["bytes"] for t in extracted["transfers"]) / 1e9,
        "deadline_s": extracted["deadline_s"],
    }


def merge_workflows(parts: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
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
