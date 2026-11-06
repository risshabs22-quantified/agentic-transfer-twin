from __future__ import annotations

import heapq
import math
from typing import Any

from att.network import Background, BackgroundLoad, NetEvent, Topology, free_capacity_Bps, timeline
from att.planner import Plan, Planner, validate_plan

ARRIVAL, TASK_FINISH, RELEASE, NET_EVENT = 0, 1, 2, 3

WAITING = "waiting"
QUEUED = "queued"
ACTIVE = "active"
SENT = "sent"
ARRIVED = "arrived"

SUMMARY_FIELDS = ["completed", "completion_s", "failed_attempts", "failed_transfers", "late",
                  "n_transfers", "gb_moved", "avg_gbps", "data_wait_s", "reroutes", "decisions"]


class _Transfer:
    __slots__ = ("idx", "id", "file", "bytes", "src", "dst", "after_task", "deadline_s",
                 "path", "links", "delay_s", "priority", "start_s", "timeout", "workflow",
                 "status", "remaining", "stall", "rate", "failed_attempts",
                 "ready_t", "sent_t", "arrive_t")

    def copy(self) -> "_Transfer":
        c = _Transfer.__new__(_Transfer)
        for s in _Transfer.__slots__:
            v = getattr(self, s)
            setattr(c, s, list(v) if isinstance(v, list) else v)
        return c


class _Task:
    __slots__ = ("id", "site", "runtime_s", "parents", "outputs", "unmet", "status",
                 "start_t", "finish_t")

    def copy(self) -> "_Task":
        c = _Task.__new__(_Task)
        for s in _Task.__slots__:
            setattr(c, s, getattr(self, s))
        return c


class _NullPlanner(Planner):
    name = "forecast"

    def plan(self, transfers, view):
        return {}


