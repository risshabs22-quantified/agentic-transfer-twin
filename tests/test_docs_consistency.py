from tests.helpers import ROOT

BLOCKS = {"SUMMARY": "results/headline.md", "RESULTS": "results/table_short.md"}


def block(text: str, tag: str) -> str:
    start, end = f"<!-- {tag}:START -->\n", f"<!-- {tag}:END -->"
    assert start in text and end in text, f"missing {tag} markers"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_readme_blocks_match_generated_files():
    readme = (ROOT / "README.md").read_text()
    for tag, src in BLOCKS.items():
        assert block(readme, tag) == (ROOT / src).read_text(), f"README {tag} block is stale; run make_tables.py"


def test_summary_csv_has_all_runs():
    lines = (ROOT / "results" / "summary.csv").read_text().splitlines()
    assert len(lines) == 181


def test_plots_exist():
    for name in ("completion_time.png", "failures.png"):
        assert (ROOT / "results" / name).stat().st_size > 10_000
