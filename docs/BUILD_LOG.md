# Build log

Running record of how this repo was built, stage by stage (see `CLAUDE.md` section 17).
Every entry says what was built, why, and the commands to verify it.

## Progress

- [x] Stage 0 — environment, requirements, data, build log
- [ ] Stage 1 — extraction (`att/extract.py`)
- [ ] Stage 2 — configs + network model (`att/network.py`)
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