class Simulator:
    def __init__(self, workflow: dict[str, Any], topo: Topology, background: Background | None,
                 events: list[NetEvent], seed: int, *, steps_per_deadline: int = 1000,
                 max_time_frac: float = 20.0, timeout_frac: float = 0.1, dt: float | None = None,
                 sharing: str = "proportional"):
        self.workflow = workflow
        self.topo = topo
        self.D = float(workflow["deadline_s"])
        self.members: dict[str, float] = {k: float(v["deadline_s"]) for k, v in workflow.get("members", {}).items()}
        grid_D = min(self.members.values()) if self.members else self.D
        self.dt = float(dt) if dt is not None else grid_D / steps_per_deadline
        self.max_time = max_time_frac * self.D
        self.timeout = timeout_frac * self.D
        self.seed = seed
        if sharing not in ("proportional", "maxmin"):
            raise ValueError(f"unknown sharing model {sharing!r}")
        self.sharing = sharing
        n_links = len(topo.links)

        self._load: BackgroundLoad | None = (
            BackgroundLoad(topo, background, self.D, self.dt, self.max_time, seed)
            if background is not None else None)
        self._const_free: list[float] | None = None
        if background is None:
            self._const_free = [topo.capacity_Bps(i) for i in range(n_links)]

        self.t = 0.0
        self.cell = 0
        self.down = [False] * n_links
        self.surge = [0.0] * n_links
        self.heap: list[tuple[float, int, int, Any]] = []
        self.counter = 0
        self.event_seq = 0
        self.reroutes = 0
        self.decisions: list[dict[str, Any]] = []
        self.rejections = 0
        self.planner: Planner | None = None
        self.stop_time = self.max_time
        self.count_window: tuple[float, float] | None = None
        self.window_bytes = [0.0] * n_links

        self.req: dict[str, dict[str, Any]] = {tr["id"]: dict(tr) for tr in workflow["transfers"]}
        self.transfers: list[_Transfer] = []
        self.by_id: dict[str, _Transfer] = {}
        by_after: dict[str | None, list[int]] = {}
        for i, tr in enumerate(workflow["transfers"]):
            x = _Transfer()
            x.idx, x.id, x.file, x.bytes = i, tr["id"], tr["file"], float(tr["bytes"])
            x.src, x.dst, x.after_task, x.deadline_s = tr["src"], tr["dst"], tr["after_task"], float(tr["deadline_s"])
            x.status = WAITING if tr["after_task"] is not None else ACTIVE
            x.remaining, x.stall, x.rate, x.failed_attempts = float(tr["bytes"]), 0.0, 0.0, 0
            x.ready_t = 0.0 if tr["after_task"] is None else math.nan
            x.sent_t = x.arrive_t = math.nan
            x.path, x.links, x.delay_s, x.priority, x.start_s = [], [], 0.0, 1, 0.0
            x.workflow = tr.get("workflow")
            x.timeout = timeout_frac * (self.members[x.workflow] if x.workflow in self.members else self.D)
            self.transfers.append(x)
            self.by_id[x.id] = x
            by_after.setdefault(tr["after_task"], []).append(i)
        self.by_after = {k: tuple(v) for k, v in by_after.items()}

        producer = {f: tid for tid, t in workflow["tasks"].items() for f in t["outputs"]}
        self.tasks: dict[str, _Task] = {}
        task_waiters: dict[str, list[str]] = {}
        transfer_waiters: dict[str, list[str]] = {}
        for tid, t in workflow["tasks"].items():
            k = _Task()
            k.id, k.site, k.runtime_s = tid, t["site"], float(t["runtime_s"])
            k.parents, k.outputs = list(t["parents"]), list(t["outputs"])
            need_tasks = list(dict.fromkeys(t["parents"]))
            need_transfers: list[str] = []
            for f in t["inputs"]:
                p = producer.get(f)
                src = workflow["tasks"][p]["site"] if p is not None else workflow["source_site"]
                if src == k.site:
                    if p is not None and p not in need_tasks:
                        need_tasks.append(p)
                else:
                    trid = f"{f}@{k.site}"
                    if trid not in need_transfers:
                        need_transfers.append(trid)
            for p in need_tasks:
                task_waiters.setdefault(p, []).append(tid)
            for trid in need_transfers:
                transfer_waiters.setdefault(trid, []).append(tid)
            k.unmet = len(need_tasks) + len(need_transfers)
            k.status, k.start_t, k.finish_t = "pending", math.nan, math.nan
            self.tasks[tid] = k
        self.task_waiters = {k: tuple(v) for k, v in task_waiters.items()}
        self.transfer_waiters = {k: tuple(v) for k, v in transfer_waiters.items()}
        self.tasks_done = 0

        for ev in timeline(events, topo, self.D):
            self._push(ev.t, NET_EVENT, ev)

        for x in self.transfers:
            self._set_route(x, topo.shortest_path(x.src, x.dst))


    def _push(self, t: float, kind: int, payload: Any) -> None:
        self.counter += 1
        heapq.heappush(self.heap, (t, kind, self.counter, payload))

    def _set_route(self, x: _Transfer, path: list[str]) -> None:
        x.path = list(path)
        x.links = self.topo.path_links(x.path)
        x.delay_s = self.topo.path_delay_s(x.path)

    def free_now(self) -> list[float]:
        if self._const_free is not None:
            return [0.0 if self.down[i] else self._const_free[i] for i in range(len(self.down))]
        return free_capacity_Bps(self.topo, self._load, self.cell, self.surge, self.down)

    def _finished_ids(self) -> set[str]:
        return {x.id for x in self.transfers if x.status in (SENT, ARRIVED)}

    def view(self) -> "TwinView":
        return TwinView(self)


    def _call_planner(self, trigger: dict[str, Any]) -> None:
        planner = self.planner
        planner.note = {}
        view = self.view()
        if trigger["type"] == "initial_plan":
            raw = planner.plan([dict(r) for r in self.req.values()], view)
        else:
            raw = planner.on_event(dict(trigger), view)
        raw = raw or {}
        accepted, rejected = validate_plan(raw, self.req, self.topo, self.t, self._finished_ids())
        self.rejections += len(rejected)
        self._apply(accepted, initial=trigger["type"] == "initial_plan")
        note = planner.note or {}
        self.decisions.append({
            "seq": len(self.decisions),
            "t": self.t,
            "agent": note.get("agent", planner.name),
            "trigger": dict(trigger),
            "saw": note.get("saw", {}),
            "tool_calls": note.get("tool_calls", []),
            "decision": raw,
            "rejected": rejected,
            "reason": note.get("reason", ""),
        })

    def _apply(self, accepted: Plan, initial: bool) -> None:
        for tid, e in accepted.items():
            x = self.by_id[tid]
            if e["path"] != x.path:
                if not initial:
                    self.reroutes += 1
                self._set_route(x, e["path"])
                x.stall = 0.0
            x.priority = e["priority"]
            x.start_s = e["start_s"]
            if x.status in (QUEUED, ACTIVE):
                if self.t >= x.start_s:
                    x.status = ACTIVE
                else:
                    x.status = QUEUED
                    x.stall = 0.0
                    self._push(x.start_s, RELEASE, x.idx)

    def _notify(self, event: dict[str, Any]) -> None:
        self.event_seq += 1
        event = {**event, "t": self.t, "seq": self.event_seq}
        self._call_planner(event)


    def _make_ready(self, x: _Transfer) -> None:
        x.ready_t = self.t
        if self.t >= x.start_s:
            x.status = ACTIVE
        else:
            x.status = QUEUED
            self._push(x.start_s, RELEASE, x.idx)

    def _satisfy(self, tid: str) -> None:
        k = self.tasks[tid]
        k.unmet -= 1
        if k.unmet == 0 and k.status == "pending":
            self._start_task(k)

    def _start_task(self, k: _Task) -> None:
        k.status, k.start_t = "running", self.t
        self._push(self.t + k.runtime_s, TASK_FINISH, k.id)

    def _finish_task(self, k: _Task) -> None:
        k.status, k.finish_t = "done", self.t
        self.tasks_done += 1
        for i in self.by_after.get(k.id, ()):
            self._make_ready(self.transfers[i])
        for w in self.task_waiters.get(k.id, ()):
            self._satisfy(w)

    def _net_event(self, ev: Any) -> None:
        if ev.type == "link_down":
            self.down[ev.link] = True
        elif ev.type == "link_up":
            self.down[ev.link] = False
        elif ev.type == "surge_start":
            self.surge[ev.link] += ev.extra_load
        elif ev.type == "surge_end":
            self.surge[ev.link] -= ev.extra_load
        self._notify({"type": ev.type, "link": self.topo.links[ev.link].ends})

    def _stalled(self, x: _Transfer) -> bool:
        return any(self.down[i] for i in x.links)

    def _process_instant(self) -> None:
        while True:
            progressed = False
            for x in self.transfers:
                if x.status == ACTIVE and x.remaining <= max(1e-6, 1e-12 * x.bytes):
                    x.status, x.remaining, x.rate, x.sent_t = SENT, 0.0, 0.0, self.t
                    self._push(self.t + x.delay_s, ARRIVAL, x.idx)
                    progressed = True
            while self.heap and self.heap[0][0] <= self.t:
                _, kind, _, payload = heapq.heappop(self.heap)
                progressed = True
                if kind == ARRIVAL:
                    x = self.transfers[payload]
                    x.status, x.arrive_t = ARRIVED, self.t
                    for w in self.transfer_waiters.get(x.id, ()):
                        self._satisfy(w)
                elif kind == TASK_FINISH:
                    self._finish_task(self.tasks[payload])
                elif kind == RELEASE:
                    x = self.transfers[payload]
                    if x.status == QUEUED and self.t >= x.start_s:
                        x.status = ACTIVE
                elif kind == NET_EVENT:
                    self._net_event(payload)
            for x in self.transfers:
                if x.status == ACTIVE and x.stall >= x.timeout * (1 - 1e-12) and self._stalled(x):
                    x.failed_attempts += 1
                    x.remaining, x.stall = x.bytes, 0.0
                    progressed = True
                    if self.planner is not None and not isinstance(self.planner, _NullPlanner):
                        self._notify({"type": "transfer_failed", "transfer_id": x.id})
            if not progressed:
                return

    def _rates(self) -> list[_Transfer]:
        active = [x for x in self.transfers if x.status == ACTIVE]
        free = self.free_now()
        moving = []
        for x in active:
            if self._stalled(x):
                x.rate = 0.0
            else:
                moving.append(x)
                x.stall = 0.0
        if self.sharing == "maxmin":
            self._maxmin_rates(moving, free)
            return active
        weight = [0] * len(free)
        for x in moving:
            for i in x.links:
                weight[i] += x.priority
        for x in moving:
            x.rate = min(free[i] * x.priority / weight[i] for i in x.links)
        return active

    @staticmethod
    def _maxmin_rates(moving: list[_Transfer], free: list[float]) -> None:
        cap = list(free)
        unfrozen = list(moving)
        while unfrozen:
            weight = [0] * len(cap)
            for x in unfrozen:
                for i in x.links:
                    weight[i] += x.priority
            best, share = -1, math.inf
            for i, w in enumerate(weight):
                if w > 0 and cap[i] / w < share:
                    best, share = i, cap[i] / w
            still = []
            for x in unfrozen:
                if best in x.links:
                    x.rate = max(share, 0.0) * x.priority
                    for i in x.links:
                        cap[i] -= x.rate
                else:
                    still.append(x)
            unfrozen = still


    def run(self, planner: Planner, horizon_s: float | None = None) -> dict[str, Any]:
        if horizon_s is not None:
            self.stop_time = min(self.max_time, self.t + horizon_s)
        if isinstance(planner, _NullPlanner):
            self.planner = planner
        elif self.planner is None:
            self.start(planner)
        return self._loop()

    def start(self, planner: Planner) -> None:
        self.planner = planner
        for k in self.tasks.values():
            if k.unmet == 0 and k.status == "pending":
                self._start_task(k)
        self._call_planner({"type": "initial_plan", "t": 0.0, "seq": 0})

    def _loop(self) -> dict[str, Any]:
        n_tasks = len(self.tasks)
        while True:
            self._process_instant()
            if self.tasks_done == n_tasks:
                break
            active = self._rates()
            snapped = False
            for x in active:
                if x.rate > 0 and self.t + x.remaining / x.rate <= self.t:
                    x.remaining, snapped = 0.0, True
                elif x.rate == 0 and self.t + (x.timeout - x.stall) <= self.t:
                    x.stall, snapped = x.timeout, True
            if snapped:
                continue
            nxt = self.stop_time
            if self.heap:
                nxt = min(nxt, self.heap[0][0])
            if active and self._load is not None:
                nxt = min(nxt, (self.cell + 1) * self.dt)
            for x in active:
                if x.rate > 0:
                    nxt = min(nxt, self.t + x.remaining / x.rate)
                else:
                    nxt = min(nxt, self.t + (x.timeout - x.stall))
            if not active and not self.heap:
                break
            step = nxt - self.t
            if self.count_window is not None:
                self._count_bytes(active, self.t, nxt)
            for x in active:
                if x.rate > 0:
                    x.remaining -= x.rate * step
                else:
                    x.stall += step
            self.t = nxt
            self._advance_cell()
            if self.t >= self.stop_time:
                self._process_instant()
                break
        return self.metrics()

    def _count_bytes(self, active: list[_Transfer], t0: float, t1: float) -> None:
        w0, w1 = self.count_window
        overlap = min(t1, w1) - max(t0, w0)
        if overlap <= 0:
            return
        for x in active:
            for i in x.links:
                self.window_bytes[i] += x.rate * overlap

    def _advance_cell(self) -> None:
        if self._load is None:
            return
        k = int(self.t / self.dt)
        if (k + 1) * self.dt <= self.t:
            k += 1
        elif k * self.dt > self.t:
            k -= 1
        self.cell = max(self.cell, k)


    def metrics(self) -> dict[str, Any]:
        done = self.tasks_done == len(self.tasks)
        completion = max(k.finish_t for k in self.tasks.values()) if done else math.nan
        arrived = [x for x in self.transfers if x.status == ARRIVED]
        arrived_bytes = sum(x.bytes for x in arrived)
        late = sum(1 for x in self.transfers if x.status != ARRIVED or x.arrive_t > x.deadline_s)
        wait = 0.0
        for k in self.tasks.values():
            if k.status == "pending":
                continue
            ref = max((self.tasks[p].finish_t for p in k.parents), default=0.0)
            wait += k.start_t - ref
        return {
            "completed": done,
            "completion_s": completion,
            "failed_attempts": sum(x.failed_attempts for x in self.transfers),
            "failed_transfers": sum(1 for x in self.transfers if x.failed_attempts > 0),
            "late": late,
            "n_transfers": len(self.transfers),
            "gb_moved": arrived_bytes / 1e9,
            "avg_gbps": arrived_bytes * 8 / completion / 1e9 if done and completion > 0 else math.nan,
            "data_wait_s": wait,
            "reroutes": self.reroutes,
            "decisions": len(self.decisions),
            "end_s": self.t,
            "deadline_D_s": self.D,
            "tasks_done": self.tasks_done,
            "transfers_arrived": len(arrived),
            "rejected_entries": self.rejections,
            **self._member_metrics(),
        }

    def _member_metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, D in self.members.items():
            tasks = [k for k in self.tasks.values() if k.id.startswith(name + "/")]
            done = all(k.status == "done" for k in tasks)
            comp = max(k.finish_t for k in tasks) if done else math.nan
            trs = [x for x in self.transfers if x.workflow == name]
            out[f"{name}:completion_s"] = comp
            out[f"{name}:completion_D"] = comp / D if done else math.nan
            out[f"{name}:late"] = sum(1 for x in trs if x.status != ARRIVED or x.arrive_t > x.deadline_s)
            out[f"{name}:failed_transfers"] = sum(1 for x in trs if x.failed_attempts > 0)
        return out


    def snapshot(self) -> "Simulator":
        c = Simulator.__new__(Simulator)
        c.workflow, c.topo, c.D, c.dt = self.workflow, self.topo, self.D, self.dt
        c.max_time, c.timeout, c.seed = self.max_time, self.timeout, self.seed
        c.members, c.sharing = self.members, self.sharing
        c._load = None
        c._const_free = self.free_now()
        c.t, c.cell = self.t, self.cell
        c.down, c.surge = list(self.down), [0.0] * len(self.surge)
        c.heap = [e for e in self.heap if e[1] != NET_EVENT]
        heapq.heapify(c.heap)
        c.counter, c.event_seq = self.counter, self.event_seq
        c.reroutes, c.decisions, c.rejections = 0, [], 0
        c.planner, c.stop_time = None, self.max_time
        c.count_window, c.window_bytes = None, [0.0] * len(self.down)
        c.req = self.req
        c.transfers = [x.copy() for x in self.transfers]
        c.by_id = {x.id: x for x in c.transfers}
        c.by_after, c.task_waiters, c.transfer_waiters = self.by_after, self.task_waiters, self.transfer_waiters
        c.tasks = {k: v.copy() for k, v in self.tasks.items()}
        c.tasks_done = self.tasks_done
        return c

    def forecast(self, plan: Plan, horizon_s: float | None = None) -> dict[str, Any]:
        c = self.snapshot()
        accepted, rejected = validate_plan(plan, c.req, c.topo, c.t, c._finished_ids())
        c._apply(accepted, initial=True)
        m = c.run(_NullPlanner(), horizon_s=horizon_s)
        m["rejected"] = rejected
        m["late_arrived"] = sum(1 for x in c.transfers if x.status == ARRIVED and x.arrive_t > x.deadline_s)
        return m


