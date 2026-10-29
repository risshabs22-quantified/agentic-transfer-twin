Under the link failure, on 1000Genome 8ch the baseline took 1.69 D with 26.5 failed transfers per run, simple rerouting 0.96 D, and the agents 0.80 D, so rerouting alone recovered 83% of the agents' improvement; on Montage 0.1° the baseline took 1.09 D with 36.5 failed transfers per run, simple rerouting 1.01 D, and the agents 0.95 D, so rerouting alone recovered 53% of the agents' improvement.

Congestion is where coordination mattered most: on 1000Genome 8ch baseline_reroute ignores surges and was identical to the baseline (1.17 D, 26.9 late transfers per run), while the agents, which move transfers off the congested link, took 0.83 D with 0.0 late and were faster on 10/10 seeds.

Part of the agents' advantage is planning, not reacting: with no events at all they were already 16% faster than the baseline on 1000Genome 8ch and 1.5% faster on Montage 0.1°, by spreading large transfers over parallel routes; but the same initial plan without event reactions (agents_static) took 1.03 D under congestion and 1.34 D under the link failure on 1000Genome 8ch, versus 0.83 D and 0.80 D when the agents react.

Where there was little to fix, the agents gained little: congestion did not stress Montage 0.1° (baseline 0.853 D in normal and 0.853 D under congestion, because Montage moves most of its data after the surge window ends), and the agents' edge there (0.840 D in normal, 0.833 D under congestion; -0.4 s per run in normal) is a small planning effect, not a response to congestion.

The agents did not always help: on the smaller Montage 0.05° workflow used for tuning, they were slower than the baseline in normal (0.966 D vs. 0.962 D) and congestion (0.977 D vs. 0.962 D) (means over the tuning seeds): their start-of-run forecast can only assume today's network, and it sometimes picked a rebalanced plan that then ran slower than plain lowest-delay routing.

On Montage 0.1° under the link failure, simple rerouting moved every stuck transfer onto the same backup route and still left 8.5 late transfers per run, versus 0.0 for the agents, which spread and prioritized them; across all 120 paired comparisons on the result workflows the agents were never slower.
