# Build log

Running record of how this repo was built, stage by stage (see `CLAUDE.md` section 17).
Every entry says what was built, why, and the commands to verify it.

## Progress

- [x] Stage 0 — environment, requirements, data, build log
- [x] Stage 1 — extraction (`att/extract.py`)
- [x] Stage 2 — configs + network model (`att/network.py`)
- [x] Stage 3 — simulator, planner interface, baselines
- [ ] Stage 4 — tuning (baseline only) + freeze `configs/experiment.yaml`
- [ ] Stage 5 — tools, MCP server, tool client, stdio demo
- [ ] Stage 6 — agents + event handling, agent tuning on dev workflows
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

## Tuning table

(Filled in at Stage 4.)

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
