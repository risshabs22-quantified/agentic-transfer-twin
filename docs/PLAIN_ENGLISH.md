# The whole project in plain English

This guide explains everything in this repository without assuming you know any programming or
networking. Every idea is explained from scratch, and every number comes from the project's result
files. If you later want the exact rules and formulas behind each part, the
[technical reference](HOW_IT_WORKS.md) has them, section by section.

**Contents**

1. [The problem](#1-the-problem)
2. [The question this project asks](#2-the-question-this-project-asks)
3. [What is real and what is made up](#3-what-is-real-and-what-is-made-up)
4. [Step 1: the recipes](#4-step-1-the-recipes)
5. [Step 2: from recipe to shipping list](#5-step-2-from-recipe-to-shipping-list)
6. [Step 3: the pretend network](#6-step-3-the-pretend-network)
7. [Step 4: the simulation](#7-step-4-the-simulation)
8. [Step 5: three ways to plan the shipping](#8-step-5-three-ways-to-plan-the-shipping)
9. [Step 6: the service window (MCP)](#9-step-6-the-service-window-mcp)
10. [How the comparison is kept fair](#10-how-the-comparison-is-kept-fair)
11. [The flight recorder and replay](#11-the-flight-recorder-and-replay)
12. [The experiments](#12-the-experiments)
13. [The results, and how to read them](#13-the-results-and-how-to-read-them)
14. [The limits, and what was done about them](#14-the-limits-and-what-was-done-about-them)
15. [One file's journey](#15-one-files-journey)
16. [What is in each folder](#16-what-is-in-each-folder)
17. [How to run it yourself](#17-how-to-run-it-yourself)
18. [Glossary](#18-glossary)

---

## 1. The problem

Big science projects run their analysis as a **workflow**: a long list of computing jobs, called
**tasks**, where many tasks need the output of earlier ones. Think of a factory assembly line where
each station needs parts from the stations before it.

These tasks don't all run in one building. They run at computing centers in different places, so
when a task in one place needs a file made somewhere else, that file has to be sent across the
internet first. The task can't start until the file arrives.

The connections between computing centers are like highways. They can only carry so much at once,
other traffic shares them, they get jammed, and sometimes one closes completely. When a file is
late, the task waiting for it is late, and so is every task after that one. One closed highway can
delay a whole project.

Somebody, or something, has to decide **which route each file takes, which files go first, and what
to do when a road jams or closes**. That is the job this project studies.

---

## 2. The question this project asks

Can a small team of computer programs, called **agents**, plan those file shipments better than
simple fixed rules? And when they do better, is it because they are clever, or would a simple
"take a detour when a road closes" rule have done just as well?

To answer that fairly, the project builds a complete pretend world (real science jobs, a pretend
network), lets three different planners handle exactly the same situations, writes down every
decision they make, and compares how fast each one gets the work done.

---

## 3. What is real and what is made up

**Real:** the science jobs. The project uses published records of two real scientific workflows,
including which tasks exist, which tasks need which files, how big each file is, and how long each
task actually took to run.

**Made up (and labeled as made up everywhere):**

- which computing center each task runs at;
- the deadlines;
- the network: its map, how big each connection is, how long data takes to cross it, the other
  traffic on it, the traffic jam and the road closure;
- a multiplier that makes the files bigger (explained in section 5).

No real network measurements are used, because none were available and the project uses only public
data.

---

## 4. Step 1: the recipes

The project uses records of two kinds of real scientific workflows, published by a research group
called WfCommons. Think of each record as a detailed recipe: every step, which ingredients each step
needs, how much of each ingredient there is, and how long each step takes.

- **1000Genome** comes from genetics. It processes data from the 1000 Genomes Project, which
  sequenced the DNA of thousands of people. It is "data-heavy": it moves a lot of large files.
- **Montage** comes from astronomy. It stitches many small sky images into one large mosaic. It
  moves many small files in waves.

There are four recipes in total:

| Recipe | Steps (tasks) | Used for |
|---|---|---|
| 1000Genome, 2 chromosomes | 52 | practice (tuning settings) |
| Montage, 0.05° patch of sky | 58 | practice (tuning settings) |
| 1000Genome, 8 chromosomes | 208 | the real test |
| Montage, 0.1° patch of sky | 103 | the real test |

The two small "practice" recipes were used only to adjust settings. The two big ones were kept
untouched until the final test, the way a teacher keeps the exam questions separate from the
homework.

---

## 5. Step 2: from recipe to shipping list

A program reads each recipe and works out the shipping list: every file that must travel between
computing centers.

**Where each task runs.** There are four computing centers: Caltech, UCSD, FNAL and ORNL. The raw
starting data begins at a fifth place, CERN. Each task is assigned to one of the four centers by a
fixed scrambling formula. It works like rolling dice, except the same "seed" number always gives the
same rolls (seeds are explained in section 10). Different seeds give different arrangements, which
gives the experiment many different situations to test.

**Which files must travel.** If a task needs a file that was made at a different center, or a raw
file from CERN, that file goes on the shipping list. If several tasks at the same center need the
same file, it is shipped there only once.

**Deadlines.** First the program works out the fastest the whole workflow could possibly finish if
files traveled instantly. That's the length of the longest chain of steps that must happen one after
another, called the **critical path**. Think of cooking a dinner: even with unlimited helpers, the
meal can't be ready before the slowest chain of "this must happen before that" steps is done.

The workflow's **deadline, D**, is set to 1.5 times that fastest possible time, so there is some
breathing room. Each file then gets its own deadline: the latest moment it can arrive without making
the workflow miss D.

**Making files bigger.** At their real sizes, these files are so small compared with modern network
connections that nothing interesting happens. So every file size is multiplied by a fixed number,
the **data scale**: 100 for the big 1000Genome test and 300 for the big Montage test. How those
numbers were picked, by a fixed rule that couldn't favor anyone, is in section 10.

---

## 6. Step 3: the pretend network

The network is a made-up map of six places connected by seven links. A **link** is like a highway
between two cities.

Each link has two properties:

- **capacity (bandwidth):** how much data it can carry per second, like the number of lanes. It is
  measured in **Gbps**, billions of bits per second. Two links carry 400 Gbps and five carry 100 Gbps.
- **delay (latency):** how long a single bit takes to travel across, like the driving time. It is
  measured in milliseconds, from 2 ms to 90 ms.

| Link | Capacity | Delay |
|---|---|---|
| CERN – StarLight | 400 Gbps | 90 ms |
| StarLight – FNAL | 400 Gbps | 2 ms |
| StarLight – Caltech | 100 Gbps | 50 ms |
| StarLight – ORNL | 100 Gbps | 15 ms |
| FNAL – ORNL | 100 Gbps | 15 ms |
| Caltech – UCSD | 100 Gbps | 5 ms |
| FNAL – UCSD | 100 Gbps | 55 ms |

StarLight is a hub in the middle: everything coming from CERN passes through it. The quickest road to
UCSD runs through Caltech, so the StarLight–Caltech link carries traffic for two destinations at once.
If that link closes, the only way left into Caltech and UCSD is the FNAL–UCSD link.

**Other traffic.** Real networks are shared, so each link carries "background" traffic from other
users. On average it takes about 20% of each link. It rises and falls in a slow wave, plus small
random wobbles, and it never takes more than 95%, so an open link always keeps at least 5% free.

**Three situations** are tested. Their times are given as fractions of the deadline D, so a short
workflow and a long one get proportionally the same trouble:

- **normal:** only the background traffic;
- **congestion (a traffic jam):** extra traffic floods the StarLight–ORNL link from 5% to 50% of the
  way to the deadline, leaving it only about 5% of its capacity;
- **link failure (a road closure):** the StarLight–Caltech link shuts down from 15% to 75% of the way
  to the deadline.

---

## 7. Step 4: the simulation

The **simulation** is a computer program that plays out what happens, like a very fast, very precise
movie of the shipments and tasks. People call this kind of model a **digital twin**: a software copy
of a real system that you can run "what if" experiments on without touching the real thing.

How the movie works:

- **Files move over their route.** All the files using a link share it. A file marked urgent
  (**priority 2**) gets twice the share of a normal one (**priority 1**). A file's speed is set by the
  most crowded link on its route, the way a car trip is slowed by its worst stretch of road.
- **Arrival.** When the last bit of a file has been sent, it arrives after the route's driving time.
- **Tasks start** as soon as all the steps before them are done and all their files have arrived.
  They take exactly as long as they took in real life.
- **Road closures.** A file whose route includes a closed link is stuck. If it stays stuck for 10%
  of the deadline D, that shipping attempt is declared **failed** and starts over from zero, still
  waiting on its route unless a planner moves it.
- **The end.** The movie ends when every task is done. If it reaches 20 times the deadline first, the
  run counts as not completed.

The movie doesn't move in fixed ticks like a clock. It jumps straight from one meaningful moment to
the next (a file arrives, a task ends, a road closes), so all the times are exact and a whole run
takes less than a second.

**What gets measured** for every run:

- **completion time:** when the last task finished, the main score (lower is better);
- **late transfers:** files that arrived after their own deadline;
- **failed transfers:** files that had at least one shipping attempt time out;
- plus how much data moved, the average speed, how long tasks spent waiting for data, how many times
  a route was changed, and how many decisions the planner made.

---

## 8. Step 5: three ways to plan the shipping

A **planner** decides each file's route, how urgent it is, and when it may start. The simulation asks
the planner once at the start, and again every time something happens (a road closes or reopens, a
jam starts or ends, or a shipment fails).

**Planner 1: the baseline.** Every file takes the quickest route on the map, nothing is marked urgent,
and the planner never changes its mind. If a road closes, its files just wait. This is the simple
rule everything else is compared with.

**Planner 2: the baseline with detours.** The same, plus one rule: when a road closes, every file
whose route uses it is moved to the quickest route that avoids it. It ignores traffic jams and never
marks anything urgent. It exists to answer one question: "Isn't this just rerouting?"

**Planner 3: the agent team.** Three programs, each with one job, a bit like the staff of a control
room:

- **The workflow agent** works out which files are most urgent. For each file it estimates the
  earliest it could possibly arrive, compares that with the file's deadline, and calls the
  difference the **slack**: how much time there is to spare. The 30% of files with the least spare
  time are marked urgent.
- **The network agent** looks at the roads. For each file it finds the three quickest routes and
  estimates how long the file would take on each with today's traffic. It also flags links that are
  more than 70% full.
- **The coordinator** makes the final plan.
  - **At the start** it writes three complete plans:
    1. one that spreads big files across parallel roads so no single link is overloaded;
    2. one that puts each file on its own fastest road;
    3. one that simply uses the quickest roads on the map.

    It runs a quick **forecast** of each (a mini simulation, explained below), picks the best, and
    only abandons the simple third plan if another is predicted to be at least 5% faster.
  - **When something happens**, it only reconsiders the files that are affected. Files go off a
    closed road, spread over the remaining routes. Files go off a jammed road if another is
    predicted to be faster. Files return to a reopened road if that is faster. It also re-checks
    which files are most urgent.
  - **Before acting**, it forecasts "with the change" and "without the change", and only makes the
    change if it isn't predicted to make things worse.

**What a forecast is.** It's a mini simulation that assumes the network stays exactly as it is right
now: today's traffic stays, a closed road stays closed, nothing new happens. It can't see the
future, because it only knows the present. That keeps it honest, but it also means it can be wrong:
a closed road usually reopens.

**Two extra versions of the agent team** were tested on the side:

- **agents without reactions:** the same starting plan, but it never responds to anything that
  happens. This shows how much of the agents' advantage comes from planning well at the start versus
  reacting well later.
- **LLM mode:** the same team, except the final decision is handed to **Claude**, an AI language
  model made by Anthropic. Claude reads a summary of what the other agents found and chooses. If its
  answer is unusable, the team falls back to its normal rules. Every question asked and every answer
  given is saved. A hard spending limit of $25 was set; the full test cost about $6.

---

## 9. Step 6: the service window (MCP)

The agents are not allowed to look inside the simulation. They can only ask questions through a
fixed set of **tools**, offered by a small server that speaks **MCP (Model Context Protocol)**. MCP is
a standard way for AI programs to discover and use tools, the way a USB plug is a standard way to
connect devices. Think of it as a service window: the agents can only ask what the window offers.

The questions they can ask:

| Tool | In plain words |
|---|---|
| `get_workflow_requirements` | "Which files need to move, how big are they, when will each be ready, and when is each due?" |
| `get_network_state` | "How busy is each road right now, and which roads are closed?" |
| `get_paths` | "What are the quickest routes from here to there?" |
| `estimate_transfer_time` | "How long would this file take on this route with today's traffic?" |
| `simulate_plan` | "If I did this, how would things turn out, assuming nothing changes?" |
| `submit_plan` | "Is this plan allowed?" (checks that routes are real and settings make sense) |

There are also batch versions that answer many questions of the same kind at once.

This matters for three reasons. The agents can't cheat by peeking at the future, because nothing
behind the window shows it. The same window could later be connected to a real network instead of
the pretend one, and the agents wouldn't need to change. And any program that speaks MCP can use the
tools: the project includes a screenshot of a standard inspection app (the MCP Inspector) asking for
routes, and instructions for connecting the Claude Desktop app.

---

## 10. How the comparison is kept fair

**Same dice for everyone.** A computer can't roll real dice, so it uses a **random number generator**
started from a number called a **seed**. The same seed always produces the same "random" numbers. In
each comparison, all three planners get the same seed, which means the same task locations, the same
background traffic and the same jams and closures. When one planner beats another on the same seed,
luck played no part.

**Practice and exam kept apart.** Settings were adjusted only on the two small practice recipes,
using seeds 100 to 104. The final test used the two big recipes with seeds 0 to 9, which were never
used for adjusting anything. All settings were locked in a file before the final test ran.

**Settings chosen by fixed rules.** The file-size multiplier was chosen before the agents even
existed, using only the baseline: the largest value from a fixed list at which the baseline still
finishes on time in normal conditions. Each trouble scenario was then checked to make sure it really
causes trouble. Congestion didn't affect the big Montage test. The rules allowed moving the jam to
the busiest road and making it as heavy as possible, which was tried, and it still didn't matter.
Making the jam last longer or start at a different time wasn't allowed, so the scenario was left
alone and the result reported as it was.

**No peeking.** The agents can only see the present through the service window, and automatic checks
prove that a road closure scheduled for later does not change any forecast made before it.

**No hand-typed numbers.** Every number in the results tables and summaries is computed by a program
from the saved results, and an automatic check fails if the documents ever disagree with the files.

**The same answer every time.** Running the same thing twice gives exactly the same result, down to
the last digit. The project avoids every source of hidden randomness it knows of (for example, it
never uses the computer's clock in decisions), and automatic checks run the same code in separate
programs and compare the outputs.

---

## 11. The flight recorder and replay

Every decision any planner makes is written down, like an airplane's flight recorder. Each entry
says:

- what triggered the decision (the start, or which event);
- what the planner looked at;
- every question it asked through the service window;
- exactly what it decided;
- anything that was rejected and why;
- a one-line reason in plain words.

**Replay** proves the record is complete. A replay rebuilds the run from its saved settings and feeds
the simulation only the recorded decisions, with none of the planners' own code running. Every event
must happen at exactly the recorded moment, and every final number must match. All 180 main runs, and
every extra run, replay exactly. For the AI language model runs this means they can be checked
without asking the AI anything again.

---

## 12. The experiments

The main experiment covers every combination of:

- 2 big recipes (1000Genome 8 chromosomes, Montage 0.1°),
- 3 situations (normal, congestion, link failure),
- 10 seeds (0 to 9),
- 3 planners (baseline, baseline with detours, agent team),

which makes **180 runs**.

Four extra experiments were run on the side, with the same seeds and nothing re-adjusted:

1. **agents without reactions**, to separate good starting plans from good reactions;
2. **two workflows at once**, both big recipes sharing the network at the same time;
3. **a different sharing rule**, where spare room on a road is handed to whoever can use it (called
   "max-min fair" sharing), to check that the conclusions don't depend on the simple sharing rule;
4. **LLM mode**, with Claude making the coordinator's final decisions.

---

## 13. The results, and how to read them

Times are given as a fraction of the deadline D:

- **1.00** means the workflow finished exactly at its deadline;
- **0.80** means it finished with 20% of the time to spare;
- **1.69** means it took 69% longer than allowed.

Lower is better, and anything above 1.00 missed the deadline. In the table below, each cell is the
average of 10 seeds, and the number in brackets is the average number of late file deliveries per
run.

**The headline:**

<!-- SUMMARY:START -->
Across 180 simulated runs, the agent team beat both baselines in all 120 same-seed comparisons and had 0 late transfers. Plain rerouting already fixes much of a link failure (83% of the agents' gain on 1000Genome 8ch, 53% on Montage 0.1°). Congestion is different: rerouting does nothing there, and on 1000Genome 8ch the agents finish at 0.83 D against 1.17 D, where D is the deadline.
<!-- SUMMARY:END -->

**The main table:**

<!-- RESULTS:START -->
Mean over 10 seeds: completion time as a fraction of the deadline D (late transfers per run). 1.00 means finished exactly on time; lower is better. Full tables: [`results/table.md`](results/table.md).

| Workflow | Scenario | baseline | baseline_reroute | agents |
|---|---|---|---|---|
| 1000Genome 8ch | normal | 0.95 (0.6) | 0.95 (0.6) | 0.80 (0.0) |
| 1000Genome 8ch | congestion | 1.17 (26.9) | 1.17 (26.9) | 0.83 (0.0) |
| 1000Genome 8ch | link failure | 1.69 (86.1) | 0.96 (0.4) | 0.80 (0.0) |
| Montage 0.1° | normal | 0.85 (0.0) | 0.85 (0.0) | 0.84 (0.0) |
| Montage 0.1° | congestion | 0.85 (0.0) | 0.85 (0.0) | 0.83 (0.0) |
| Montage 0.1° | link failure | 1.09 (71.8) | 1.01 (8.5) | 0.95 (0.0) |
<!-- RESULTS:END -->

**What the numbers say** (these sentences are generated by a program from the results, so they can't
drift):

<!-- FINDINGS:START -->
When the StarLight-Caltech link fails, the baseline on 1000Genome 8ch takes 1.69 D, and 26.5 transfers per run time out at least once. Rerouting alone brings it to 0.96 D and the agents to 0.80 D, so rerouting covers 83% of the agents' gain. On Montage 0.1° the same three numbers are 1.09, 1.01 and 0.95 D, and rerouting covers 53%.

Congestion is where coordination paid off. On 1000Genome 8ch the rerouting baseline ignores the surge, so it scores the same result as the plain baseline: 1.17 D with 26.9 late transfers per run. The agents move transfers off the congested link and finish in 0.83 D with 0.0 late, faster on 10 of 10 seeds.

With no events at all the agents are already 16% faster than the baseline on 1000Genome 8ch (1.5% on Montage 0.1°), because they spread large transfers over parallel routes from the start. That plan alone does not carry them through events, though. Without reactions (agents_static) the same plan takes 1.03 D under congestion and 1.34 D under the link failure, against 0.83 and 0.80 D when the agents react.

Congestion barely touched Montage 0.1° (baseline 0.853 D in normal, 0.853 D with the surge), because Montage moves most of its data after the surge window closes. The agents' small edge there (0.840 and 0.833 D, -0.4 s per run in normal) is the planning effect again.

The agents lost on the smaller Montage 0.05° workflow used for tuning, in normal (0.966 D against 0.962 D) and congestion (0.977 D against 0.962 D) over the tuning seeds. Their start-of-run forecast can only assume today's network, and it sometimes chose a rebalanced plan that ran slower than plain lowest-delay routing.

Rerouting has its own failure mode. On Montage 0.1° it sends every stuck transfer to the same backup route and still leaves 8.5 late transfers per run, where the agents, spreading and prioritizing, leave 0.0. Across all 120 paired comparisons on the result workflows, they were never slower.
<!-- FINDINGS:END -->

**The two charts.** The first shows how long each planner took in each situation, one panel per
recipe, with the deadline drawn as a dashed line. The second shows late and failed file deliveries.

![Completion time](../results/completion_time.png)

![Late and failed transfers](../results/failures.png)

**The extra experiments, in short:**

- **LLM mode:** Claude agreed with the normal rules most of the time, found a slightly better
  starting plan on a few 1000Genome seeds, and made no real difference on Montage. It still beat both
  simple planners on every seed.
- **Two workflows at once:** the agents were faster for both workflows on every seed and met both
  deadlines far more often than the simple planners. The small, rushed Montage workflow still
  suffered most, because nothing in the agents tries to be fair between workflows.
- **Different sharing rule:** every result moved by less than 0.01 of the deadline, and the planners
  finished in the same order.

---

## 14. The limits, and what was done about them

| Limit | Why it matters | What was done | What is still missing |
|---|---|---|---|
| The network is made up | Its numbers aren't real measurements | Everything made up is labeled; the agents only talk to the network through the service window, which is where a real network could plug in | Real network data |
| Bandwidth sharing is simplified | It could favor one planner | The whole experiment was repeated with a different sharing rule; same conclusions | The finer behavior of real internet traffic |
| Files were made bigger | Real sizes barely load the network | The multiplier was chosen by a fixed rule, before the agents existed, using only the baseline | Real file sizes |
| Task locations are random | A real scheduler would place tasks smarter | The same random placement is used for every planner, so comparisons stay fair | Smart placement |
| Unlimited computers | Tasks never wait for a free computer | Stated openly; task durations are real | Computer shortages |
| The agents might cheat | That would make the comparison worthless | They only see the present; checks prove a future event doesn't change their forecasts | |
| Adjusting settings on the test data | That inflates results | Practice recipes and practice seeds kept separate; settings locked before the test | |
| Forecasts assume nothing changes | They're wrong when a jam or closure ends | The coordinator needs a clear predicted gain before leaving the simple plan, and only changes things if the forecast isn't worse | Forecasts still mislead sometimes (the practice Montage loss) |
| The jam missed Montage's busy period | One situation tells us nothing about Montage | The jam was moved and made as heavy as the rules allowed; then reported as is | That cell is uninformative |
| "Maybe it's just rerouting" | It would overstate the agents | The detour-only planner and the no-reaction agents were both tested | |
| Results might not repeat | Claims couldn't be checked | Every run replays exactly; a fresh copy of the project reproduces the results; an automatic service re-runs everything on a different kind of computer | On a different kind of processor, one number differed in its 16th digit |
| The AI model gives different answers each time | Its runs can't be re-created by asking again | Every question and answer is saved and replays exactly; a spending limit was set | Only one AI model and one way of asking were tried |
| One workflow at a time | Real networks carry many | A two-workflow test | Rules for fairness between many workflows |
| Small test | Limits how fine the conclusions can be | Every comparison is on matching seeds, with the spread of results reported | 10 seeds, 2 big recipes, one event per situation |

---

## 15. One file's journey

This is a real file from the test, followed through one run: the big 1000Genome recipe, the road
closure situation, seed 3, planned by the agent team.

1. **The file.** It's called `chr3n-4001-5001.tar.gz` and is small, about 0.003 GB even after
   scaling. It is made by a task that runs at **Caltech**, and needed by a task at **FNAL**. So it has
   to travel from Caltech to FNAL.
2. **Its deadline.** The FNAL task must start by 392.871 seconds for the whole workflow to finish by
   its deadline of 601.916 seconds, so the file has to arrive by 392.871 seconds.
3. **The starting plan.** The workflow agent sees this file has little time to spare and marks it
   urgent. The coordinator compares its three plans by forecast and routes the file
   Caltech → StarLight → FNAL.
4. **The road closes.** At 90.287 seconds the StarLight–Caltech link shuts. The coordinator finds 25
   files whose routes use it, including this one even though it hasn't been made yet, and moves
   them. This file now goes **Caltech → UCSD → FNAL**. Before acting, the coordinator checked: with
   the change, the forecast finished at 480.0 seconds; without it, the forecast never finished,
   because forecasts assume the road stays closed forever.
5. **The file arrives.** Its task at Caltech finishes at 256.200 seconds and the file arrives at
   256.260 seconds, more than two minutes before its deadline. The whole workflow finishes at 480.002
   seconds, 0.797 of the deadline.

The same file under the other planners:

| Planner | Route | File ready | Arrived | On time? | Whole workflow finished |
|---|---|---|---|---|---|
| baseline | Caltech → StarLight → FNAL (never changed) | 806.340 s | 806.393 s | **late** | 1031.615 s (1.714 × deadline) |
| baseline with detours | moved to Caltech → UCSD → FNAL | 365.012 s | 365.072 s | on time | 590.284 s (0.981 × deadline) |
| agent team | moved to Caltech → UCSD → FNAL, marked urgent | 256.200 s | 256.260 s | on time | 480.002 s (0.797 × deadline) |

Under the baseline, the file itself was never stuck. The task that makes it was waiting for raw data
from CERN, and that data was stuck behind the closed road. The delay reached this file through the
chain of steps, which is why a single closure can hold up so much.

---

## 16. What is in each folder

| Folder or file | What it is |
|---|---|
| `README.md` | the front page |
| `docs/PLAIN_ENGLISH.md` | this guide |
| `docs/writeup.md` | the short research report |
| `docs/HOW_IT_WORKS.md` | the technical reference, with every rule and formula |
| `docs/BUILD_LOG.md` | a diary of how the project was built, every change from the original plan, and the settings tables |
| `data/` | the four published recipes and their license |
| `configs/` | three settings files: the network map, the situations, and the locked experiment settings |
| `att/` | the program itself: the shipping-list maker, the network, the simulation, the planners, the agents, the service window, the flight recorder and replay |
| `scripts/` | small programs you run, one per job: run the experiments, replay them, make the tables and charts, adjust settings, run the extra experiments |
| `tests/` | about 80 automatic checks that confirm everything still works and that the documents match the results |
| `results/` | everything the experiments produced: a table with one line per run, the flight records, per-run settings files, tables, findings and charts |

---

## 17. How to run it yourself

You need a computer with Python 3.10 or newer installed. Open a terminal in the project folder and
type these lines one at a time:

```bash
python -m venv .venv && source .venv/bin/activate     # makes a private workspace for this project (Windows: .venv\Scripts\activate)
pip install -r requirements.txt                       # installs the few add-ons the project needs
python scripts/run_experiments.py                     # runs all 180 experiments
python scripts/replay.py --all                        # replays all 180 from their flight records and checks they match
python scripts/make_tables.py && python scripts/make_plots.py   # rebuilds the tables, findings and charts
pytest -q                                             # runs all the automatic checks
```

To follow one file through a run, as in section 15:

```bash
python scripts/trace_transfer.py --run 1000genome-8ch__link_failure__seed3__agents --transfer chr3n-4001-5001.tar.gz@FNAL
```

---

## 18. Glossary

- **Ablation.** A test version with one ingredient added or removed, to measure what that ingredient
  is worth. Here: the detour-only planner and the agents without reactions.
- **Agent.** A program that gathers information, makes decisions and acts on its own within set
  rules. Here: the workflow agent, the network agent and the coordinator.
- **Background traffic.** Other people's data on the same links, taking part of their capacity.
- **Bandwidth (capacity).** How much data a link can carry per second, like the number of lanes on a
  highway.
- **Baseline.** The simple reference planner everything else is compared with.
- **baseline_reroute.** The name used in the tables for "the baseline with detours".
- **agents_static.** The name used in the tables for "agents without reactions".
- **Claude.** An AI language model made by Anthropic, used in the optional LLM mode.
- **Completion time.** When the last task of a workflow finished. Lower is better.
- **Congestion.** A traffic jam: extra traffic fills one link.
- **Coordinator.** The agent that turns the other agents' advice into the final plan.
- **Critical path.** The longest chain of steps that must happen one after another. The workflow can't
  finish faster than this, however fast the network is.
- **Data scale.** The number every file size was multiplied by so that the network matters.
- **Deadline (D).** The time the whole workflow should finish by: 1.5 times its critical path.
- **Delay (latency).** How long a bit takes to cross a link, like driving time.
- **Digital twin.** A software copy of a real system for running "what if" experiments.
- **Failed transfer.** A file whose shipment timed out at least once because its road was closed.
- **Flight recorder (decision log).** The saved list of every decision a planner made, with what it
  saw and why.
- **Forecast.** A quick mini simulation that assumes today's conditions continue unchanged.
- **Gbps.** Gigabits per second: billions of bits per second. Eight bits make one byte, so 100 Gbps
  carries 12.5 gigabytes per second.
- **Late transfer.** A file that arrived after its own deadline.
- **Link.** A connection between two places in the network, like a highway between two cities.
- **LLM (large language model).** An AI system that reads and writes text, such as Claude.
- **Link failure.** A road closure: a link stops carrying anything for a while.
- **Max-min fair sharing.** A rule for sharing a link where spare room goes to whoever can use it.
  Used as a check on the simpler main rule.
- **MCP (Model Context Protocol).** A standard way for AI programs to find and use tools, like a
  universal plug.
- **Paired comparison.** Comparing two planners on exactly the same situation (same seed) and
  counting who wins, so luck plays no part.
- **Planner.** Whatever decides each file's route, urgency and start time.
- **Priority.** How urgent a file is. Priority 2 gets twice the share of a busy link that priority 1
  gets.
- **Replay.** Re-running a recorded run using only its flight record, and checking every result
  matches.
- **Route (path).** The sequence of links a file travels over.
- **Seed.** The starting number for the computer's dice. The same seed gives the same "random"
  situation every time.
- **Simulation.** A program that plays out what would happen, step by step.
- **Slack.** Spare time: how much later something could happen without missing its deadline.
- **Task.** One computing job in a workflow.
- **Tool.** A single question the agents are allowed to ask through the service window.
- **Transfer.** One file being sent from one place to another.
- **Tuning.** Adjusting settings, done here only on practice data.
- **Workflow.** A scientific analysis broken into many tasks, where tasks depend on the outputs of
  earlier ones.
