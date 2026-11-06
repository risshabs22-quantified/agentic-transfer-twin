from __future__ import annotations

import urllib.request
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
BASE = "https://raw.githubusercontent.com/wfcommons/WfInstances/main"

FILES: list[tuple[str, str]] = [
    (f"{BASE}/pegasus/1000genome/1000genome-chameleon-2ch-100k-001.json",
     "1000genome-chameleon-2ch-100k-001.json"),
    (f"{BASE}/pegasus/montage/montage-chameleon-2mass-005d-001.json",
     "montage-chameleon-2mass-005d-001.json"),
    (f"{BASE}/pegasus/1000genome/1000genome-chameleon-8ch-100k-001.json",
     "1000genome-chameleon-8ch-100k-001.json"),
    (f"{BASE}/pegasus/montage/montage-chameleon-2mass-01d-001.json",
     "montage-chameleon-2mass-01d-001.json"),
    (f"{BASE}/LICENSE", "LICENSE-WfInstances.txt"),
]


def fetch_all(raw_dir: Path = RAW_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for url, name in FILES:
        dest = raw_dir / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"skip   {name} (already present)")
            continue
        print(f"fetch  {name}")
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        print(f"       {len(data):,} bytes")


if __name__ == "__main__":
    fetch_all()
