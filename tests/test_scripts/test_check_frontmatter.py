import subprocess
import sys
from pathlib import Path

SCRIPT = Path("scripts/check_frontmatter.py").resolve()


def test_passes_on_valid_page(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\n"
        "title: T\n"
        "summary: S\n"
        "audience: [app-developers]\n"
        "diataxis: how-to\n"
        "status: stable\n"
        "last_verified: 2026-04-15\n"
        "sources:\n  - src/x.py\n"
        "---\n# T\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_fails_on_missing_fields(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text("---\ntitle: T\n---\n# T\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "summary" in result.stderr or "audience" in result.stderr


def test_fails_on_invalid_diataxis(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\n"
        "title: T\n"
        "summary: S\n"
        "audience: [app-developers]\n"
        "diataxis: marketing\n"
        "status: stable\n"
        "last_verified: 2026-04-15\n"
        "---\n# T\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "diataxis" in result.stderr.lower()


def test_explanation_page_without_sources_rejected(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: explanation\nstatus: stable\nlast_verified: 2026-04-15\n---\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "sources" in result.stderr.lower()


def test_explanation_page_with_sources_accepted(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: explanation\nstatus: stable\nlast_verified: 2026-04-15\n"
        "sources:\n  - src/x.py\n---\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_generated_reference_page_exempt_from_sources(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: reference\nstatus: stable\nlast_verified: 2026-04-15\n"
        "generated: true\n---\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(page)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
