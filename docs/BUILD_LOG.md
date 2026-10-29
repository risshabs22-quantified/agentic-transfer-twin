# Build log

Running record of how this repo was built, stage by stage.
Every entry says what was built, why, and the commands to verify it.

## Progress

- [x] Stage 0: environment, requirements, data, build log
- [x] Stage 1: extraction (`att/extract.py`)
- [x] Stage 2: configs + network model (`att/network.py`)
- [x] Stage 3: simulator, planner interface, baselines
- [x] Stage 4: tuning (baseline only) + freeze `configs/experiment.yaml`
- [x] Stage 5: tools, MCP server, tool client, stdio demo
- [x] Stage 6: agents + event handling, agent tuning on dev workflows
- [x] Stage 7: decision log, replay, experiment runner (180 runs)
- [x] Stage 8: tables, plots, README, write-up
- [x] Stage 9: `docs/HOW_IT_WORKS.md`
- [x] Stage 10: fresh-clone reproduction check

### Definition of done

- [x] Fresh clone + the README steps reproduce `results/summary.csv` exactly (byte-for-byte)
- [x] `python scripts/replay.py --all` prints `REPLAY OK` for all 180 runs
- [x] `pytest -q` passes (69 tests), including determinism, no-peeking and docs-consistency tests
- [x] README, write-up and HOW_IT_WORKS complete; every number traces back to `results/`
- [x] Everything synthetic is labeled; limitations are specific and honest
- [x] Every deviation from the original spec is logged and explained (below)
- [x] No secrets, no Caltech/ORNL material, nothing outside the repo touched
- [x] Final commit pushed

## Deviations

Changes from the original project spec, with why each one is better and how to check it.

