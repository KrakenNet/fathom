import subprocess
import sys
from pathlib import Path


def test_cli_docs_generator_emits_per_command_pages(tmp_path: Path) -> None:
    out = tmp_path / "cli"
    result = subprocess.run(
        [sys.executable, "scripts/generate_cli_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    expected = {"validate.md", "compile.md", "info.md", "test.md", "bench.md", "repl.md"}
    actual = {p.name for p in out.glob("*.md")}
    assert expected.issubset(actual), f"missing: {expected - actual}"

    validate = (out / "validate.md").read_text(encoding="utf-8")
    assert "fathom validate" in validate.lower()
    assert "Usage" in validate or "usage" in validate
    assert "\x1b[" not in validate, "ANSI escape sequence leaked into docs"
    assert "\r\n" not in validate, "CRLF line endings leaked into docs"
