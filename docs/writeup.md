# Agents for workflow data transfers on a simulated network: a preliminary trial

Risshab Shankar, November 2026

## 1. Summary

<!-- SUMMARY:START -->
Across 180 simulated runs, the agent team beat both baselines in all 120 same-seed comparisons and had 0 late transfers. Plain rerouting already fixes much of a link failure (83% of the agents' gain on 1000Genome 8ch, 53% on Montage 0.1°). Congestion is different: rerouting does nothing there, and on 1000Genome 8ch the agents finish at 0.83 D against 1.17 D, where D is the deadline.
<!-- SUMMARY:END -->

In plain words: science jobs spread over several computing centers have to ship files between them,
and a jammed or closed connection delays everything downstream. I built a simulated network, ran
real science jobs over it, and compared three ways of planning the file shipments: a simple rule, the
same rule plus detours around closed roads, and a team of three AI agents. Times are given as a
fraction of each job's deadline D, so 1.00 is exactly on time and lower is better. A non-technical
walkthrough of the whole project is in [`PLAIN_ENGLISH.md`](PLAIN_ENGLISH.md).

## 2. Goal

This project tests, in a small and fully reproducible setting, the plan I proposed on October 23.
Real workflow traces give the data-transfer requirements. Those transfers run over a simulated
network whose capacity changes, and a workflow agent, a network agent and a coordinator turn the
requirements into a transfer plan through tools exposed over MCP. Every decision is logged so any
run can be replayed, and the agents are compared with a simple rule-based baseline on completion
time and failed transfers. The question I cared most about was where agents actually help and
where a simple rule is already enough.

## 3. Setup

**Workflows.** I used four public traces from the WfCommons WfInstances project (Coleman et al.,
*Future Generation Computer Systems*, 2022; LGPL-3.0): 1000Genome with 2 and 8 chromosomes, and
Montage at 0.05° and 0.1°. The two small ones (1000Genome 2ch, Montage 0.05°) were used only for
tuning; all results below are on the two larger ones (1000Genome 8ch, Montage 0.1°). From each trace
I use the task graph, which files each task reads and writes, file sizes, and task runtimes.

**From traces to transfers.** Each task is placed at one of four compute sites by a seeded sha256
hash (synthetic, but repeatable). Raw inputs start at a source site. Whenever a task needs a file
that lives at another site, that is a transfer; a file needed by several tasks at one site is
moved once. Deadlines come from the critical-path method: the workflow deadline D is 1.5 × the
critical path (if data moved instantly), and each transfer must arrive by the latest start time of
the first task that needs it.

**Network (synthetic).** Six sites and seven links with invented capacities (100 or 400 Gbps) and
delays. Every link carries background traffic: a mean load plus a slow wave plus random noise,
redrawn per seed. Three scenarios, with times given as fractions of D so short and long workflows
are stressed alike:

- `normal`: background traffic only;
- `congestion`: a surge on one link (StarLight–ORNL) from 0.05 D to 0.5 D that pushes it to its
  load cap;
- `link_failure`: one link (StarLight–Caltech) is down from 0.15 D to 0.75 D. On this map that link
  carries the lowest-delay route to both Caltech and UCSD.

A transfer whose route has a down link stalls; after 0.1 D without progress the attempt fails and
starts over. The simulator is event-driven: link capacity is re-sampled every D/1000, and every
arrival, task finish, failure and event happens at its exact time.

**Scaling file sizes.** At their real sizes these files barely load a 100 Gbps network, so I
multiply sizes by a per-workflow `data_scale` (synthetic). I chose it by a fixed rule, using only
the baseline and only five tuning seeds, before any agent existed: the largest value from a fixed
list at which the baseline still finishes within D and is late on at most 1% of transfers in
`normal`. That gave ×100 for 1000Genome 8ch and ×300 for Montage 0.1°. I then checked that each
stress scenario actually stresses the baseline. Congestion did not stress Montage 0.1°, even after
moving the surge to the busiest link and raising it to the load cap, so I kept the scenario as
configured and report that as a finding instead of making it harsher.

**Keeping tuning separate from evaluation.** Network settings were tuned on seeds 100–104 with the
baseline only. Agent parameters were tuned on the two small workflows with the same seeds. The
final runs use seeds 0–9 on the two result workflows, with every setting frozen beforehand in
`configs/experiment.yaml`. All three planners see the same seed, so the same placement, noise and
events.

## 4. Agents and MCP tools

The agents never touch the simulator. They see the network only through six tools (two also have
batch versions), served by an MCP server and called through an MCP client in every decision:

| Tool | What it returns | SciNet task |
|---|---|---|
| `get_workflow_requirements` | transfers, sizes, src/dst, readiness, deadlines, status | 1.1.3 |
| `get_network_state` | per link: capacity, free Gbps now, up/down; the clock | 3.1.5 |
| `get_paths` | up to k routes, lowest delay first | 2.2.3 |
| `estimate_transfer_time` | seconds at today's free capacity of the slowest link, plus delay | 1.3.4 |
| `simulate_plan` | a forecast run of a plan on a copy of the present network | 3.1.5 |
| `submit_plan` | validation of a plan | 3.2.4 |

- **Workflow agent:** estimates each transfer's earliest arrival and its slack (deadline minus
  earliest arrival), and gives the most urgent ones priority 2.
