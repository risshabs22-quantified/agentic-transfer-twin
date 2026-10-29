"""Stage 0 check: the public WfInstances data and its license are present."""
import json
from pathlib import Path

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"
WORKFLOWS = [
    "1000genome-chameleon-2ch-100k-001.json",
    "montage-chameleon-2mass-005d-001.json",
    "1000genome-chameleon-8ch-100k-001.json",
    "montage-chameleon-2mass-01d-001.json",
]


def test_raw_files_present_and_parse():
    for name in WORKFLOWS:
        d = json.loads((RAW / name).read_text())
        assert d["schemaVersion"].startswith("1.")
        assert d["workflow"]["specification"]["tasks"], name


def test_license_present():
    text = (RAW / "LICENSE-WfInstances.txt").read_text()
    assert "LESSER GENERAL PUBLIC LICENSE" in text
