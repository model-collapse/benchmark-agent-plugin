from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "plugin" / "skills"


def test_only_benchmark_skill_exists():
    dirs = {p.name for p in ROOT.iterdir() if p.is_dir()}
    assert dirs == {"benchmark"}


def test_skill_prose_covers_the_verbs():
    text = (ROOT / "benchmark" / "SKILL.md").read_text().lower()
    assert "plan" in text and "analyze" in text and "--detach" in text