- **Network agent:** finds the three lowest-delay routes for each transfer, estimates the time on
  each, recommends the fastest one that is up, and flags busy links.
- **Coordinator:** builds three candidate plans:
  - routes chosen to spread bytes over parallel links;
  - each transfer on its individually fastest route;
  - plain lowest-delay routes.

  It forecasts all three with `simulate_plan` and keeps the best. It only leaves the simple plan
  if another is forecast clearly faster, because forecasts are uncertain. On each event it
  re-plans only the transfers the event affects:
  - off a down link, spreading them over the routes that remain;
  - off a surged link, if another route is projected faster;
  - back onto a restored link.

  It keeps a change only if a forecast says it is no worse than doing nothing.

**Validation.** Every plan entry is checked by the simulator and by `submit_plan`:
- the transfer exists;
- the route is simple, runs from source to destination, and uses real links;
- the priority is 1 or 2;
- the start time is not in the past.

Invalid entries are rejected and logged, and the previous entry stays.

**No peeking.** Planners learn about the network only from the tools and from event notifications.
The tools expose only the present. `simulate_plan` assumes current capacities persist, down links
stay down, and nothing else happens. Tests check that a failure scheduled in the future does not
change a forecast, and that the agent code imports nothing from the simulator or the scenario files.

All main results are **rule mode**: the agents are deterministic rules, not a language model. A
separate LLM-mode test is reported at the end of the results table.

## 5. Baselines

- **baseline** is what I proposed: lowest-delay route for every transfer, normal priority, start
  as soon as the data exists, and never react. Stuck transfers wait and time out.
- **baseline_reroute** is an ablation I added to answer "isn't this just rerouting?". It is the
  same, but when a link goes down it moves every unfinished transfer that uses it to the
  lowest-delay route that avoids it. It ignores congestion and never uses priorities.

## 6. Results

<!-- RESULTS:START -->
_Generated by `scripts/make_tables.py` from `results/summary.csv` (180 runs). Each cell: mean ± standard deviation over 10 evaluation seeds. D = the workflow's deadline. The network, task placement, deadlines and scaled file sizes are SYNTHETIC._