| # | Stage | What changed | Why | How to check |
|---|---|---|---|---|
| 1 | 3 | **Exact event-driven simulator** instead of fixed `dt` steps. Capacity is still piecewise constant on the `dt = D/1000` grid (load sampled at each cell start, exactly as specified), but the clock jumps from one interesting moment to the next (grid boundary while something is moving, task finish, arrival, planned start, scenario event, last byte sent, stall timeout). | Completion, arrival and failure times are exact for the capacity model instead of rounded up to a step; idle stretches (only tasks running) cost nothing; a full 8ch run takes ~0.03 s. | `tests/test_simulator.py::test_units_sanity` (0.81 s arrival, exact), `test_priority_shares_capacity_two_to_one` (1.2 s / 1.6 s exactly). |
| 2 | 3 | **Stall timeout counts *consecutive* stall time**: the timer resets when the transfer moves again or is given a new path. | The spec says stall time "accumulates" but not whether it resets; a timeout in real transfer tools (and TCP) is time without progress, so short separate stalls should not add up to a failure. | `test_stall_shorter_than_timeout_does_not_fail`, `test_failure_path_counts_transfer_once`. |
| 3 | 3 | **Rerouting keeps the bytes already sent** (like restart markers in GridFTP); only a *failed attempt* resets to the full size, as specified. | Otherwise a reroute would be punished like a failure, which would bias against any planner that reroutes. Applies identically to every planner. | `att/simulator.py::_apply`. |
| 4 | 3 | **Extra validation rule:** plan entries for transfers that have already sent all their bytes are rejected ("transfer already sent all its bytes"). Transfers missing from the initial plan get the default entry (lowest-delay path, priority 1, start 0). | Changing a finished transfer has no effect and would inflate `reroutes`. The default makes a partial plan safe. Both apply to every planner and to `submit_plan`. | `tests/test_planner.py`, `test_invalid_entries_rejected_and_logged`. |
| 5 | 3 | **Every planner call is logged as a decision, including "no change"**, so `decisions` = 1 + number of events delivered. | Replay must check every event against the log (type, seq, t); logging only non-empty answers would make that impossible. | `sim.decisions` length vs. events in `test_failure_path_counts_transfer_once`. |
| 6 | 3 | `avg_gbps` is NaN when a run doesn't complete (same as `completion_s`). Ties at one instant are processed in a fixed order: last bytes sent → arrivals → task finishes → planned starts → scenario events → timeouts. | Keeps metrics well defined and the run deterministic. | `att/simulator.py::_process_instant`. |
| 7 | 3 | Added `att/config.py` (YAML loading) and `att/runner.py` (`build_sim`, `run_one`, `run_id`) to the layout. | One place builds a run, so experiments, tuning, tests and replay can't drift apart. |  |
| 8 | 3 | **Float guard:** if a transfer's remaining bytes are too small to move the clock (`t + remaining/rate == t`), it is finished now. | Found while testing: a 1.7e-5-byte remainder at 10 GB/s gives a 1.6e-15 s step, which is below float resolution at t = 51 s, so the loop never advanced. | `att/simulator.py::_loop`. |
| 9 | 4 | Added an optional per-link byte counter (`Simulator.count_window`) used only by `tune.py` for step (a). | Step (a) needs "the link that carries the most baseline bytes during the event window"; measuring it inside the simulator is exact. It is off (None) in every experiment run. | `scripts/tune.py::busiest_link_in_window`. |
| 10 | 5 | Tools additions: batch tools `get_paths_many` and `estimate_many` (the spec allows these); `get_paths(..., avoid_down=False)` option; `get_workflow_requirements` adds `data_ready_s` (best present estimate of when a transfer's data exists, from task status and trace runtimes); "never"/"unknown" are returned as `null` because MCP output must be valid JSON (NaN/inf are not). | Fewer round trips per decision; agents need readiness to compute slack; the SDK rejects NaN in structured output (verified). | `tests/test_tools.py`. |
| 11 | 5 | The module-level demo server `att.mcp_server.mcp` is built lazily (module `__getattr__`) rather than at import time. | Importing `build_server` in every experiment run would otherwise build a throwaway demo twin each time. `python -m att.mcp_server` and `getattr(module, "mcp")` (what `mcp dev` uses) still work. | `python scripts/mcp_demo_client.py`. |
| 12 | 5 | `Simulator.run` split into `start(planner)` (t = 0 setup + initial plan) and the main loop. | The demo server and tests need a twin "at t = 0 with a plan in place" without running it. | `tests/test_tools.py`. |
| 13 | 6 | **Coordinator forecasts three drafts, not two**: load-balanced, the network agent's fastest-route draft, *and* the simple lowest-delay draft. It keeps the best forecast, but leaves the lowest-delay draft only if another is forecast at least `draft_margin` (tuned: 5%) faster. | On dev Montage (tuning seeds) the two specified drafts were both *worse* than the baseline in `normal` (1.010 D and 1.158 D vs 0.962 D): time-blind balancing pushes small files onto 3-hop routes, and "everyone takes the fastest route" herds them onto one link. Persistence forecasts are only accurate to a few %, so a small forecast gain is noise; the margin is a principled hysteresis. With it: 0.966 D. | `results/tuning/agent_tuning.json`; `AgentTeam(drafts=...)` reproduces each variant. |
| 14 | 6 | **Event handling details:** every event also refreshes priorities (slack changes over time); `link_up`/`surge_end` consider moving back *any* unfinished transfer that could use the restored link (not only not-yet-started ones), because rerouting keeps bytes already sent (Deviation 3); a transfer is moved only if its projected load drops by `move_margin` (tuned: 10%) or its route is down; and the whole change is kept only if a `simulate_plan` forecast says it is no worse than keeping the current plan. | Avoids churn from tiny projected gains, and the forecast gate stops changes that look good locally but hurt overall. | `att/agents/coordinator.py::_react`. |
| 15 | 6 | Agent parameters tuned: `priority_fraction` ∈ {0.1, 0.2, 0.3, 0.5}, `move_margin` ∈ {0, 0.1, 0.25}, `draft_margin` ∈ {0, 0.05, 0.1}, on the 2 dev workflows × 3 scenarios × tuning seeds 100–104 (36 configs). `busy_threshold` (0.3) and `k_paths` (3) kept as specified. | The spec allows tuning agent parameters on dev workflows only; the grid is small and fully logged. | `python scripts/tune_agents.py`. |
| 16 | 6 | The tool client tags every recorded call with the calling agent (`workflow_agent` / `network_agent` / `coordinator`). | The decision log then shows which agent asked what. | `tests/test_agents.py`. |
| 17 | 7 | Manifests store a **self-contained `settings` dict** (workflow file + sha256, sites, slack, data_scale, the scenario's events, background parameters, the full topology, simulator settings, planner + parameters), and replay rebuilds the simulator from it (`att/runner.py::sim_from_settings`) rather than from the current YAML files. Experiments use the same function, so there is one code path. | A replay can't silently pick up a later config edit; a changed data file is detected by its hash. | `tests/test_replay.py`. |
| 18 | 7 | `summary.csv` is rebuilt from the manifests of every run in the configured grid, in grid order. Logs are gzip files with a fixed header (mtime 0, no file name). Added `att/experiment.py` (run + record one run). | Running a subset refreshes only those runs and still produces the same full table; identical runs give byte-identical logs. | `test_log_and_manifest_are_byte_identical_when_rerun`. |
| 19 | 8 | **Supplementary ablation `agents_static`** (the agents' initial plan, never reacting to events), run on the same 60 result-workflow cells by `scripts/run_ablation.py` into `results/ablation/` (logs, manifests, its own `summary.csv`). It is not part of the 180 main runs or `results/summary.csv`. | The main table showed the agents are already faster in `normal`, so part of their advantage is up-front planning, not coordination. This ablation measures how much comes from reacting to events (SciNet 4.4.2: "which benefits come from coordination vs. rerouting"). Nothing was tuned on it. | `python scripts/run_ablation.py`; table at the end of `results/table.md`. |
| 20 | 8 | A third auto-synced block, `<!-- SUMMARY:START/END -->`, holds a one-sentence headline computed by `make_tables.py` (`results/headline.md`); the write-up's Summary section and the README lead use it. The docs-consistency test covers all three blocks. | The write-up's summary sentence must also trace to `results/`. | `tests/test_docs_consistency.py`. |
| 21 | 8 | Key findings include the agents' clearest loss, which is on a **dev** workflow (Montage 0.05°, tuning seeds), read from `results/tuning/*.json`. | On the result workflows the agents were never slower in any paired comparison, but the spec asks for a finding where they did not help if one exists; hiding the dev loss would overstate the agents. | `scripts/make_tables.py::dev_comparison`. |
| 22 | 8 | Plots: completion time in seconds with a dashed line at D (one panel per workflow, since D differs); failures as a 2 × 2 grid (late / failed × workflow). Colors fixed per planner, from a palette checked for color-vision deficiency with the dataviz validator; every bar carries its value. | One y-axis per panel, units on axes, identity never by color alone. | `results/*.png`. |
| 23 | 9 | **Bug fix found while writing HOW_IT_WORKS:** a stall timeout no longer fails a transfer whose link came back at that same instant (the timeout check now also requires the transfer to still be stalled). | The outage lasts exactly 0.6 D = 6 timeouts, so stalled baseline transfers hit their 6th timeout at the very moment the link returned and were counted as failed although they were no longer stuck. This changed results after I had seen them, so I re-ran **everything**: `tune.py` and `tune_agents.py` outputs are byte-identical (same choices); in the 180 runs only `failed_attempts` and `decisions` changed, in the 10 `1000genome-8ch / link_failure / baseline` rows (e.g. seed 3: 136 → 115 failed attempts); completion, late and failed-transfer counts, tables, findings and plots are unchanged (a transfer stalled since its last failure had no progress to lose). The fix can only help the baselines. | `tests/test_simulator.py::test_link_back_exactly_at_timeout_does_not_fail`; `python scripts/replay.py --all`. |
| 24 | stretch | **Cross-platform reproduction is exact to the last bit for all but one value.** CI (Linux x86-64) replays the committed logs (180/180 OK), re-runs all 180 experiments and compares with the committed `summary.csv` using `scripts/check_summary.py` (ints/bools/text exact, floats within 1e-9 relative). Result: 2879 of 2880 values byte-identical; the one exception is `data_wait_s` in one row (7085.066725301376 on macOS arm64 vs …378 on Linux), a difference in the 16th significant digit. | Bit-identical floats across CPU architectures are not guaranteed (numpy's vectorized `sin` and libm differ in the last bit between ARM and x86). The DoD requirement (fresh clone reproduces `summary.csv` byte-for-byte) holds on the same platform, verified in Stage 10; across platforms the honest guarantee is the replay tolerance. | GitHub Actions job `reproduce`; `python scripts/check_summary.py a.csv b.csv`. |
| 25 | stretch | **Competing workflows** support: `extract.merge_workflows` prefixes every task/file id with its workflow name; the simulator keeps each workflow's own D (`members`), re-samples capacity on the shortest workflow's grid, gives each transfer the timeout of its own workflow (0.1 × its own D), and reports per-workflow completion/late/failed (`<workflow>:...` metrics). Single-workflow runs are unchanged (verified: replay 180/180 and `summary.csv` byte-identical after the change). | Judging Montage on 1000Genome's clock (a 60 s timeout for a 32 s workflow) would be meaningless. | `tests/test_competing.py`. |
| 26 | stretch | Optional **weighted max-min fair sharing** (`Simulator(sharing="maxmin")`, set via `simulator.sharing` in a run's settings; default stays `proportional`, used for all main results). | Checks that the conclusions don't depend on the simplified sharing rule. | `tests/test_simulator.py::test_maxmin_gives_unused_capacity_to_others` (hand-checked rates: 50 vs. 90 Gbps). |
| 27 | stretch | **LLM mode** differs from the spec in three ways: (a) **no temperature setting**: since 2026-10-21 the Claude API rejects `temperature` on every model, so "temperature 0" is impossible; reproducibility comes from the decision log instead (every prompt and raw answer is logged and all LLM runs replay exactly with no API calls); (b) **Claude does not call the MCP tools itself**: the coordinator makes the tool calls and passes their results, because the spec allows at most one LLM call per plan/event and a tool-using loop needs one API call per tool round; (c) Claude is consulted only when there is a decision to make (initial plan, or an event whose rule proposal is non-empty). Also: refusal fallbacks (`fallbacks: "default"`) are enabled; a hard spend cap (default $25, conservative pricing) stops runs before any call that could exceed it; recorded runs are never re-run (no double spending). Dependency added: `anthropic==2.3.0` (optional, LLM mode only). | Follows the current API; keeps the one-call limit; keeps cost bounded and auditable. | `tests/test_llm_mode.py` (offline, mocked API); `python scripts/replay.py --llm`. |

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
| montage-01d | 300 | 0.859 | congestion | (c) kept as configured; reported as a finding |  |  |  |  | no |
| montage-01d | 300 | 0.859 | link_failure | as configured | down StarLight–Caltech | 1.092 | 79.0 | 39.8 | yes |

---

## Entries

### Stage 0: environment and data (2026-10-29)

**Built**
- Git repo on `main`, remote `origin` = `github.com/risshabs22-quantified/agentic-transfer-twin` (the remote was empty, so there were no existing README/LICENSE to keep).
- `.venv` with Python **3.12.14** (the system `python3` is 3.14; 3.12 is the recommended version and has wheels for every dependency).
- `requirements.txt` pinning the exact installed versions of the direct dependencies:
  networkx 3.7, numpy 2.5.4, pandas 3.1.0, matplotlib 3.11.2, PyYAML 6.0.3, mcp[cli] 2.3.0, pytest 9.2.0.
- `pyproject.toml` holding only pytest config (`pythonpath = ["."]` so tests import `att` without installing it).
- `scripts/fetch_data.py`: downloads the 4 WfInstances traces + LICENSE into `data/raw/` (skips existing files; writes via a `.part` temp file so an interrupted download can't leave a corrupt file).
- `data/NOTICE.md`: credit, LGPL-3.0 note, citation, and what is synthetic.
- `tests/test_data.py`: data files parse and the license is present.

**Verified**
- MCP SDK 2.3.0 v2 API (`mcp.server.MCPServer`, `mcp.Client`) works in-process as documented.
  One detail found: a tool annotated `-> dict` returns `structured_content=None`; annotating
  `-> dict[str, Any]` returns the dict as structured content. Tools use the latter.
  In-process tool calls cost ~0.15 ms each, so per-call overhead is not a concern.

**How to verify**
```bash
python scripts/fetch_data.py   # prints "skip" for each file
pytest -q
```

### Stage 1: extraction (`att/extract.py`) (2026-10-29)

**Built**
- The reference extraction algorithm from the spec, unchanged in behavior, split into small
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

**Result** (seed 0, slack 1.5, data_scale 1) matches the expected values exactly:

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

### Stage 2: configs and network model (`att/network.py`) (2026-10-29)

**Built**
- `configs/topology.yaml`, `configs/scenarios.yaml` exactly as specified, with "SYNTHETIC" headers.
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

### Stage 3: simulator, planner interface, baselines (2026-10-29)

**Built**
- `att/planner.py`: `Planner` base class (`plan`, `on_event`, and a `note` dict the planner fills
  with `agent`/`saw`/`tool_calls`/`reason` for the decision log) and `validate_entry` /
  `validate_plan`, shared by the simulator and (later) the `submit_plan` tool.
- `att/simulator.py`: `Simulator` (the twin) and `TwinView` (what planners see: the clock, link
  capacity/free capacity/up-down *now*, transfer and task status, the current plan). Semantics
  follow the spec (see Deviations 1–6 for the details that had to be chosen).
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

These are close to the numbers from an earlier throwaway prototype (≈0.99 / 1.19 / 1.71 D for 8ch; ≈0.78 /
1.03 D for Montage, with congestion having no effect on Montage). Each run takes 0.01–0.05 s.

**How to verify**
```bash
pytest -q tests/test_simulator.py tests/test_planner.py
```

### Stage 4: tuning (baseline only) and freezing `configs/experiment.yaml` (2026-10-29)

**Built**
- `scripts/tune.py`: applies the tuning rule using only `baseline` and tuning
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
- montage-005d (dev only) / `congestion`: passes the rule only formally: its *normal* run already
  has 1.4 late transfers on average, so "late + failed > 0" is true without any stress
  (completion 0.962 D in both). In practice congestion doesn't stress it either. It is only used
  for tuning agent parameters, not for results.

**How to verify**
```bash
python scripts/tune.py     # ~5 s; same numbers; doesn't touch experiment.yaml without --write
pytest -q tests/test_config.py
```

### Stage 5: tools, MCP server, tool client, stdio demo (2026-10-29)

**Built**
- `att/tools.py`: `get_workflow_requirements`, `get_network_state`, `get_paths` (+ `get_paths_many`),
  `estimate_transfer_time` (+ `estimate_many`), `simulate_plan` (persistence forecast via
  `Simulator.snapshot()`), `submit_plan` (same validation as the simulator). Plain functions over
  a `TwinView`; JSON in, JSON out.
- `att/mcp_server.py`: `build_server(view) -> MCPServer` with one `@mcp.tool()` wrapper per tool;
  `python -m att.mcp_server` serves a demo twin (1000Genome 2ch, normal, seed 0, t = 0) over stdio.
- `att/tool_client.py`: `run_with_tools(server, fn)` opens ONE MCP client session inside ONE
  `asyncio.run` per decision and records every call (tool, args, with long args stored as size + sha256,
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

### Stage 6: agents and event handling; agent tuning on dev workflows (2026-10-29)

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
  yaml, and agents never read `view.<anything>`; they only pass it to `build_server`); frozen
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
under link failure (everyone piles onto the one backup route, the effect the earlier prototype had shown).

**How to verify**
```bash
python scripts/tune_agents.py     # ~70 s, same choice
pytest -q tests/test_agents.py
```

### Stage 7: decision log, replay, experiments (180 runs) (2026-10-29)

**Built**
- `att/decision_log.py`: `results/logs/<run_id>.jsonl.gz`, one line per decision with
  `run_id, seq, t, agent, trigger, saw, tool_calls, decision, rejected, reason`. Every planner is
  logged, the baselines included; "no change" answers are logged too (Deviation 5).
- `att/replay.py`: `ReplayPlanner` (returns logged decisions in order, checks each incoming event's
  type/seq/t/link/transfer against the log, raises `ReplayMismatch` otherwise) and `replay_run`.
- `att/experiment.py` + `scripts/run_experiments.py`: 2 result workflows × 3 scenarios × seeds 0–9
  × 3 planners = 180 runs; manifest per run (settings, metrics, git commit, package versions).
  Filters `--workflows/--scenarios/--seeds/--planners` run a subset.
- `scripts/replay.py --run <id> | --all`: rebuilds from the manifest, replays from the log,
  compares metrics (ints/bools exact, floats 1e-9 relative), prints `REPLAY OK <id>`, exits non-zero
  on any mismatch.
- `tests/test_replay.py`: exact replay of a baseline and an agents run on a dev workflow;
  re-running gives byte-identical logs; a tampered log is caught; an extra event is caught.

**Result**
- `python scripts/run_experiments.py`: 180 runs in ~14 s, `results/summary.csv` has 180 rows,
  every run completed. Code was committed first so manifests record a clean commit.
- `python scripts/replay.py --all`: **180/180 runs replayed exactly**.
- Note: the agent parameters and `experiment.yaml` were frozen (Stage 6 commit) before any
  evaluation-seed run; nothing has been tuned since.

**How to verify**
```bash
python scripts/run_experiments.py
python scripts/replay.py --all
pytest -q tests/test_replay.py
```

### Stage 8: tables, plots, findings, README, write-up (2026-10-29)

**Built**
- `scripts/make_tables.py` → `results/table.md` (mean ± std of completion in s and × D, late,
  failed, completed runs per workflow × scenario × planner; paired per-seed comparisons agents vs.
  baseline and vs. baseline_reroute with mean Δ and win counts; the `agents_static` ablation
  table), `results/key_findings.md` (6 sentences, every number computed, wording follows the sign
  of each result), `results/headline.md`; rewrites the SUMMARY/RESULTS/FINDINGS blocks in
  `README.md` and `docs/writeup.md`.
- `scripts/make_plots.py` → `results/completion_time.png`, `results/failures.png` (titles computed
  from the data). Rendered and checked by eye for overlaps.
- `scripts/run_ablation.py` (Deviation 19).
- `README.md` (summary, real vs. synthetic, install/run, results + findings + plots, MCP section
  with Inspector command and a screenshot placeholder, data credit, "How this was built").
- `docs/writeup.md` (sections 1–10, first person; the only numbers outside the synced blocks are
  settings from `configs/` and the tuning outputs).
- `tests/test_docs_consistency.py`: blocks equal the generated files; 180 rows; plots exist.

**What the results say** (all from `results/`): the agents were faster than both baselines on all
120 same-seed comparisons and had no late or failed transfers. Simple rerouting recovers 83%
(1000Genome 8ch) and 53% (Montage 0.1°) of the agents' improvement under the link failure.
Congestion is where coordination clearly matters (1000Genome 8ch: 1.17 D for both baselines vs.
0.83 D). A real part of the agents' advantage is planning, not reacting: they are already 16%
faster in `normal` on 1000Genome 8ch; but without event reactions the same plan takes 1.03 D under
congestion and 1.34 D under the link failure. Congestion does not stress Montage 0.1° at all.

**How to verify**
```bash
python scripts/run_ablation.py
python scripts/make_tables.py && python scripts/make_plots.py
pytest -q tests/test_docs_consistency.py
```

### Stage 10: fresh-clone check (2026-10-29)

**Done**
- `git clone` of `origin/main` (commit `ffdc372`) into a temporary folder outside the repo, new
  venv with Python 3.12.14, then exactly the README steps: `pip install -r requirements.txt`,
  `python scripts/run_experiments.py`, `python scripts/replay.py --all`,
  `python scripts/make_tables.py && python scripts/make_plots.py`, plus `pytest -q` and
  `python scripts/run_ablation.py`.

**Result**
- `results/summary.csv` **byte-identical** to the committed one; `results/ablation/summary.csv`
  identical too.
- `REPLAY OK` for **180/180** runs (exit code 0).
- `pytest -q`: 69 passed.
- After regenerating, `git status` in the clone showed no changes to logs, tables, findings, plots,
  README or write-up; the only difference was the `git_commit` field inside each manifest (the
  clone was at a newer commit than the one that produced the committed results), as expected.
- Secret scan of all tracked files: nothing found; no `.env` tracked; `.git` is 1.3 MB.

**How to verify**
```bash
git clone https://github.com/risshabs22-quantified/agentic-transfer-twin.git /tmp/att-check && cd /tmp/att-check
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python scripts/run_experiments.py && python scripts/replay.py --all
cmp results/summary.csv <(git show HEAD:results/summary.csv) && echo identical
```

### Stretch goal 1: GitHub Actions (2026-10-29)

- `.github/workflows/tests.yml`, two jobs on every push to `main` and on pull requests:
  - `pytest`: Python 3.12 on ubuntu-latest, `pip install -r requirements.txt`, `pytest -q`.
  - `reproduce`: replays the committed logs, re-runs all 180 experiments, and compares with the
    committed `summary.csv` using `scripts/check_summary.py` (Deviation 24).
- Both jobs passed on GitHub before I kept them. The first `reproduce` attempt used a
  byte-for-byte `git diff` and failed on the one 16th-digit difference; I switched it to the
  replay tolerance and documented why, rather than hiding the difference.

### Stretch goal 2: `competing_workflows` (2026-10-29)

- `scripts/run_competing.py`: 1000Genome 8ch (×100) and Montage 0.1° (×300) start together at
  t = 0 on the `normal` network; 3 planners × seeds 0–9 = 30 runs into `results/competing/`
  (logs, manifests, `summary.csv`); every run is replayed from its log right after it is recorded
  (30/30 REPLAY OK). Frozen parameters; nothing tuned.
- `make_tables.py` adds a "Supplementary: competing workflows" section to `results/table.md`.
- Result (see the table): every workflow met its deadline in 7/10 runs with the agents vs. 0/10
  for both baselines (which are identical here, with no outage to reroute around); the agents were
  faster for both workflows on 10/10 seeds; Montage still finishes right at its deadline on
  average with the agents, because nothing in the agents is about fairness between workflows.

### Stretch goals 3 and 4: max-min fair sharing; Claude Desktop snippet (2026-10-29)

- `scripts/run_maxmin.py`: the full 180-run grid under max-min fair sharing into `results/maxmin/`
  (logs, manifests, `summary.csv`), each replayed right after it is recorded: 180/180 exact.
  Nothing re-tuned. `make_tables.py` adds a "Supplementary: max-min fair sharing" section.
  Result: every cell moves by less than 0.01 D, the planners keep the same order everywhere, and
  the agents still win 10/10 paired seeds against both baselines in every cell, so the conclusions
  do not depend on the sharing model.
- README: a Claude Desktop `mcpServers` config snippet for the demo MCP server (same command the
  stdio demo client already exercises).
- Stretch goal 5 (LLM mode) not started yet: it needs an API key and approval to spend money.

### Stretch goal 5: LLM mode (Claude Opus 5.5, spending cap $25) (2026-10-29)

- Key stored only in the gitignored `.env` (permissions 600); verified with the free `/v1/models`
  endpoint; never committed (checked the staged diff before every commit).
- `att/llm.py` (one structured-output Claude call, spend ledger in `results/llm/spend.json`, hard
  cap), `att/agents/llm_coordinator.py` (`LLMAgentTeam`: same agents/tools; Claude picks the draft
  and may flip priorities, and on events applies/keeps/customises the coordinator's proposal from
  listed route options; validated; rule fallback on any failure). The rule coordinator got two
  review hooks; rule-mode logs and `summary.csv` verified byte-identical afterwards.
- One dev smoke test (1000Genome 2ch, link_failure, seed 100), then the 60 result-workflow runs
  (seeds 0–9). The prompt was not changed after seeing any evaluation result.
- Result (`results/table.md`, "Supplementary: LLM mode"): 131 API calls, spend upper bound $5.94;
  0 fallbacks; Claude's decision matched the rule coordinator's in 114 of 129 decisions; LLM mode
  was faster than rule mode on 2/10 seeds per 1000Genome scenario (never slower) and essentially
  tied on Montage (slower on 4/10 congestion seeds by small margins); it beat both baselines on
  every seed. All 61 LLM runs replay exactly without calling the API (`scripts/replay.py --llm`).

### MCP Inspector screenshot (2026-10-29)

- The MCP Inspector (v2.13.0) was run against `python -m att.mcp_server` with a `get_paths`
  call (CERN → UCSD). Saved as `docs/inspector.png`, cropped to the Inspector window only (browser tabs,
  bookmarks and the Inspector session token in the URL removed), and placed in the README's MCP
  section in place of the placeholder.

### Shorter README; credit line reworded (2026-10-29)

- The README was cut to the essentials: summary, links, real vs. synthetic,
  run commands, a compact results table, both plots, key findings (collapsible), the MCP server
  and credits. Optional extras (ablation, competing workflows, max-min, LLM mode, Claude Desktop
  config) are documented in `docs/HOW_IT_WORKS.md` and this log.
- New generated file `results/table_short.md` (one row per workflow × scenario: mean completion × D
  and late transfers per planner) fills the README's RESULTS block; the write-up keeps the full
  `results/table.md`. `tests/test_docs_consistency.py` checks both.
- The credit line states that the project was designed, directed and verified by its author and that
  the code was written with an AI coding assistant (Claude Code) under that direction.

### Writing pass and cleanup (2026-10-30)

Docs, docstrings and the generated findings were rewritten in plainer language: shorter
sentences, no dashes used as punctuation, and no internal milestone labels ("Stage 4",
"stretch goal") in code. The findings generator keeps the same computed numbers and the same
sign-dependent wording. Dead code went too: `TwinView.timeout_s`, `Simulator.settings` and an
unused import. Results are unchanged: `summary.csv` is identical, 180/180 main runs and 61/61 LLM
runs replay exactly, and all 78 tests pass.

### HOW_IT_WORKS as a complete reference (2026-10-30)

`docs/HOW_IT_WORKS.md` was rebuilt as the full reference for the repository: the idea, the
life cycle of one run, extraction (placement hash, critical-path deadlines, transfer rules), the
network model (topology, the background-load formula, scenarios), the simulator (event loop,
sharing, stalls and timeouts, validation, every metric, forecasts), each planner and agent with
its exact rules and parameters, LLM mode, the tools with real example outputs, logs, manifests
and replay, tuning and experiments, every output file, results, a table of limitations with what
was done about each, tests, and how to extend the code. Its results, summary and findings are
synced from `results/` like the README's, and `tests/test_docs_consistency.py` now checks it too.