class TwinView:
    def __init__(self, sim: Simulator):
        self._sim = sim

    @property
    def now(self) -> float:
        return self._sim.t

    @property
    def deadline_s(self) -> float:
        return self._sim.D

    @property
    def topology(self) -> Topology:
        return self._sim.topo

    def links(self) -> list[dict[str, Any]]:
        sim = self._sim
        free = sim.free_now()
        out = []
        for i, ln in enumerate(sim.topo.links):
            out.append({"link": ln.ends, "gbps": ln.gbps, "ms": ln.ms, "up": not sim.down[i],
                        "free_gbps": free[i] * 8 / 1e9, "free_Bps": free[i]})
        return out

    def down_links(self) -> list[int]:
        return [i for i, d in enumerate(self._sim.down) if d]

    def transfers(self) -> list[dict[str, Any]]:
        out = []
        for x in self._sim.transfers:
            status = x.status
            if status == ACTIVE:
                status = "stalled" if self._sim._stalled(x) else "moving"
            out.append({
                "id": x.id, "file": x.file, "bytes": x.bytes, "src": x.src, "dst": x.dst,
                "after_task": x.after_task, "deadline_s": x.deadline_s,
                "path": list(x.path), "priority": x.priority, "start_s": x.start_s,
                "status": status, "remaining_bytes": x.remaining,
                "failed_attempts": x.failed_attempts,
                "ready": x.status in (QUEUED, ACTIVE, SENT, ARRIVED),
            })
        return out

    def tasks(self) -> dict[str, dict[str, Any]]:
        sim = self._sim
        out = {}
        for tid, t in sim.workflow["tasks"].items():
            k = sim.tasks[tid]
            out[tid] = {"site": t["site"], "runtime_s": t["runtime_s"], "parents": list(t["parents"]),
                        "earliest_finish_s": t["earliest_finish_s"], "latest_start_s": t["latest_start_s"],
                        "status": k.status,
                        "start_s": None if math.isnan(k.start_t) else k.start_t,
                        "finish_s": None if math.isnan(k.finish_t) else k.finish_t}
        return out

    def plan(self) -> Plan:
        return {x.id: {"path": list(x.path), "priority": x.priority, "start_s": x.start_s}
                for x in self._sim.transfers}

    def finished_ids(self) -> set[str]:
        return self._sim._finished_ids()

    def requirements(self) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self._sim.req.items()}

    def forecast(self, plan: Plan, horizon_s: float | None = None) -> dict[str, Any]:
        return self._sim.forecast(plan, horizon_s)
