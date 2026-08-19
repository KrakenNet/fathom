"""README's performance table and ``scripts/benchmark.py`` must agree.

The table used to be a standalone claim -- four numbers with no measurement
anywhere in the repo. Now the script gates on them, which only helps while the
two say the same thing; a number edited in one place and not the other puts CI
back to enforcing something README does not promise.
"""

import importlib.util
import re
import subprocess
import sys
import types
from pathlib import Path

SCRIPT = Path.cwd() / "scripts" / "benchmark.py"
README = Path.cwd() / "README.md"

ROW = re.compile(r"^\|\s*(?P<operation>[^|]+?)\s*\|\s*(?P<target>[^|]+?)\s*\|$")


def _load_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark", str(SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["benchmark"] = mod
    spec.loader.exec_module(mod)
    return mod


def _readme_targets() -> dict[str, str]:
    """The Performance Targets table, as {operation: target cell}."""
    lines = README.read_text(encoding="utf-8").splitlines()
    start = lines.index("## Performance Targets")
    rows: dict[str, str] = {}
    for line in lines[start:]:
        if line.startswith("## ") and not line.startswith("## Performance Targets"):
            break
        match = ROW.match(line)
        if not match:
            continue
        operation = match.group("operation")
        if operation in ("Operation",) or set(operation) <= set("- "):
            continue
        rows[operation] = match.group("target")
    return rows


def test_readme_table_matches_the_benchmark_targets() -> None:
    assert _readme_targets() == {
        name: target.readme_cell for name, target in _load_module().TARGETS.items()
    }


def test_readme_table_is_not_empty() -> None:
    # A rename of the README heading would otherwise make the parity test
    # above pass against two empty dicts.
    assert len(_readme_targets()) == 4


def test_benchmark_enforces_its_targets() -> None:
    """A missed target has to fail the process, not just print a table."""
    mod = _load_module()
    missed = mod.Result("x", 10.0, 10.0, mod.Target(1.0, "us", "< 1µs"))
    met = mod.Result("x", 0.5, 0.9, mod.Target(1.0, "us", "< 1µs"))
    assert not missed.passed
    assert met.passed


def test_benchmark_runs_and_reports() -> None:
    """Smoke test at a tiny iteration count: the harness itself works."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--iterations", "5", "--warmup", "1", "--report-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for operation in _load_module().TARGETS:
        assert operation in result.stdout