| Workflow (D, data_scale) | Scenario | Planner | Completion (s) | Completion (× D) | Late transfers | Failed transfers | Completed runs |
|---|---|---|---|---|---|---|---|
| 1000Genome 8ch (601.9 s, ×100) | normal | baseline | 574.8 ± 25.9 | 0.955 ± 0.043 | 0.6 ± 1.3 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | normal | baseline_reroute | 574.8 ± 25.9 | 0.955 ± 0.043 | 0.6 ± 1.3 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | normal | agents | 481.8 ± 23.0 | 0.800 ± 0.038 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | congestion | baseline | 705.7 ± 24.3 | 1.172 ± 0.040 | 26.9 ± 3.5 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | congestion | baseline_reroute | 705.7 ± 24.3 | 1.172 ± 0.040 | 26.9 ± 3.5 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | congestion | agents | 497.8 ± 28.5 | 0.827 ± 0.047 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | link failure | baseline | 1019.7 ± 16.2 | 1.694 ± 0.027 | 86.1 ± 7.4 | 26.5 ± 4.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | link failure | baseline_reroute | 575.0 ± 25.5 | 0.955 ± 0.042 | 0.4 ± 1.3 | 0.0 ± 0.0 | 10/10 |
| 1000Genome 8ch (601.9 s, ×100) | link failure | agents | 481.7 ± 22.2 | 0.800 ± 0.037 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | normal | baseline | 27.0 ± 0.6 | 0.853 ± 0.018 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | normal | baseline_reroute | 27.0 ± 0.6 | 0.853 ± 0.018 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | normal | agents | 26.6 ± 0.5 | 0.840 ± 0.017 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | congestion | baseline | 27.0 ± 0.6 | 0.853 ± 0.018 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | congestion | baseline_reroute | 27.0 ± 0.6 | 0.853 ± 0.018 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | congestion | agents | 26.4 ± 0.4 | 0.833 ± 0.014 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | link failure | baseline | 34.4 ± 1.1 | 1.087 ± 0.034 | 71.8 ± 34.5 | 36.5 ± 7.3 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | link failure | baseline_reroute | 32.1 ± 0.9 | 1.014 ± 0.028 | 8.5 ± 12.9 | 0.0 ± 0.0 | 10/10 |
| Montage 0.1° (31.7 s, ×300) | link failure | agents | 30.1 ± 0.8 | 0.950 ± 0.025 | 0.0 ± 0.0 | 0.0 ± 0.0 | 10/10 |

**Paired comparisons** (same seed = same placement, noise and events). Δ = agents − other planner; negative Δ means the agents were faster. "Agents faster" counts seeds where the agents finished strictly sooner.

| Workflow | Scenario | Agents vs. | Mean Δ completion (s) | Mean Δ (× D) | Agents faster | Mean Δ late | Mean Δ failed |
|---|---|---|---|---|---|---|---|
| 1000Genome 8ch | normal | baseline | -93.0 | -0.154 | 10/10 seeds | -0.6 | +0.0 |
| 1000Genome 8ch | normal | baseline_reroute | -93.0 | -0.154 | 10/10 seeds | -0.6 | +0.0 |
| 1000Genome 8ch | congestion | baseline | -208.0 | -0.345 | 10/10 seeds | -26.9 | +0.0 |
| 1000Genome 8ch | congestion | baseline_reroute | -208.0 | -0.345 | 10/10 seeds | -26.9 | +0.0 |
| 1000Genome 8ch | link failure | baseline | -538.1 | -0.894 | 10/10 seeds | -86.1 | -26.5 |
| 1000Genome 8ch | link failure | baseline_reroute | -93.3 | -0.155 | 10/10 seeds | -0.4 | +0.0 |
| Montage 0.1° | normal | baseline | -0.4 | -0.013 | 10/10 seeds | +0.0 | +0.0 |
| Montage 0.1° | normal | baseline_reroute | -0.4 | -0.013 | 10/10 seeds | +0.0 | +0.0 |
| Montage 0.1° | congestion | baseline | -0.6 | -0.020 | 10/10 seeds | +0.0 | +0.0 |
| Montage 0.1° | congestion | baseline_reroute | -0.6 | -0.020 | 10/10 seeds | +0.0 | +0.0 |
| Montage 0.1° | link failure | baseline | -4.3 | -0.136 | 10/10 seeds | -71.8 | -36.5 |
| Montage 0.1° | link failure | baseline_reroute | -2.0 | -0.064 | 10/10 seeds | -8.5 | +0.0 |

**Supplementary ablation** (not part of the 180 main runs): `agents_static` uses the agents' initial plan but never reacts to events. It separates planning up front from coordinating during events. Same seeds; nothing tuned.

| Workflow | Scenario | agents_static (× D) | agents (× D) | late: static / agents | failed: static / agents |
|---|---|---|---|---|---|
| 1000Genome 8ch | normal | 0.800 ± 0.038 | 0.800 ± 0.038 | 0.0 / 0.0 | 0.0 / 0.0 |
| 1000Genome 8ch | congestion | 1.026 ± 0.112 | 0.827 ± 0.047 | 9.6 / 0.0 | 0.0 / 0.0 |
| 1000Genome 8ch | link failure | 1.343 ± 0.159 | 0.800 ± 0.037 | 60.1 / 0.0 | 28.5 / 0.0 |
| Montage 0.1° | normal | 0.840 ± 0.017 | 0.840 ± 0.017 | 0.0 / 0.0 | 0.0 / 0.0 |
| Montage 0.1° | congestion | 0.840 ± 0.017 | 0.833 ± 0.014 | 0.0 / 0.0 | 0.0 / 0.0 |
| Montage 0.1° | link failure | 1.082 ± 0.033 | 0.950 ± 0.025 | 69.8 / 0.0 | 37.2 / 0.0 |

