"""Compare two summary.csv files: same rows and columns; integers, booleans and text exactly,
floats within 1e-9 relative (the same rule replay uses). Exits non-zero on any difference.

Used by CI to check that the experiments reproduce on another platform (Linux x86-64), where the
last bit of a float can legitimately differ from macOS arm64 because math libraries differ.

Usage:
    python scripts/check_summary.py results/summary.csv committed_summary.csv
"""
from __future__ import annotations

import csv
import math
import sys


def parse(v: str):
    if v in ("True", "False"):
        return v == "True"
    for conv in (int, float):
        try:
            return conv(v)
        except ValueError:
            pass
    return v


def main(a_path: str, b_path: str) -> int:
    a = list(csv.DictReader(open(a_path)))
    b = list(csv.DictReader(open(b_path)))
    if len(a) != len(b) or (a and list(a[0]) != list(b[0])):
        print(f"different shape: {len(a)} vs {len(b)} rows")
        return 1
    bad = exact = 0
    for i, (ra, rb) in enumerate(zip(a, b)):
        for k in ra:
            x, y = parse(ra[k]), parse(rb[k])
            if ra[k] == rb[k]:
                exact += 1
                continue
            if isinstance(x, float) and isinstance(y, (int, float)) and math.isclose(x, y, rel_tol=1e-9):
                print(f"row {i + 1} {k}: {ra[k]} vs {rb[k]} (equal within 1e-9 relative)")
                continue
            print(f"MISMATCH row {i + 1} {k}: {ra[k]} vs {rb[k]}")
            bad += 1
    total = len(a) * len(a[0]) if a else 0
    print(f"{exact}/{total} values byte-identical; {bad} mismatches beyond tolerance")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
