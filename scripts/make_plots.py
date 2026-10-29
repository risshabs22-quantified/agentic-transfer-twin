"""Make the two result plots from results/summary.csv.

  results/completion_time.png  grouped bars (scenario x planner), mean ± std over seeds, one panel per workflow
  results/failures.png         late transfers and failed transfers, same layout

Titles are computed from the data so they state the finding. Colors follow the planner (never its
rank): baseline blue, baseline_reroute orange, agents aqua -- a palette checked for color-vision
deficiency with the dataviz validator. Values are printed on the bars, so color is never the only cue.

Usage:
    python scripts/make_plots.py
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.make_tables import NICE, PLANNERS, RESULTS, SCEN_ORDER, cell, load  # noqa: E402

COLORS = {"baseline": "#2a78d6", "baseline_reroute": "#eb6834", "agents": "#1baf7a"}
INK, MUTED, GRID = "#1f1f1e", "#5f5e58", "#e4e3df"
plt.rcParams.update({
    "font.size": 10, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": MUTED,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.grid.axis": "y",
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True, "figure.facecolor": "#fcfcfb",
    "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
})


def grouped(ax, df, w, col, fmt, scale=1.0):
    """Grouped bars: x = scenario, one bar per planner, error bar = std over seeds."""
    width = 0.26
    x = np.arange(len(SCEN_ORDER))
    for i, p in enumerate(PLANNERS):
        means = [cell(df, w, s, p)[col].mean() * scale for s in SCEN_ORDER]
        sds = [cell(df, w, s, p)[col].std(ddof=1) * scale for s in SCEN_ORDER]
        pos = x + (i - 1) * (width + 0.02)  # small gap between neighbouring bars
        ax.bar(pos, means, width, yerr=sds, color=COLORS[p], label=p, capsize=3,
               error_kw={"elinewidth": 1, "ecolor": MUTED, "capthick": 1})
        for xp, mval, sd in zip(pos, means, sds):
            ax.text(xp, mval + sd + ax.get_ylim()[1] * 0.0, format(mval, fmt), ha="center", va="bottom",
                    fontsize=7.5, color=INK)
    ax.set_xticks(x, [NICE[s] for s in SCEN_ORDER])


def completion_plot(df) -> None:
    wfs = list(dict.fromkeys(df.workflow))
    fig, axes = plt.subplots(1, len(wfs), figsize=(11, 5.2))
    for ax, w in zip(axes, wfs):
        D = df.attrs["D"][w]
        grouped(ax, df, w, "completion_s", ".0f" if D > 100 else ".1f")
        ax.axhline(D, color=INK, linestyle="--", linewidth=1, label="deadline D")
        ax.set_ylabel("Workflow completion time (s)")
        ax.set_ylim(0, max(cell(df, w, s, p).completion_s.max() for s in SCEN_ORDER for p in PLANNERS) * 1.15)
        fastest = all(cell(df, w, s, "agents").completion_s.mean() <= min(cell(df, w, s, p).completion_s.mean()
                                                                          for p in PLANNERS) for s in SCEN_ORDER)
        lf = {p: cell(df, w, "link_failure", p).completion_s.mean() for p in PLANNERS}
        title = (f"{NICE[w]} (data ×{df.attrs['scale'][w]}): the link failure costs the baseline "
                 f"{lf['baseline'] / D - cell(df, w, 'normal', 'baseline').completion_s.mean() / D:+.2f} D"
                 + ("; agents fastest in every scenario" if fastest else ""))
        ax.set_title(textwrap.fill(title, 60), fontsize=9.5, color=INK)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, frameon=False, fontsize=9, loc="lower center", ncol=4)
    G = "1000genome-8ch"
    gc = {p: cell(df, G, "congestion", p).completion_s.mean() / df.attrs["D"][G] for p in PLANNERS}
    fig.suptitle(f"Rerouting fixes most of an outage; under congestion only the agents help "
                 f"({NICE[G]}: {gc['baseline_reroute']:.2f} D with rerouting vs. {gc['agents']:.2f} D with agents)\n"
                 f"Mean ± std over 10 seeds; SYNTHETIC network", fontsize=10.5, color=INK)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(RESULTS / "completion_time.png", dpi=150, metadata={"Software": None})
    plt.close(fig)


def failures_plot(df) -> None:
    wfs = list(dict.fromkeys(df.workflow))
    fig, axes = plt.subplots(2, len(wfs), figsize=(11, 6.4))
    for j, w in enumerate(wfs):
        for i, (col, label) in enumerate([("late", "Late transfers per run"),
                                          ("failed_transfers", "Failed transfers per run")]):
            ax = axes[i, j]
            top = max(cell(df, w, s, p)[col].max() for s in SCEN_ORDER for p in PLANNERS)
            ax.set_ylim(0, max(top * 1.2, 1))
            grouped(ax, df, w, col, ".1f")
            ax.set_ylabel(f"{label} (count)")
            if i == 0:
                ax.set_title(NICE[w], fontsize=10, color=INK)
    axes[0, 0].legend(frameon=False, fontsize=8.5, loc="upper left")
    late_agents = df[df.planner == "agents"].late.sum()
    fail_agents = df[df.planner == "agents"].failed_transfers.sum()
    fig.suptitle(f"The baseline misses deadlines and times out under the link failure; the agents had {late_agents} late "
                 f"and {fail_agents} failed transfers across all 60 of their runs\n"
                 f"Mean ± std over 10 seeds; SYNTHETIC network",
                 fontsize=10.5, color=INK)
    fig.tight_layout()
    fig.savefig(RESULTS / "failures.png", dpi=150, metadata={"Software": None})
    plt.close(fig)


def main() -> None:
    df = load()
    completion_plot(df)
    failures_plot(df)
    print("wrote results/completion_time.png, results/failures.png")


if __name__ == "__main__":
    main()
