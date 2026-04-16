import json
import subprocess
import sys
from pathlib import Path

SAMPLE = """\
# Changelog

## [0.3.0] - 2026-04-14
### Added
- Rule-assertion actions (`then.assert`, `bind`).
- `Engine.register_function()`.
### Fixed
- Slot-drop edge case.

## [0.2.0] - 2026-04-10
### Added
- First OWASP Agentic rule pack.
"""


def test_parses_keep_a_changelog(tmp_path: Path) -> None:
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text(SAMPLE, encoding="utf-8")
    out = tmp_path / "changelog.json"
    result = subprocess.run(
        [sys.executable, "scripts/changelog_to_json.py", str(cl), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["version"] == "0.3.0"
    assert data[0]["date"] == "2026-04-14"
    assert "Rule-assertion actions (`then.assert`, `bind`)." in data[0]["added"]
    assert data[0]["fixed"] == ["Slot-drop edge case."]
    assert data[1]["version"] == "0.2.0"


def test_real_changelog_parses(tmp_path: Path) -> None:
    """Guard against format drift between CHANGELOG.md and the parser.

    The parser silently emitted an empty list when headings stopped
    matching — this asserts the committed CHANGELOG produces at least
    one version so that drift fails loud.
    """
    out = tmp_path / "changelog.json"
    result = subprocess.run(
        [sys.executable, "scripts/changelog_to_json.py", "CHANGELOG.md", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data, "parser produced zero versions from the committed CHANGELOG.md"


def test_empty_match_fails_loud(tmp_path: Path) -> None:
    """The parser must refuse to write an empty JSON when the source has
    content but no matching version headings — that combination is the
    exact silent-drop failure mode we're guarding against."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("# Changelog\n\n## 0.1.0 — 2026-01-01\n### Added\n- x\n", encoding="utf-8")
    out = tmp_path / "changelog.json"
    result = subprocess.run(
        [sys.executable, "scripts/changelog_to_json.py", str(cl), str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "zero versions" in result.stderr
