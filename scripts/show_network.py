"""Print each link's free capacity at a few moments in each scenario (a quick sanity check of the network model).

Usage:
    python scripts/show_network.py [--workflow 1000genome-8ch] [--seed 100]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from att import config  # noqa: E402
from att.extract import extract_transfers  # noqa: E402
from att.network import BackgroundLoad, free_capacity_Bps, state_at, timeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", default="1000genome-8ch")
    ap.add_argument("--seed", type=int, default=100)
    args = ap.parse_args()

    exp = config.load_experiment()
    topo = config.topology()
    bg, _ = config.scenarios()
    ex = extract_transfers(config.workflow_path(exp, args.workflow), exp["sites"], exp["source_site"],
                           exp["slack"], args.seed)
    D = ex["deadline_s"]
    sim = exp["simulator"]
    dt = D / sim["steps_per_deadline"]
    load = BackgroundLoad(topo, bg, D, dt, sim["max_time_frac"] * D, args.seed)
    print(f"{args.workflow}: D = {D:.3f} s, dt = {dt:.4f} s, seed {args.seed}  (SYNTHETIC network)")
    fracs = [0.0, 0.04, 0.06, 0.1, 0.14, 0.16, 0.2, 0.49, 0.51, 0.74, 0.76]
    for scen in exp["scenarios"]:
        events = timeline(config.scenario_events(exp, args.workflow, scen), topo, D)
        print(f"\n== {scen}: " + (", ".join(f"{e.type}@{e.t / D:.2f}D {topo.links[e.link].a}-{topo.links[e.link].b}"
                                            for e in events) or "no events"))
        header = "t/D    " + " ".join(f"{ln.a[:4]}-{ln.b[:4]}".rjust(11) for ln in topo.links)
        print(header + "   (free Gbps)")
        for f in fracs:
            t = f * D
            extra, down = state_at(events, len(topo.links), t)
            free = free_capacity_Bps(topo, load, int(t / dt + 1e-9), extra, down)
            print(f"{f:5.2f}  " + " ".join(f"{x * 8 / 1e9:11.1f}" for x in free))


if __name__ == "__main__":
    main()
