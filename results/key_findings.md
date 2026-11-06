When the StarLight-Caltech link fails, the baseline on 1000Genome 8ch takes 1.69 D, and 26.5 transfers per run time out at least once. Rerouting alone brings it to 0.96 D and the agents to 0.80 D, so rerouting covers 83% of the agents' gain. On Montage 0.1° the same three numbers are 1.09, 1.01 and 0.95 D, and rerouting covers 53%.

Congestion is where coordination paid off. On 1000Genome 8ch the rerouting baseline ignores the surge, so it scores the same result as the plain baseline: 1.17 D with 26.9 late transfers per run. The agents move transfers off the congested link and finish in 0.83 D with 0.0 late, faster on 10 of 10 seeds.

With no events at all the agents are already 16% faster than the baseline on 1000Genome 8ch (1.5% on Montage 0.1°), because they spread large transfers over parallel routes from the start. That plan alone does not carry them through events, though. Without reactions (agents_static) the same plan takes 1.03 D under congestion and 1.34 D under the link failure, against 0.83 and 0.80 D when the agents react.

Congestion barely touched Montage 0.1° (baseline 0.853 D in normal, 0.853 D with the surge), because Montage moves most of its data after the surge window closes. The agents' small edge there (0.840 and 0.833 D, -0.4 s per run in normal) is the planning effect again.

The agents lost on the smaller Montage 0.05° workflow used for tuning, in normal (0.966 D against 0.962 D) and congestion (0.977 D against 0.962 D) over the tuning seeds. Their start-of-run forecast can only assume today's network, and it sometimes chose a rebalanced plan that ran slower than plain lowest-delay routing.

Rerouting has its own failure mode. On Montage 0.1° it sends every stuck transfer to the same backup route and still leaves 8.5 late transfers per run, where the agents, spreading and prioritizing, leave 0.0. Across all 120 paired comparisons on the result workflows, they were never slower.