**Supplementary: max-min fair sharing** (a robustness check outside the main results). The same 180 runs with weighted max-min fair sharing instead of proportional sharing; nothing re-tuned. Mean completion (× D), proportional → max-min; and the agents' paired wins under max-min.

| Workflow | Scenario | baseline | baseline_reroute | agents | Agents faster than baseline / baseline_reroute (max-min) |
|---|---|---|---|---|---|
| 1000Genome 8ch | normal | 0.955 → 0.955 | 0.955 → 0.955 | 0.800 → 0.798 | 10/10 / 10/10 |
| 1000Genome 8ch | congestion | 1.172 → 1.168 | 1.172 → 1.168 | 0.827 → 0.822 | 10/10 / 10/10 |
| 1000Genome 8ch | link failure | 1.694 → 1.694 | 0.955 → 0.955 | 0.800 → 0.798 | 10/10 / 10/10 |
| Montage 0.1° | normal | 0.853 → 0.851 | 0.853 → 0.851 | 0.840 → 0.837 | 10/10 / 10/10 |
| Montage 0.1° | congestion | 0.853 → 0.851 | 0.853 → 0.851 | 0.833 → 0.825 | 10/10 / 10/10 |
| Montage 0.1° | link failure | 1.087 → 1.086 | 1.014 → 1.009 | 0.950 → 0.944 | 10/10 / 10/10 |

**Supplementary: LLM mode** (`mode=llm`, reported separately; not part of the 180 main runs). Same 60 cells as `agents`, but Claude (claude-opus-5-5) makes the coordinator's final decision (one call per initial plan and per event that has a proposal). 129 Claude decisions, 114 identical to what the rule coordinator would have chosen, 0 fallbacks to rules; API spend upper bound $5.94 (including a dev smoke test).

| Workflow | Scenario | agents, rule (× D) | agents, LLM (× D) | late: rule / LLM | LLM faster than rule | LLM faster than baseline / baseline_reroute |
|---|---|---|---|---|---|---|
| 1000Genome 8ch | normal | 0.800 ± 0.038 | 0.783 ± 0.014 | 0.0 / 0.0 | 2/10 (slower on 0) | 10/10 / 10/10 |
| 1000Genome 8ch | congestion | 0.827 ± 0.047 | 0.811 ± 0.041 | 0.0 / 0.0 | 2/10 (slower on 0) | 10/10 / 10/10 |
| 1000Genome 8ch | link failure | 0.800 ± 0.037 | 0.783 ± 0.014 | 0.0 / 0.0 | 2/10 (slower on 0) | 10/10 / 10/10 |
| Montage 0.1° | normal | 0.840 ± 0.017 | 0.840 ± 0.017 | 0.0 / 0.0 | 0/10 (slower on 0) | 10/10 / 10/10 |
| Montage 0.1° | congestion | 0.833 ± 0.014 | 0.834 ± 0.016 | 0.0 / 0.0 | 1/10 (slower on 4) | 10/10 / 10/10 |
| Montage 0.1° | link failure | 0.950 ± 0.025 | 0.949 ± 0.025 | 0.0 / 0.0 | 1/10 (slower on 0) | 10/10 / 10/10 |

**Supplementary: competing workflows** (not part of the 180 main runs). 1000Genome 8ch and Montage 0.1° start together on the `normal` network; each keeps its own data_scale and deadline D. Completion is shown as a fraction of each workflow's own D. Same evaluation seeds; nothing tuned.

| Planner | 1000Genome 8ch completion (× its D) | 1000Genome 8ch late | Montage 0.1° completion (× its D) | Montage 0.1° late | Runs where every workflow met its D |
|---|---|---|---|---|---|
| baseline | 0.966 ± 0.043 | 0.7 | 1.139 ± 0.093 | 8.2 | 0/10 |
| baseline_reroute | 0.966 ± 0.043 | 0.7 | 1.139 ± 0.093 | 8.2 | 0/10 |
| agents | 0.836 ± 0.020 | 0.0 | 0.996 ± 0.039 | 0.9 | 7/10 |

