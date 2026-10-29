"""Decision log: one JSON object per line, per decision, in results/logs/<run_id>.jsonl.gz.

Every time a planner is asked for a decision (the initial plan, and every event during the run)
we record what triggered it, what the planner saw, which tools it
called, what it decided, which entries were rejected, and its one-line reason. The log is enough
to replay the run exactly without running any agent code (see att/replay.py).

Files are written byte-for-byte deterministically (gzip timestamp fixed to 0, no file name in the
header), so the same run always produces the same file.
"""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any

FIELDS = ["run_id", "seq", "t", "agent", "trigger", "saw", "tool_calls", "decision", "rejected", "reason"]


def to_lines(run_id: str, decisions: list[dict[str, Any]]) -> list[str]:
    lines = []
    for d in decisions:
        rec = {"run_id": run_id, **{k: d.get(k) for k in FIELDS if k != "run_id"}}
        lines.append(json.dumps(rec, allow_nan=False, separators=(",", ":")))
    return lines


def write_log(path: str | Path, run_id: str, decisions: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ("\n".join(to_lines(run_id, decisions)) + "\n").encode()
    buf = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0) as gz:
        gz.write(data)
    path.write_bytes(buf.getvalue())


def read_log(path: str | Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt") as fh:
        return [json.loads(line) for line in fh if line.strip()]
