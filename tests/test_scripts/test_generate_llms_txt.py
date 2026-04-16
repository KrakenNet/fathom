import subprocess
import sys
from pathlib import Path

MKDOCS = """\
site_name: Fathom
site_url: https://example.com
docs_dir: docs
nav:
  - Home: index.md
  - Guide:
      - Getting Started: guide/getting-started.md
"""

SCRIPT = Path("scripts/generate_llms_txt.py").resolve()


def test_generates_index_and_full(tmp_path: Path) -> None:
    (tmp_path / "mkdocs.yml").write_text(MKDOCS, encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "guide").mkdir(parents=True)
    (docs / "index.md").write_text(
        "---\ntitle: Home\nsummary: Welcome.\n---\n# Home\nIntro body.\n",
        encoding="utf-8",
    )
    (docs / "guide" / "getting-started.md").write_text(
        "---\ntitle: Getting Started\nsummary: Install and hello world.\n---\n"
        "# Getting Started\nBody.\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    idx = (docs / "llms.txt").read_text(encoding="utf-8")
    full = (docs / "llms-full.txt").read_text(encoding="utf-8")
    assert "# Fathom" in idx
    assert "https://example.com/" in idx
    assert "Getting Started" in idx
    assert "Install and hello world." in idx
    assert "# Home" in full
    assert "# Getting Started" in full
