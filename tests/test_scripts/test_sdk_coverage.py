import subprocess
import sys
from pathlib import Path


def test_coverage_passes_against_real_generated_tree() -> None:
    # Generate first to ensure tree exists
    subprocess.run(
        [sys.executable, "scripts/generate_python_sdk_docs.py"],
        check=True,
    )
    result = subprocess.run(
        [sys.executable, "scripts/check_sdk_coverage.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"SDK coverage failed:\n{result.stdout}\n{result.stderr}"


def test_coverage_fails_when_page_missing(tmp_path: Path) -> None:
    # Point the checker at an empty directory via env override
    import os

    env = os.environ.copy()
    env["FATHOM_SDK_DOCS_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "scripts/check_sdk_coverage.py"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert result.returncode != 0, "expected failure when docs dir is empty"
    assert "Engine" in result.stdout + result.stderr
