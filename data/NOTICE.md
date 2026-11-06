# Data notice

The four workflow traces in `data/raw/` are **real, public data** from the
[WfCommons WfInstances](https://github.com/wfcommons/WfInstances) project, downloaded
unmodified by `scripts/fetch_data.py`:

| File | Workflow | Tasks | Used as |
|---|---|---|---|
| `1000genome-chameleon-2ch-100k-001.json` | 1000Genome, 2 chromosomes | 52 | dev (tuning agents) |
| `montage-chameleon-2mass-005d-001.json` | Montage, 0.05° | 58 | dev (tuning agents) |
| `1000genome-chameleon-8ch-100k-001.json` | 1000Genome, 8 chromosomes | 208 | result |
| `montage-chameleon-2mass-01d-001.json` | Montage, 0.1° | 103 | result |

WfInstances is licensed under the **GNU LGPL v3.0**; the license is kept next to the data
as `data/raw/LICENSE-WfInstances.txt`.

Please cite:

> T. Coleman, H. Casanova, L. Pottier, M. Kaushik, E. Deelman, R. Ferreira da Silva,
> "WfCommons: A Framework for Enabling Scientific Workflow Research and Development,"
> *Future Generation Computer Systems*, 2022.

What this project adds on top of the traces is **synthetic**: which site each task runs at,
the deadlines, the network map and all its numbers, and the `data_scale` multiplier on file sizes.