Agents vs. baseline: faster on 10/10 seeds for 1000Genome 8ch and 10/10 seeds for Montage 0.1°.

Agents vs. baseline_reroute: faster on 10/10 seeds for 1000Genome 8ch and 10/10 seeds for Montage 0.1°.
<!-- RESULTS:END -->

![Completion time by scenario and planner](../results/completion_time.png)

![Late and failed transfers by scenario and planner](../results/failures.png)

The end of the results table also has four supplementary experiments that are not part of the 180
main runs:
- **`agents_static`:** the agents' initial plan with no event reactions, which separates planning
  from coordination.
- **Competing workflows:** both result workflows share the network at once.
- **Max-min fair sharing:** the same 180 runs under a different bandwidth-sharing model, to check
  that the conclusions don't depend on my simple sharing rule.
- **LLM mode (`mode=llm`):** the same agents, but Claude makes the coordinator's final decision with
  one API call per plan or event, reported separately. Every prompt and answer is in the logs, and
  these runs also replay exactly without calling the API.

<!-- FINDINGS:START -->
When the StarLight-Caltech link fails, the baseline on 1000Genome 8ch takes 1.69 D, and 26.5 transfers per run time out at least once. Rerouting alone brings it to 0.96 D and the agents to 0.80 D, so rerouting covers 83% of the agents' gain. On Montage 0.1° the same three numbers are 1.09, 1.01 and 0.95 D, and rerouting covers 53%.

Congestion is where coordination paid off. On 1000Genome 8ch the rerouting baseline ignores the surge, so it scores the same result as the plain baseline: 1.17 D with 26.9 late transfers per run. The agents move transfers off the congested link and finish in 0.83 D with 0.0 late, faster on 10 of 10 seeds.

With no events at all the agents are already 16% faster than the baseline on 1000Genome 8ch (1.5% on Montage 0.1°), because they spread large transfers over parallel routes from the start. That plan alone does not carry them through events, though. Without reactions (agents_static) the same plan takes 1.03 D under congestion and 1.34 D under the link failure, against 0.83 and 0.80 D when the agents react.

Congestion barely touched Montage 0.1° (baseline 0.853 D in normal, 0.853 D with the surge), because Montage moves most of its data after the surge window closes. The agents' small edge there (0.840 and 0.833 D, -0.4 s per run in normal) is the planning effect again.

The agents lost on the smaller Montage 0.05° workflow used for tuning, in normal (0.966 D against 0.962 D) and congestion (0.977 D against 0.962 D) over the tuning seeds. Their start-of-run forecast can only assume today's network, and it sometimes chose a rebalanced plan that ran slower than plain lowest-delay routing.

Rerouting has its own failure mode. On Montage 0.1° it sends every stuck transfer to the same backup route and still leaves 8.5 late transfers per run, where the agents, spreading and prioritizing, leave 0.0. Across all 120 paired comparisons on the result workflows, they were never slower.
<!-- FINDINGS:END -->

## 7. Replay and audit

Every decision by every planner (baselines included) is one line in a compressed JSON log. Here is
a real line, from 1000Genome 8ch, `link_failure`, seed 3, agents. I shortened it to 5 of its 10
tool calls and 1 of its 42 plan entries:

