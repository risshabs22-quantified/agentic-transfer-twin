# agentic-transfer-twin

Three AI agents (workflow, network, coordinator) plan the data transfers of real scientific
workflows over a simulated network with congestion and a link failure. They use tools served by an
MCP server, every decision is logged and replayable, and they are compared with simple rule-based
baselines. A preliminary trial for the SciNet project.

<!-- SUMMARY:START -->
Across 180 simulated runs, the agent team beat both baselines in all 120 same-seed comparisons and had 0 late transfers. Plain rerouting already fixes much of a link failure (83% of the agents' gain on 1000Genome 8ch, 53% on Montage 0.1°). Congestion is different: rerouting does nothing there, and on 1000Genome 8ch the agents finish at 0.83 D against 1.17 D, where D is the deadline.
<!-- SUMMARY:END -->

**Read:** [write-up](docs/writeup.md) (short report) · [how it works](docs/HOW_IT_WORKS.md) (complete reference: every rule, limitation and output) · [build log](docs/BUILD_LOG.md)

**Real vs. synthetic:** the workflow traces (tasks, dependencies, file sizes, runtimes) are real
public data. Everything else is synthetic and labeled so: task placement, deadlines, the network
and its numbers, the events, and the file-size multiplier.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/run_experiments.py                     # 180 runs
python scripts/replay.py --all                        # replays every run from its log
python scripts/make_tables.py && python scripts/make_plots.py
```

## Results

Planners:
- **baseline:** lowest-delay routes; never reacts.
- **baseline_reroute:** the same, plus rerouting around a failed link.
- **agents:** the three agents, which see the network only through MCP tools.

<!-- RESULTS:START -->
Mean over 10 seeds: completion time as a fraction of the deadline D (late transfers per run). Full tables: [`results/table.md`](results/table.md).

| Workflow | Scenario | baseline | baseline_reroute | agents |
|---|---|---|---|---|
| 1000Genome 8ch | normal | 0.95 (0.6) | 0.95 (0.6) | 0.80 (0.0) |
| 1000Genome 8ch | congestion | 1.17 (26.9) | 1.17 (26.9) | 0.83 (0.0) |
| 1000Genome 8ch | link failure | 1.69 (86.1) | 0.96 (0.4) | 0.80 (0.0) |
| Montage 0.1° | normal | 0.85 (0.0) | 0.85 (0.0) | 0.84 (0.0) |
| Montage 0.1° | congestion | 0.85 (0.0) | 0.85 (0.0) | 0.83 (0.0) |
| Montage 0.1° | link failure | 1.09 (71.8) | 1.01 (8.5) | 0.95 (0.0) |
<!-- RESULTS:END -->

![Completion time](results/completion_time.png)

![Late and failed transfers](results/failures.png)

<details>
<summary><b>Key findings</b></summary>

<!-- FINDINGS:START -->
When the StarLight-Caltech link fails, the baseline on 1000Genome 8ch takes 1.69 D, and 26.5 transfers per run time out at least once. Rerouting alone brings it to 0.96 D and the agents to 0.80 D, so rerouting covers 83% of the agents' gain. On Montage 0.1° the same three numbers are 1.09, 1.01 and 0.95 D, and rerouting covers 53%.

Congestion is where coordination paid off. On 1000Genome 8ch the rerouting baseline ignores the surge, so it scores the same result as the plain baseline: 1.17 D with 26.9 late transfers per run. The agents move transfers off the congested link and finish in 0.83 D with 0.0 late, faster on 10 of 10 seeds.

With no events at all the agents are already 16% faster than the baseline on 1000Genome 8ch (1.5% on Montage 0.1°), because they spread large transfers over parallel routes from the start. That plan alone does not carry them through events, though. Without reactions (agents_static) the same plan takes 1.03 D under congestion and 1.34 D under the link failure, against 0.83 and 0.80 D when the agents react.

Congestion barely touched Montage 0.1° (baseline 0.853 D in normal, 0.853 D with the surge), because Montage moves most of its data after the surge window closes. The agents' small edge there (0.840 and 0.833 D, -0.4 s per run in normal) is the planning effect again.

The agents lost on the smaller Montage 0.05° workflow used for tuning, in normal (0.966 D against 0.962 D) and congestion (0.977 D against 0.962 D) over the tuning seeds. Their start-of-run forecast can only assume today's network, and it sometimes chose a rebalanced plan that ran slower than plain lowest-delay routing.

Rerouting has its own failure mode. On Montage 0.1° it sends every stuck transfer to the same backup route and still leaves 8.5 late transfers per run, where the agents, spreading and prioritizing, leave 0.0. Across all 120 paired comparisons on the result workflows, they were never slower.
<!-- FINDINGS:END -->

</details>

## MCP server

Tools: `get_workflow_requirements`, `get_network_state`, `get_paths`, `estimate_transfer_time`,
`simulate_plan`, `submit_plan` (plus batch versions).

```bash
python scripts/mcp_demo_client.py                              # call every tool over stdio
npx @modelcontextprotocol/inspector python -m att.mcp_server   # browse them in the MCP Inspector
```

![MCP Inspector](docs/inspector.png)

## Credits

Workflow traces: [WfCommons WfInstances](https://github.com/wfcommons/WfInstances) (LGPL-3.0;
see [`data/NOTICE.md`](data/NOTICE.md)). Coleman et al., "WfCommons: A Framework for Enabling
Scientific Workflow Research and Development," *Future Generation Computer Systems*, 2022.

Designed, directed and verified by Risshab Shankar. Code written with an AI coding assistant
(Claude Code) under my direction.
