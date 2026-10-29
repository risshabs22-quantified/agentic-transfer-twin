# Build log

Running record of how this repo was built, stage by stage (see `CLAUDE.md` section 17).
Every entry says what was built, why, and the commands to verify it.

## Progress

- [x] Stage 0 — environment, requirements, data, build log
- [x] Stage 1 — extraction (`att/extract.py`)
- [x] Stage 2 — configs + network model (`att/network.py`)
- [x] Stage 3 — simulator, planner interface, baselines
- [x] Stage 4 — tuning (baseline only) + freeze `configs/experiment.yaml`
- [x] Stage 5 — tools, MCP server, tool client, stdio demo
- [x] Stage 6 — agents + event handling, agent tuning on dev workflows
- [ ] Stage 7 — decision log, replay, experiment runner (180 runs)
- [ ] Stage 8 — tables, plots, README, write-up
- [ ] Stage 9 — `docs/HOW_IT_WORKS.md`
- [ ] Stage 10 — fresh-clone reproduction check

## Deviations

Changes from `CLAUDE.md`, with why each one is better and how to check it.

| # | Stage | What changed | Why | How to check |
|---|---|---|---|---|
| 1 | 3 | **Exact event-driven simulator** instead of fixed `dt` steps. Capacity is still piecewise constant on the `dt = D/1000` grid (load sampled at each cell start, exactly as specified), but the clock jumps from one interesting moment to the next (grid boundary while something is moving, task finish, arrival, planned start, scenario event, last byte sent, stall timeout). | Completion, arrival and failure times are exact for the capacity model instead of rounded up to a step; idle stretches (only tasks running) cost nothing; a full 8ch run takes ~0.03 s. | `tests/test_simulator.py::test_units_sanity` (0.81 s arrival, exact), `test_priority_shares_capacity_two_to_one` (1.2 s / 1.6 s exactly). |
| 2 | 3 | **Stall timeout counts *consecutive* stall time**: the timer resets when the transfer moves again or is given a new path. | CLAUDE.md says stall time "accumulates" but not whether it resets; a timeout in real transfer tools (and TCP) is time without progress, so short separate stalls should not add up to a failure. | `test_stall_shorter_than_timeout_does_not_fail`, `test_failure_path_counts_transfer_once`. |
| 3 | 3 | **Rerouting keeps the bytes already sent** (like restart markers in GridFTP); only a *failed attempt* resets to the full size, as specified. | Otherwise a reroute would be punished like a failure, which would bias against any planner that reroutes. Applies identically to every planner. | `att/simulator.py::_apply`. |
| 4 | 3 | **Extra validation rule:** plan entries for transfers that have already sent all their bytes are rejected ("transfer already sent all its bytes"). Transfers missing from the initial plan get the default entry (lowest-delay path, priority 1, start 0). | Changing a finished transfer has no effect and would inflate `reroutes`. The default makes a partial plan safe. Both apply to every planner and to `submit_plan`. | `tests/test_planner.py`, `test_invalid_entries_rejected_and_logged`. |
| 5 | 3 | **Every planner call is logged as a decision, including "no change"**, so `decisions` = 1 + number of events delivered. | Replay must check every event against the log (type, seq, t); logging only non-empty answers would make that impossible. | `sim.decisions` length vs. events in `test_failure_path_counts_transfer_once`. |
| 6 | 3 | `avg_gbps` is NaN when a run doesn't complete (same as `completion_s`). Ties at one instant are processed in a fixed order: last bytes sent → arrivals → task finishes → planned starts → scenario events → timeouts. | Keeps metrics well defined and the run deterministic. | `att/simulator.py::_process_instant`. |
| 7 | 3 | Added `att/config.py` (YAML loading) and `att/runner.py` (`build_sim`, `run_one`, `run_id`) to the layout. | One place builds a run, so experiments, tuning, tests and replay can't drift apart. | — |
| 8 | 3 | **Float guard:** if a transfer's remaining bytes are too small to move the clock (`t + remaining/rate == t`), it is finished now. | Found while testing: a 1.7e-5-byte remainder at 10 GB/s gives a 1.6e-15 s step, which is below float resolution at t = 51 s, so the loop never advanced. | `att/simulator.py::_loop`. |
| 9 | 4 | Added an optional per-link byte counter (`Simulator.count_window`) used only by `tune.py` for step (a). | Step (a) needs "the link that carries the most baseline bytes during the event window"; measuring it inside the simulator is exact. It is off (None) in every experiment run. | `scripts/tune.py::busiest_link_in_window`. |
| 10 | 5 | Tools additions: batch tools `get_paths_many` and `estimate_many` (CLAUDE.md allows these); `get_paths(..., avoid_down=False)` option; `get_workflow_requirements` adds `data_ready_s` (best present estimate of when a transfer's data exists, from task status and trace runtimes); "never"/"unknown" are returned as `null` because MCP output must be valid JSON (NaN/inf are not). | Fewer round trips per decision; agents need readiness to compute slack; the SDK rejects NaN in structured output (verified). | `tests/test_tools.py`. |
| 11 | 5 | The module-level demo server `att.mcp_server.mcp` is built lazily (module `__getattr__`) rather than at import time. | Importing `build_server` in every experiment run would otherwise build a throwaway demo twin each time. `python -m att.mcp_server` and `getattr(module, "mcp")` (what `mcp dev` uses) still work. | `python scripts/mcp_demo_client.py`. |
| 12 | 5 | `Simulator.run` split into `start(planner)` (t = 0 setup + initial plan) and the main loop. | The demo server and tests need a twin "at t = 0 with a plan in place" without running it. | `tests/test_tools.py`. |
| 13 | 6 | **Coordinator forecasts three drafts, not two**: load-balanced, the network agent's fastest-route draft, *and* the simple lowest-delay draft. It keeps the best forecast, but leaves the lowest-delay draft only if another is forecast at least `draft_margin` (tuned: 5%) faster. | On dev Montage (tuning seeds) the two specified drafts were both *worse* than the baseline in `normal` (1.010 D and 1.158 D vs 0.962 D): time-blind balancing pushes small files onto 3-hop routes, and "everyone takes the fastest route" herds them onto one link. Persistence forecasts are only accurate to a few %, so a small forecast gain is noise; the margin is a principled hysteresis. With it: 0.966 D. | `results/tuning/agent_tuning.json`; `AgentTeam(drafts=...)` reproduces each variant. |
| 14 | 6 | **Event handling details:** every event also refreshes priorities (slack changes over time); `link_up`/`surge_end` consider moving back *any* unfinished transfer that could use the restored link (not only not-yet-started ones), because rerouting keeps bytes already sent (Deviation 3); a transfer is moved only if its projected load drops by `move_margin` (tuned: 10%) or its route is down; and the whole change is kept only if a `simulate_plan` forecast says it is no worse than keeping the current plan. | Avoids churn from tiny projected gains, and the forecast gate stops changes that look good locally but hurt overall. | `att/agents/coordinator.py::_react`. |
| 15 | 6 | Agent parameters tuned: `priority_fraction` ∈ {0.1, 0.2, 0.3, 0.5}, `move_margin` ∈ {0, 0.1, 0.25}, `draft_margin` ∈ {0, 0.05, 0.1}, on the 2 dev workflows × 3 scenarios × tuning seeds 100–104 (36 configs). `busy_threshold` (0.3) and `k_paths` (3) kept as specified. | CLAUDE.md allows tuning agent parameters on dev workflows only; the grid is small and fully logged. | `python scripts/tune_agents.py`. |
| 16 | 6 | The tool client tags every recorded call with the calling agent (`workflow_agent` / `network_agent` / `coordinator`). | The decision log then shows which agent asked what. | `tests/test_agents.py`. |

## Tuning table

Baseline only, tuning seeds 100–104, means over the 5 seeds. Source: `results/tuning/tuning.json` (from `python scripts/tune.py --write`).

**Step 1: data_scale sweep in `normal`** (cell = mean completion / D, mean late as % of transfers; rule: completion ≤ 1.0 D and late ≤ 1%):

| Workflow | ×10 | ×20 | ×50 | ×100 | ×200 | ×300 | ×500 | ×1000 | chosen |
|---|---|---|---|---|---|---|---|---|---|
| 1000genome-2ch | 0.681 / 0.0% | 0.696 / 0.0% | 0.740 / 0.0% | 0.813 / 0.0% | 0.956 / 0.0% | 1.092 / 28.4% | 1.385 / 47.8% | 2.090 / 47.8% | **200** |
| montage-005d | 0.678 / 0.0% | 0.679 / 0.0% | 0.682 / 0.0% | 0.688 / 0.0% | 0.704 / 0.0% | 0.723 / 0.0% | 0.779 / 0.0% | 0.962 / 1.0% | **1000** |
| 1000genome-8ch | 0.694 / 0.0% | 0.722 / 0.0% | 0.819 / 0.0% | 0.973 / 0.3% | 1.289 / 33.1% | 1.602 / 55.4% | 2.233 / 73.8% | 3.797 / 79.6% | **100** |
| montage-01d | 0.679 / 0.0% | 0.680 / 0.0% | 0.685 / 0.0% | 0.700 / 0.0% | 0.773 / 0.0% | 0.859 / 0.0% | 1.017 / 3.5% | 1.453 / 54.8% | **300** |

**Step 2: stress check** (stressed = completion ≥ 1.10 × normal, or late + failed transfers > 0):

| Workflow | scale | normal (×D) | scenario | step | event | completion / D | late | failed transfers | stressed? |
|---|---|---|---|---|---|---|---|---|---|
| 1000genome-2ch | 200 | 0.956 | congestion | as configured | surge StarLight–ORNL +0.7 | 1.195 | 9.6 | 0.0 | yes |
| 1000genome-2ch | 200 | 0.956 | link_failure | as configured | down StarLight–Caltech | 1.678 | 21.0 | 7.4 | yes |
| montage-005d | 1000 | 0.962 | congestion | as configured | surge StarLight–ORNL +0.7 | 0.962 | 1.4 | 0.0 | yes |
| montage-005d | 1000 | 0.962 | link_failure | as configured | down StarLight–Caltech | 1.192 | 61.8 | 17.2 | yes |
| 1000genome-8ch | 100 | 0.973 | congestion | as configured | surge StarLight–ORNL +0.7 | 1.179 | 26.8 | 0.0 | yes |
| 1000genome-8ch | 100 | 0.973 | link_failure | as configured | down StarLight–Caltech | 1.711 | 95.4 | 33.8 | yes |
| montage-01d | 300 | 0.859 | congestion | as configured | surge StarLight–ORNL +0.7 | 0.859 | 0.0 | 0.0 | no |
| montage-01d | 300 | 0.859 | congestion | (a) moved to busiest link | surge StarLight–FNAL +0.7 | 0.859 | 0.0 | 0.0 | no |
| montage-01d | 300 | 0.859 | congestion | (b) extra_load 1.0 (load cap) | surge StarLight–FNAL +1.0 | 0.859 | 0.0 | 0.0 | no |
| montage-01d | 300 | 0.859 | congestion | (c) kept as configured; reported as a finding | — | — | — | — | no |
| montage-01d | 300 | 0.859 | link_failure | as configured | down StarLight–Caltech | 1.092 | 79.0 | 39.8 | yes |

---

## Entries

### 2026-10-29 — Stage 0: environment and data

**Built**
- Git repo on `main`, remote `origin` = `github.com/risshabs22-quantified/agentic-transfer-twin` (the remote was empty, so there were no existing README/LICENSE to keep).
- `.venv` with Python **3.12.14** (the system `python3` is 3.14; 3.12 is what CLAUDE.md recommends and has wheels for every dependency).
- `requirements.txt` pinning the exact installed versions of the direct dependencies:
  networkx 3.7, numpy 2.5.4, pandas 3.1.0, matplotlib 3.11.2, PyYAML 6.0.3, mcp[cli] 2.3.0, pytest 9.2.0.
- `pyproject.toml` holding only pytest config (`pythonpath = ["."]` so tests import `att` without installing it).
- `scripts/fetch_data.py`: downloads the 4 WfInstances traces + LICENSE into `data/raw/` (skips existing files; writes via a `.part` temp file so an interrupted download can't leave a corrupt file).
- `data/NOTICE.md`: credit, LGPL-3.0 note, citation, and what is synthetic.
- `tests/test_data.py`: data files parse and the license is present.

**Verified**
- MCP SDK 2.3.0 v2 API (`mcp.server.MCPServer`, `mcp.Client`) works in-process as CLAUDE.md describes.
  One detail found: a tool annotated `-> dict` returns `structured_content=None`; annotating
  `-> dict[str, Any]` returns the dict as structured content. Tools use the latter.
  In-process tool calls cost ~0.15 ms each, so per-call overhead is not a concern.

**How to verify**
```bash
python scripts/fetch_data.py   # prints "skip" for each file
pytest -q
```

### 2026-10-29 — Stage 1: extraction (`att/extract.py`)

**Built**
- The reference implementation from CLAUDE.md section 8, unchanged in behavior, split into small
  functions (`load_instance`, `place_tasks`, `topological_order`, `earliest_finish_times`,
  `latest_start_times`, `extract_transfers`, `summarize`).
- Extensions: `data_scale` (multiplies bytes, rounded to whole bytes; default 1 leaves sizes
  untouched), and the result now also carries `placement`, `tasks` (parents, children, inputs,
  outputs, runtime, site, earliest finish, latest start), `file_bytes`, and the settings used.
- `tests/test_extract.py`: the acceptance table, transfer invariants (`src != dst`, `bytes > 0`,
  unique ids, deadline within D, src = producer's site or CERN), `data_scale` scales bytes only,
  placement depends on seed, a hand-checked critical-path example, and cross-process
  determinism (two subprocesses with `PYTHONHASHSEED=1` and `98765` produce identical sha256
  digests of the full output).

**Result** (seed 0, slack 1.5, data_scale 1) — matches CLAUDE.md exactly:

| File | Transfers | GB moved | D (s) |
|---|---|---|---|
| 1000genome-chameleon-2ch-100k-001 | 62 | 8.67 | 307.029 |
| montage-chameleon-2mass-005d-001 | 140 | 0.34 | 32.078 |
| 1000genome-chameleon-8ch-100k-001 | 179 | 38.97 | 601.916 |
| montage-chameleon-2mass-01d-001 | 248 | 0.68 | 31.683 |

**How to verify**
```bash
pytest -q tests/test_extract.py
```

### 2026-10-29 — Stage 2: configs and network model (`att/network.py`)

**Built**
- `configs/topology.yaml`, `configs/scenarios.yaml` exactly as in CLAUDE.md section 9, with "SYNTHETIC" headers.
- `configs/experiment.yaml`: sites, source, slack, simulator settings, the four workflows
  (`data_scale: null` until Stage 4), scenarios, planners, seeds.
- `att/config.py`: loads the YAML files; supports per-workflow scenario overrides (in case
  Stage 4 has to move an event for one workflow).
- `att/network.py`:
  - `Topology` (networkx graph + link index lookups, path delay, lowest-delay path, k shortest
    simple paths optionally avoiding links). Links keep their YAML order so per-link loops and
    per-link random draws are deterministic.
  - `BackgroundLoad`: one seeded `numpy.random.default_rng(seed)`; draws all per-link phases,
    then the whole per-link noise table, up front. Load is sampled at the start of each grid
    cell of width `dt` and held for the cell; noise is constant over `interval_frac * D`.
  - `timeline()`: scenario events → time-sorted on/off edges (`link_down`/`link_up`,
    `surge_start`/`surge_end`) at `frac * D`.
  - `free_capacity_Bps()`: `gbps * 1e9 / 8 * (1 - load)`, or 0 when down.
- `scripts/show_network.py`: prints free Gbps per link at several fractions of D for each scenario.

**Result** (`python scripts/show_network.py`, 1000genome-8ch, seed 100): free capacity is
65–95 Gbps on the 100 G links and 255–400 Gbps on the 400 G links in normal; StarLight–ORNL drops
to ~5 Gbps (the 0.95 load cap) from 0.05 D to 0.5 D in `congestion`; StarLight–Caltech is 0 from
0.15 D to 0.75 D in `link_failure`. Events switch exactly at their fractions (tested).

Note: on this map the lowest-delay route from CERN to UCSD goes through Caltech (145 ms vs
147 ms via FNAL), so the `link_failure` event affects every transfer bound for Caltech *and*
UCSD; while it is down, the only way into {Caltech, UCSD} is the FNAL–UCSD link.

**How to verify**
```bash
python scripts/show_network.py
pytest -q tests/test_network.py
```

### 2026-10-29 — Stage 3: simulator, planner interface, baselines

**Built**
- `att/planner.py`: `Planner` base class (`plan`, `on_event`, and a `note` dict the planner fills
  with `agent`/`saw`/`tool_calls`/`reason` for the decision log) and `validate_entry` /
  `validate_plan`, shared by the simulator and (later) the `submit_plan` tool.
- `att/simulator.py`: `Simulator` (the twin) and `TwinView` (what planners see: the clock, link
  capacity/free capacity/up-down *now*, transfer and task status, the current plan). Semantics
  follow CLAUDE.md section 9 (see Deviations 1–6 for the details I had to choose).
  `snapshot()` copies the present into a new simulator with constant free capacity, down links
  kept down, no scenario events and no random numbers; `forecast(plan)` runs a plan on it.
- `att/baseline.py`: `Baseline` and `BaselineReroute`, as specified.
- `tests/test_simulator.py`, `tests/test_planner.py`: units sanity, failure path, stall
  shorter than the timeout, 2:1 priority sharing, rejected entries, delayed start, baseline
  completes 1000Genome 2ch/normal, reroute avoids the down link, forecasts don't change the
  run, forecasts ignore future events, max-time cut-off, and cross-process determinism (two
  `PYTHONHASHSEED`s, metrics and every decision identical).

**Smoke run** (tuning seed 100, baseline / baseline_reroute; completion as a fraction of D):

| Workflow | scale | normal | congestion | link_failure (base) | link_failure (reroute) |
|---|---|---|---|---|---|
| 1000genome-2ch | 1 | 0.668 | 0.668 | 1.240, 9 failed | 0.668 |
| 1000genome-8ch | 100 | 0.975 | 1.151, 23 late | 1.738, 39 failed, 102 late | 1.010, 2 late |
| montage-01d | 200 | 0.791 | 0.791 | 1.023, 43 failed | 0.891 |

These are close to the prototype numbers in CLAUDE.md (≈0.99 / 1.19 / 1.71 D for 8ch; ≈0.78 /
1.03 D for Montage, with congestion having no effect on Montage). Each run takes 0.01–0.05 s.

**How to verify**
```bash
pytest -q tests/test_simulator.py tests/test_planner.py
```

### 2026-10-29 — Stage 4: tuning (baseline only) and freezing `configs/experiment.yaml`

**Built**
- `scripts/tune.py`: applies the CLAUDE.md section 14 rule using only `baseline` and tuning
  seeds 100–104; writes `results/tuning/tuning.json`; `--write` freezes `data_scale` (and any
  scenario overrides) into `configs/experiment.yaml`, keeping the file's comments.
- `tests/test_config.py`: the frozen config equals what tuning chose; tuning and evaluation
  seeds don't overlap.

**Result** (full table under "Tuning table" above)
- `data_scale`: 1000genome-2ch **200**, montage-005d **1000**, 1000genome-8ch **100**, montage-01d **300**
  (the prototype guessed ~100 for 8ch and ~200 for Montage 0.1°; the rule picked 100 and 300 here).
- 1000Genome (both): both stress scenarios stress the baseline clearly (8ch: 0.973 D normal →
  1.179 D congestion, 1.711 D link_failure).
- montage-01d / `link_failure`: stressed (0.859 → 1.092 D, 79 late, 40 failed transfers).
- **montage-01d / `congestion`: not stressed, even after (a) moving the surge to the busiest link
  in its window (StarLight–FNAL) and (b) raising it to the load cap. Kept as configured (step c)
  and reported as a finding.** Why (checked by hand, seed 100): Montage moves ~9 GB at the very
  start and then almost nothing until ~0.5 D; ~124 GB becomes ready in 0.5–0.6 D, *after* the surge
  window (0.05–0.5 D) ends. A surge on StarLight–FNAL at the cap does delay 118 transfers by up
  to 0.4 s, but none of them is near its deadline (min slack 3.7 s), so completion barely moves.
  The rule does not allow moving the event in time, so I didn't.
- montage-005d (dev only) / `congestion`: passes the rule only formally — its *normal* run already
  has 1.4 late transfers on average, so "late + failed > 0" is true without any stress
  (completion 0.962 D in both). In practice congestion doesn't stress it either. It is only used
  for tuning agent parameters, not for results.

**How to verify**
```bash
python scripts/tune.py     # ~5 s; same numbers; doesn't touch experiment.yaml without --write
pytest -q tests/test_config.py
```

### 2026-10-29 — Stage 5: tools, MCP server, tool client, stdio demo

**Built**
- `att/tools.py`: `get_workflow_requirements`, `get_network_state`, `get_paths` (+ `get_paths_many`),
  `estimate_transfer_time` (+ `estimate_many`), `simulate_plan` (persistence forecast via
  `Simulator.snapshot()`), `submit_plan` (same validation as the simulator). Plain functions over
  a `TwinView`; JSON in, JSON out.
- `att/mcp_server.py`: `build_server(view) -> MCPServer` with one `@mcp.tool()` wrapper per tool;
  `python -m att.mcp_server` serves a demo twin (1000Genome 2ch, normal, seed 0, t = 0) over stdio.
- `att/tool_client.py`: `run_with_tools(server, fn)` opens ONE MCP client session inside ONE
  `asyncio.run` per decision and records every call (tool, args — long args as size + sha256 —
  and a one-line result summary). Errors from tools surface as `ToolCallError`.
- `scripts/mcp_demo_client.py`: starts the server as a separate process over stdio and calls
  every tool once.

**Verified**
- MCP SDK detail: sync tools run in a worker thread (anyio), one call at a time, so the twin is
  never touched concurrently; one `MCPServer` object can be reused across many `asyncio.run` calls.
- `tests/test_tools.py`: every tool in-process through MCP equals the direct call; every tool
  works over stdio in a subprocess; estimates and paths respect a down link; **no-peeking:**
  `simulate_plan` at t = 0 gives byte-identical output for `normal` and `link_failure` (the
  failure is scheduled in the future), while after the link goes down the forecast does show it.

**How to verify**
```bash
python scripts/mcp_demo_client.py
pytest -q tests/test_tools.py
npx @modelcontextprotocol/inspector python -m att.mcp_server    # optional, needs Node.js
```

### 2026-10-29 — Stage 6: agents and event handling; agent tuning on dev workflows

**Built**
- `att/agents/workflow_agent.py` (SciNet 2.2.1): earliest arrival = data-ready estimate +
  `estimate_transfer_time` on the lowest-delay route that is up; slack = deadline − earliest
  arrival; lowest-slack `priority_fraction` of unfinished transfers get priority 2, each with a
  one-line reason.
- `att/agents/network_agent.py` (SciNet 2.2.2/2.2.3): top-3 routes per transfer (none down),
  estimate on each, recommends the fastest, flags busy links (< 30% free).
- `att/agents/coordinator.py` (SciNet 2.2.6): `AgentTeam`, the team's `Planner`
  (name `agents`, mode `rule`). Initial plan by projected bottleneck load, three drafts compared
  by forecast (Deviation 13), `submit_plan`; targeted event handling (Deviation 14).
  Everything goes through MCP: each `plan()`/`on_event()` opens one in-process MCP session.
- `att/runner.py::make_planner` builds any planner from the frozen config.
- `scripts/tune_agents.py` → `results/tuning/agent_tuning.json`; chosen values frozen in
  `configs/experiment.yaml` under `agents:`.
- `tests/test_agents.py`: agents complete every scenario on both dev workflows with 0 rejected
  entries and use all three agents' tools; **structural no-peeking** (AST check: `att/agents/*`
  and `att/baseline.py` never import the simulator, network model, configs, runner, extractor or
  yaml, and agents never read `view.<anything>` — they only pass it to `build_server`); frozen
  params equal the tuning output; cross-process determinism of an agents run, including every
  tool call and reason.

**Tuning result** (dev workflows, tuning seeds; mean completion / D):
chosen `priority_fraction=0.3, move_margin=0.1, draft_margin=0.05` → 0.9136 D on average
(worst config in the grid: 0.9483 D).

| dev workflow / scenario | baseline | baseline_reroute | agents (chosen) |
|---|---|---|---|
| 1000genome-2ch / normal | 0.956 | 0.956 | 0.823 |
| 1000genome-2ch / congestion | 1.195 | 1.195 | 0.824 |
| 1000genome-2ch / link_failure | 1.678 | 0.965 | 0.826 |
| montage-005d / normal | 0.962 | 0.962 | 0.966 |
| montage-005d / congestion | 0.962 | 0.962 | 0.977 |
| montage-005d / link_failure | 1.192 | 1.266 | 1.064 |

Already visible on dev data (to be checked, not assumed, on the result workflows): on 1000Genome
the agents' load balancing helps even in `normal`; on Montage the agents are slightly *worse*
than the baseline when nothing goes wrong, and `baseline_reroute` is worse than doing nothing
under link failure (everyone piles onto the one backup route — the effect CLAUDE.md predicted).

**How to verify**
```bash
python scripts/tune_agents.py     # ~70 s, same choice
pytest -q tests/test_agents.py
```
