from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import yaml

MAX_LOAD = 0.95


def gbps_to_bytes_per_s(gbps: float) -> float:
    return gbps * 1e9 / 8


@dataclass(frozen=True)
class Link:
    a: str
    b: str
    gbps: float
    ms: float

    @property
    def ends(self) -> list[str]:
        return [self.a, self.b]


@dataclass
class Topology:
    sites: list[str]
    links: list[Link]
    graph: nx.Graph = field(init=False, repr=False)
    _index: dict[tuple[str, str], int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.graph = nx.Graph()
        self.graph.add_nodes_from(self.sites)
        self._index = {}
        for i, ln in enumerate(self.links):
            self.graph.add_edge(ln.a, ln.b, ms=ln.ms, gbps=ln.gbps, index=i)
            self._index[(ln.a, ln.b)] = i
            self._index[(ln.b, ln.a)] = i

    def link_index(self, u: str, v: str) -> int:
        return self._index[(u, v)]

    def has_link(self, u: str, v: str) -> bool:
        return (u, v) in self._index

    def path_links(self, path: list[str]) -> list[int]:
        return [self._index[(u, v)] for u, v in zip(path, path[1:])]

    def path_delay_s(self, path: list[str]) -> float:
        return sum(self.links[i].ms for i in self.path_links(path)) / 1000.0

    def capacity_Bps(self, i: int) -> float:
        return gbps_to_bytes_per_s(self.links[i].gbps)

    def shortest_path(self, src: str, dst: str) -> list[str]:
        return list(nx.shortest_path(self.graph, src, dst, weight="ms"))

    def k_shortest_paths(self, src: str, dst: str, k: int, avoid: set[int] | None = None) -> list[list[str]]:
        g = self.graph
        if avoid:
            g = g.copy()
            g.remove_edges_from([self.links[i].ends for i in sorted(avoid)])
        if src not in g or dst not in g or not nx.has_path(g, src, dst):
            return []
        out: list[list[str]] = []
        for p in nx.shortest_simple_paths(g, src, dst, weight="ms"):
            out.append(list(p))
            if len(out) >= k:
                break
        return out


def load_topology(path: str | Path) -> Topology:
    with open(path) as fh:
        d = yaml.safe_load(fh)
    links = [Link(str(x["a"]), str(x["b"]), float(x["gbps"]), float(x["ms"])) for x in d["links"]]
    return Topology(sites=[str(s) for s in d["sites"]], links=links)


@dataclass(frozen=True)
class Background:
    mean: float = 0.2
    wave: float = 0.1
    period_frac: float = 0.5
    noise: float = 0.05
    interval_frac: float = 0.005


@dataclass(frozen=True)
class NetEvent:
    type: str
    link: tuple[str, str]
    start_frac: float
    end_frac: float
    extra_load: float = 0.0


def load_scenarios(path: str | Path) -> tuple[Background, dict[str, list[NetEvent]]]:
    with open(path) as fh:
        d = yaml.safe_load(fh)
    bg = Background(**d["background"])
    scenarios: dict[str, list[NetEvent]] = {}
    for name, body in d.items():
        if name == "background":
            continue
        scenarios[name] = [parse_event(e) for e in (body or {}).get("events", [])]
    return bg, scenarios


def parse_event(e: dict[str, Any]) -> NetEvent:
    if e["type"] not in ("surge", "down"):
        raise ValueError(f"unknown event type {e['type']!r}")
    return NetEvent(type=e["type"], link=(str(e["link"][0]), str(e["link"][1])),
                    start_frac=float(e["start_frac"]), end_frac=float(e["end_frac"]),
                    extra_load=float(e.get("extra_load", 0.0)))


@dataclass(frozen=True)
class TimedEvent:
    t: float
    type: str
    link: int
    extra_load: float = 0.0


def timeline(events: list[NetEvent], topo: Topology, deadline_s: float) -> list[TimedEvent]:
    edges: list[tuple[float, int, int, TimedEvent]] = []
    for pos, ev in enumerate(events):
        i = topo.link_index(*ev.link)
        on, off = ("link_down", "link_up") if ev.type == "down" else ("surge_start", "surge_end")
        edges.append((ev.start_frac * deadline_s, 1, pos, TimedEvent(ev.start_frac * deadline_s, on, i, ev.extra_load)))
        edges.append((ev.end_frac * deadline_s, 0, pos, TimedEvent(ev.end_frac * deadline_s, off, i, ev.extra_load)))
    edges.sort(key=lambda x: (x[0], x[1], x[2]))
    return [e[3] for e in edges]


class BackgroundLoad:
    def __init__(self, topo: Topology, bg: Background, deadline_s: float, dt: float,
                 max_time_s: float, seed: int):
        self.dt = dt
        self.n_links = len(topo.links)
        self.n_cells = int(math.ceil(max_time_s / dt)) + 2
        rng = np.random.default_rng(seed)
        self.phase = rng.uniform(0.0, 2.0 * math.pi, size=self.n_links)
        interval = bg.interval_frac * deadline_s
        n_noise = int(math.ceil(max_time_s / interval)) + 2 if bg.noise > 0 else 1
        noise = (rng.normal(0.0, bg.noise, size=(self.n_links, n_noise)) if bg.noise > 0
                 else np.zeros((self.n_links, 1)))
        k = np.arange(self.n_cells)
        t = k * dt
        noise_idx = np.minimum(np.floor(t / interval + 1e-9).astype(int), noise.shape[1] - 1) \
            if bg.noise > 0 else np.zeros_like(k)
        period = bg.period_frac * deadline_s
        wave = bg.wave * np.sin(2.0 * math.pi * t[None, :] / period + self.phase[:, None])
        self.base = bg.mean + wave + noise[:, noise_idx]

    def load(self, link: int, cell: int, extra: float = 0.0) -> float:
        cell = min(cell, self.n_cells - 1)
        return float(min(max(self.base[link, cell] + extra, 0.0), MAX_LOAD))


def free_capacity_Bps(topo: Topology, load: BackgroundLoad, cell: int,
                      surge_extra: list[float], down: list[bool]) -> list[float]:
    out = []
    for i in range(len(topo.links)):
        if down[i]:
            out.append(0.0)
        else:
            out.append(topo.capacity_Bps(i) * (1.0 - load.load(i, cell, surge_extra[i])))
    return out


def state_at(events: list[TimedEvent], n_links: int, t: float) -> tuple[list[float], list[bool]]:
    extra = [0.0] * n_links
    down = [False] * n_links
    for ev in events:
        if ev.t > t:
            break
        if ev.type == "surge_start":
            extra[ev.link] += ev.extra_load
        elif ev.type == "surge_end":
            extra[ev.link] -= ev.extra_load
        elif ev.type == "link_down":
            down[ev.link] = True
        elif ev.type == "link_up":
            down[ev.link] = False
    return extra, down
