"""Small helpers shared by tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
SITES = ["Caltech", "UCSD", "FNAL", "ORNL"]
SOURCE = "CERN"


def run_python(code: str, hashseed: str) -> str:
    """Run `code` in a fresh Python process with a given PYTHONHASHSEED and return its stdout.

    Different hash seeds make Python's built-in hash() of strings (and so set iteration order)
    differ between the two processes, which is exactly what a determinism test must survive.
    """
    env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return out.stdout
