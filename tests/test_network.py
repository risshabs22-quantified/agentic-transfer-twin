"""Stage 2: topology, background load, and scenario events."""
import numpy as np
import pytest

from att import config
from att.network import (MAX_LOAD, Background, BackgroundLoad, NetEvent, free_capacity_Bps,
                         gbps_to_bytes_per_s, state_at, timeline)


@pytest.fixture(scope="module")
def topo():
    return config.topology()


def test_units():
    assert gbps_to_bytes_per_s(100) == 12.5e9  # 100 Gbps = 12.5 GB/s


def test_topology_paths(topo):
    assert topo.shortest_path("CERN", "Caltech") == ["CERN", "StarLight", "Caltech"]
    # UCSD is reached fastest through Caltech (145 ms) rather than FNAL (147 ms)
    assert topo.shortest_path("CERN", "UCSD") == ["CERN", "StarLight", "Caltech", "UCSD"]
    assert topo.path_delay_s(["CERN", "StarLight", "Caltech", "UCSD"]) == pytest.approx(0.145)
    paths = topo.k_shortest_paths("CERN", "ORNL", k=3)
    assert paths[0] == ["CERN", "StarLight", "ORNL"]
    assert paths[1] == ["CERN", "StarLight", "FNAL", "ORNL"]
    sl_cal = topo.link_index("Caltech", "StarLight")
    for p in topo.k_shortest_paths("CERN", "Caltech", k=3, avoid={sl_cal}):
        assert sl_cal not in topo.path_links(p)


def test_events_switch_at_right_fractions(topo):
    D = 200.0
    _, scen = config.scenarios()
    ev = timeline(scen["link_failure"], topo, D)
    assert [(e.type, e.t) for e in ev] == [("link_down", 0.15 * D), ("link_up", 0.75 * D)]
    i = topo.link_index("StarLight", "Caltech")
    for t, expect_down in [(0.0, False), (0.149 * D, False), (0.15 * D, True), (0.5 * D, True),
                           (0.749 * D, True), (0.75 * D, False), (D, False)]:
        _, down = state_at(ev, len(topo.links), t)
        assert down[i] is expect_down, t
    ev = timeline(scen["congestion"], topo, D)
    j = topo.link_index("StarLight", "ORNL")
    assert [(e.type, e.t) for e in ev] == [("surge_start", 0.05 * D), ("surge_end", 0.5 * D)]
    assert state_at(ev, len(topo.links), 0.3 * D)[0][j] == pytest.approx(0.7)
    assert state_at(ev, len(topo.links), 0.6 * D)[0][j] == 0.0


def test_background_deterministic_and_seeded(topo):
    bg = Background()
    a = BackgroundLoad(topo, bg, 100.0, 0.1, 2000.0, seed=5)
    b = BackgroundLoad(topo, bg, 100.0, 0.1, 2000.0, seed=5)
    c = BackgroundLoad(topo, bg, 100.0, 0.1, 2000.0, seed=6)
    assert np.array_equal(a.base, b.base)
    assert not np.array_equal(a.base, c.base)
    # mean load is close to the configured mean over a long run
    assert abs(a.base.mean() - bg.mean) < 0.02


def test_load_is_clipped_and_noise_piecewise_constant(topo):
    bg = Background(mean=0.2, wave=0.0, noise=0.05, interval_frac=0.005)
    load = BackgroundLoad(topo, bg, 100.0, 0.1, 2000.0, seed=1)  # 5 cells per noise interval
    for k0 in range(0, 50, 5):
        assert len(set(load.base[0, k0:k0 + 5].tolist())) == 1
    assert load.load(0, 0, extra=5.0) == MAX_LOAD
    assert load.load(0, 0, extra=-5.0) == 0.0


def test_free_capacity_down_and_surge(topo):
    bg = Background(mean=0.0, wave=0.0, noise=0.0)
    load = BackgroundLoad(topo, bg, 100.0, 0.1, 2000.0, seed=0)
    n = len(topo.links)
    free = free_capacity_Bps(topo, load, 0, [0.0] * n, [False] * n)
    assert free == [topo.capacity_Bps(i) for i in range(n)]
    extra = [0.0] * n
    extra[3] = 0.7
    down = [False] * n
    down[2] = True
    free = free_capacity_Bps(topo, load, 0, extra, down)
    assert free[2] == 0.0
    assert free[3] == pytest.approx(topo.capacity_Bps(3) * 0.3)


def test_unknown_event_type_rejected():
    from att.network import parse_event
    with pytest.raises(ValueError):
        parse_event({"type": "meteor", "link": ["A", "B"], "start_frac": 0, "end_frac": 1})
    assert isinstance(parse_event({"type": "down", "link": ["A", "B"], "start_frac": 0, "end_frac": 1}), NetEvent)
