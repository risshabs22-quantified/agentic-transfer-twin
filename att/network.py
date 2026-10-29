"""Part 2: the SYNTHETIC network -- topology, background load, and scenario events.

Picture a highway map: sites are cities, links are highways with a number of lanes (Gbps) and a
driving time (one-way delay in ms). Other traffic (the "background load") takes up some lanes,
and it rises and falls over time. A scenario can add a traffic jam (a "surge") or close a
highway (a link going "down") for part of the run.

Everything here is synthetic: the map, its numbers, the load model and the events are invented
for the experiment and are labeled that way in the docs.

Units: capacity in Gbps = 1e9 bits/s; we convert to BYTES/s (divide by 8) because file sizes
are bytes. Times are seconds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import yaml

MAX_LOAD = 0.95  # background load is clipped here, so a link that is up always has >= 5% free


def gbps_to_bytes_per_s(gbps: float) -> float:
    """Gbps (10^9 bits/s) -> bytes/s. The classic 8x bug lives here, so it has one home."""
    return gbps * 1e9 / 8


# --------------------------------------------------------------------------------------------
# Topology
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Link:
    """One undirected link. Both directions share the same capacity (a simplification)."""
    a: str
    b: str
    gbps: float
    ms: float

    @property
    def ends(self) -> list[str]:
        return [self.a, self.b]


@dataclass
class Topology:
    """Sites + links, with fast lookups from a site pair to a link index.

    Links are kept in the order they appear in topology.yaml; that fixed order is what makes
    every per-link loop (and every random draw per link) deterministic.
    """
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
        """Index of the link between u and v (either order). KeyError if there is none."""
        return self._index[(u, v)]

    def has_link(self, u: str, v: str) -> bool:
        return (u, v) in self._index

    def path_links(self, path: list[str]) -> list[int]:
        """Link indices along a path of site names."""
        return [self._index[(u, v)] for u, v in zip(path, path[1:])]

    def path_delay_s(self, path: list[str]) -> float:
        """Total one-way propagation delay of a path, in seconds."""
        return sum(self.links[i].ms for i in self.path_links(path)) / 1000.0

    def capacity_Bps(self, i: int) -> float:
        """Full capacity of link i in bytes/s."""
        return gbps_to_bytes_per_s(self.links[i].gbps)

    def shortest_path(self, src: str, dst: str) -> list[str]:
        """Lowest-delay path (the baseline's choice)."""
        return list(nx.shortest_path(self.graph, src, dst, weight="ms"))

    def k_shortest_paths(self, src: str, dst: str, k: int, avoid: set[int] | None = None) -> list[list[str]]:
        """Up to k simple paths, lowest total delay first, optionally avoiding some links.

        networkx breaks ties between equal-delay paths deterministically for a fixed graph,
        and the graph is always built in the same order, so the result is repeatable.
        """
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


# --------------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Background:
    """Parameters of the background load (all times as fractions of D)."""
    mean: float = 0.2
    wave: float = 0.1
    period_frac: float = 0.5
    noise: float = 0.05
    interval_frac: float = 0.005


@dataclass(frozen=True)
class NetEvent:
    """One scenario event that switches on and off: a surge or an outage on one link."""
    type: str            # "surge" or "down"
    link: tuple[str, str]
    start_frac: float
    end_frac: float
    extra_load: float = 0.0  # only for surges


def load_scenarios(path: str | Path) -> tuple[Background, dict[str, list[NetEvent]]]:
    """Read scenarios.yaml -> (background params, {scenario name: [events]})."""
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
    """A scenario event edge at an absolute time, as the simulator processes it."""
    t: float
    type: str        # "link_down" | "link_up" | "surge_start" | "surge_end"
    link: int        # link index
    extra_load: float = 0.0


def timeline(events: list[NetEvent], topo: Topology, deadline_s: float) -> list[TimedEvent]:
    """Turn fractional scenario events into a time-sorted list of on/off edges.

    Ties at the same time are ordered "off" edges first (link_up, surge_end) and then by
    the event's position in the config, so the order never depends on anything random.
    """
    edges: list[tuple[float, int, int, TimedEvent]] = []
    for pos, ev in enumerate(events):
        i = topo.link_index(*ev.link)
        on, off = ("link_down", "link_up") if ev.type == "down" else ("surge_start", "surge_end")
        edges.append((ev.start_frac * deadline_s, 1, pos, TimedEvent(ev.start_frac * deadline_s, on, i, ev.extra_load)))
        edges.append((ev.end_frac * deadline_s, 0, pos, TimedEvent(ev.end_frac * deadline_s, off, i, ev.extra_load)))
    edges.sort(key=lambda x: (x[0], x[1], x[2]))
    return [e[3] for e in edges]


# --------------------------------------------------------------------------------------------
# Background load (the "other traffic" on each link)
# --------------------------------------------------------------------------------------------

class BackgroundLoad:
    """Pre-generated background load for one run, on a fixed time grid of width dt.

    Load is re-sampled at the start of every grid cell [k*dt, (k+1)*dt) and held constant
    inside it. All random numbers (one phase per link, one noise value per link per noise
    interval) are drawn ONCE, up front, from one seeded RNG, so nothing a planner does can
    change them.
    """

    def __init__(self, topo: Topology, bg: Background, deadline_s: float, dt: float,
                 max_time_s: float, seed: int):
        self.dt = dt
        self.n_links = len(topo.links)
        self.n_cells = int(math.ceil(max_time_s / dt)) + 2
        rng = np.random.default_rng(seed)
        # Draw order is fixed: all phases first, then the noise table, link by link.
        self.phase = rng.uniform(0.0, 2.0 * math.pi, size=self.n_links)
        interval = bg.interval_frac * deadline_s
        n_noise = int(math.ceil(max_time_s / interval)) + 2 if bg.noise > 0 else 1
        noise = (rng.normal(0.0, bg.noise, size=(self.n_links, n_noise)) if bg.noise > 0
                 else np.zeros((self.n_links, 1)))
        k = np.arange(self.n_cells)
        t = k * dt  # start time of each cell
        # A tiny epsilon keeps floor() stable when t is an exact multiple of the interval.
        noise_idx = np.minimum(np.floor(t / interval + 1e-9).astype(int), noise.shape[1] - 1) \
            if bg.noise > 0 else np.zeros_like(k)
        period = bg.period_frac * deadline_s
        wave = bg.wave * np.sin(2.0 * math.pi * t[None, :] / period + self.phase[:, None])
        # Unclipped base load; surges are added and the sum clipped in load().
        self.base = bg.mean + wave + noise[:, noise_idx]

    def load(self, link: int, cell: int, extra: float = 0.0) -> float:
        """Background load fraction on `link` during grid cell `cell`, plus any surge, clipped."""
        cell = min(cell, self.n_cells - 1)
        return float(min(max(self.base[link, cell] + extra, 0.0), MAX_LOAD))


def free_capacity_Bps(topo: Topology, load: BackgroundLoad, cell: int,
                      surge_extra: list[float], down: list[bool]) -> list[float]:
    """Free capacity of every link (bytes/s) in a grid cell, given which links are down/surged."""
    out = []
    for i in range(len(topo.links)):
        if down[i]:
            out.append(0.0)
        else:
            out.append(topo.capacity_Bps(i) * (1.0 - load.load(i, cell, surge_extra[i])))
    return out


def state_at(events: list[TimedEvent], n_links: int, t: float) -> tuple[list[float], list[bool]]:
    """Which links are surged / down at time t (events that started at or before t and
    have not yet ended). Used for printing and tests; the simulator tracks this incrementally."""
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