```json
{"run_id": "1000genome-8ch__link_failure__seed3__agents", "seq": 1, "t": 90.2874, "agent": "coordinator",
 "trigger": {"type": "link_down", "link": ["StarLight", "Caltech"], "t": 90.2874, "seq": 1},
 "saw": {"affected": 25, "busy_links": [], "down_links": [["Caltech", "StarLight"]], "forecast_change_s": 480.0014739691352, "forecast_keep_s": null},
 "tool_calls": [
   {"agent": "workflow_agent", "tool": "get_workflow_requirements", "args": {}, "result": "174 transfers"},
   {"agent": "workflow_agent", "tool": "get_paths_many", "args": {"pairs": "<16 items, sha256 42babf52b3c5>", "k": 1, "avoid_down": true}, "result": "16 entries"},
   {"agent": "coordinator", "tool": "simulate_plan", "args": {"plan": "<42 items, sha256 126ba983a159>"}, "result": "forecast: completion 480.001 s, late 0, failed 0"},
   {"agent": "coordinator", "tool": "simulate_plan", "args": {"plan": {}}, "result": "forecast: does not complete, late 42, failed 13"},
   {"agent": "coordinator", "tool": "submit_plan", "args": {"plan": "<42 items, sha256 126ba983a159>"}, "result": "valid=True, accepted 42, rejected 0"}],
 "decision": {"chr3n-4001-5001.tar.gz@FNAL": {"path": ["Caltech", "UCSD", "FNAL"], "priority": 2, "start_s": 90.2874}},
 "rejected": {},
 "reason": "link_down: rerouted 25 of 25 affected transfer(s) by projected load; 17 priority update(s)"}
```

`python scripts/replay.py --all` rebuilds each of the 180 runs from its manifest and drives it with
the logged decisions only, with no agent code. It checks that every event arrives exactly as
logged, and compares all metrics with the recorded ones. All 180 runs replay exactly. The same code
gives byte-identical results in separate processes, and a fresh clone reproduces `summary.csv`
byte for byte on the same platform. On a different CPU architecture (Linux x86-64 in CI) the last
digit of a floating-point value can differ, so CI checks that case with the same 1e-9 tolerance
replay uses.

## 8. Limitations

- **Sharing is simplified.** Transfers on a link split its free capacity in proportion to priority.
  There are no TCP dynamics, and both directions of a link share one capacity. Re-running
  everything under max-min fair sharing (supplementary table) gives the same picture.
- **The network is invented.** Its numbers, background load model and events are not real
  measurements.
- **Placement is random.** Tasks go to sites by a hash, which creates more cross-site transfers
  than a real scheduler would.
- **Compute is unlimited.** Tasks start as soon as their inputs arrive.
- **File sizes are scaled** by `data_scale` to make the network matter.
- **The main results use rules, not an LLM.** LLM mode is a small supplementary test: one model,
  one prompt (never tuned on the evaluation runs), and no tool use by the model itself.
- **Forecasts are persistence-only.** They assume today's network continues, which is wrong for
  outages and surges that end. On the small Montage workflow this sometimes led the agents to a
  worse plan.
- **The test set is small.** Apart from one two-workflow test, it runs one workflow at a time, with
  one event per scenario, two result workflows and 10 seeds. The congestion window also happens not to overlap Montage's heavy
  traffic.

## 9. Next steps

| What was built | SciNet milestone / task |
|---|---|
| Workflow traces → transfer sizes, dependencies, deadlines | M1: 1.1.1, 1.1.3, 1.2.2 |
| Simulated network with changing capacity, congestion, failure | M3: 3.1.1, 3.1.2, 3.1.3 |
| Tools for agents to read state and test plans | M3: 3.1.5 |
| Workflow, network, and coordinator agents | M2: 2.2.1, 2.2.2, 2.2.3 (partly), 2.2.6 |
| Plan validation | M3: 3.2.4 |
| Decision log + replay | M2: 2.3.5; M3: 3.3.5 |
| Experiment harness | M3: 3.2.3 |
| Agents vs. baselines on completion time and failures | M2: 2.4.4; M3: 3.3.1, 3.3.2, 3.3.4; M4: 4.4.2 (which benefits come from coordination vs. rerouting) |

This prototype covers parts of M1–M3 in simulation. It does not include a network foundation
model (M1 task 1.3) or any hardware work (M5). The pieces have small, separate interfaces, which
should make them easy to connect to other work:
- the extractor's transfer list;
- the `Planner` interface;
- the tool functions;
- the MCP server.

The next things I would try:
- many workflows competing at once, with rules for fairness between them (the two-workflow test
  at the end of the results table shows the small workflow still suffers most);
- forecasts that know an outage or surge is temporary;
- an LLM coordinator that can call the MCP tools itself, compared with these rules on more seeds;
- replacing the synthetic map with a real topology and measured traffic, if that is available.

## 10. How to run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/run_experiments.py
python scripts/replay.py --all
python scripts/make_tables.py && python scripts/make_plots.py
pytest -q
```
