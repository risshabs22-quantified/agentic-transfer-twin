# Build log

Running record of how this repo was built, stage by stage (see `CLAUDE.md` section 17).
Every entry says what was built, why, and the commands to verify it.

## Progress

- [x] Stage 0 — environment, requirements, data, build log
- [x] Stage 1 — extraction (`att/extract.py`)
- [x] Stage 2 — configs + network model (`att/network.py`)
- [ ] Stage 3 — simulator, planner interface, baselines
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
