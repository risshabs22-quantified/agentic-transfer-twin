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
    env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT,
                         capture_output=True, text=True, check=True)
    return out.stdout
