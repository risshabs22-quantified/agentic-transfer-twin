"""Download the four public WfInstances workflow traces (and their license) into data/raw/.

Files that already exist are skipped, so this is safe to re-run. The files are also
committed to git, so the repo works offline; this script documents exactly where they came from.

Usage:
    python scripts/fetch_data.py
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
BASE = "https://raw.githubusercontent.com/wfcommons/WfInstances/main"

# (url, local file name). Comments say how each file is used in the experiments.
FILES: list[tuple[str, str]] = [
    (f"{BASE}/pegasus/1000genome/1000genome-chameleon-2ch-100k-001.json",
     "1000genome-chameleon-2ch-100k-001.json"),  # dev workflow, 52 tasks
    (f"{BASE}/pegasus/montage/montage-chameleon-2mass-005d-001.json",
     "montage-chameleon-2mass-005d-001.json"),  # dev workflow, 58 tasks
    (f"{BASE}/pegasus/1000genome/1000genome-chameleon-8ch-100k-001.json",
     "1000genome-chameleon-8ch-100k-001.json"),  # result workflow, 208 tasks
    (f"{BASE}/pegasus/montage/montage-chameleon-2mass-01d-001.json",
     "montage-chameleon-2mass-01d-001.json"),  # result workflow, 103 tasks
    (f"{BASE}/LICENSE", "LICENSE-WfInstances.txt"),  # LGPL-3.0; must travel with the data
]


def fetch_all(raw_dir: Path = RAW_DIR) -> None:
    """Download every file in FILES into raw_dir, skipping ones already present."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    for url, name in FILES:
        dest = raw_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"skip   {name} (already present)")
            continue
        print(f"fetch  {name}")
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        # Write to a temporary name first so an interrupted download never leaves a half file.
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        print(f"       {len(data):,} bytes")


if __name__ == "__main__":
    fetch_all()
