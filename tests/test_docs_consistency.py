"""The results/findings blocks in README.md and docs/writeup.md must match the generated files."""
import pytest

from tests.helpers import ROOT

DOCS = [ROOT / "README.md", ROOT / "docs" / "writeup.md", ROOT / "docs" / "HOW_IT_WORKS.md"]
BLOCKS = {"SUMMARY": "results/headline.md", "RESULTS": "results/table.md", "FINDINGS": "results/key_findings.md"}


def block(text: str, tag: str) -> str:
    start, end = f"<!-- {tag}:START -->\n", f"<!-- {tag}:END -->"
    assert start in text and end in text, f"missing {tag} markers"
    return text.split(start, 1)[1].split(end, 1)[0]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize("tag", sorted(BLOCKS))
def test_block_matches_generated_file(doc, tag):
    src = "results/table_short.md" if (doc.name != "writeup.md" and tag == "RESULTS") else BLOCKS[tag]
    generated = (ROOT / src).read_text()
    assert block(doc.read_text(), tag) == generated, (
        f"{doc.name} {tag} block is stale; run: python scripts/make_tables.py")


def test_summary_csv_has_all_runs():
    lines = (ROOT / "results" / "summary.csv").read_text().splitlines()
    assert len(lines) == 181  # header + 2 workflows x 3 scenarios x 10 seeds x 3 planners


def test_plots_exist():
    for name in ("completion_time.png", "failures.png"):
        assert (ROOT / "results" / name).stat().st_size > 10_000
