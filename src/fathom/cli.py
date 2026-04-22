"""Fathom CLI — validate, test, and benchmark rule packs.

Provides the ``fathom`` command-line interface built on Typer.
Install via::

    pip install fathom-rules[cli]
"""

from __future__ import annotations

import enum
import importlib.resources
import json
import statistics
import time
from pathlib import Path  # noqa: TC003 - used at runtime by Typer
from typing import Any

import httpx
import yaml

from fathom.compiler import Compiler
from fathom.engine import Engine
from fathom.errors import CompilationError
from fathom.release_sig import ReleaseSigError
from fathom.release_sig import verify_artifact as _verify_artifact
from fathom.yaml_utils import validate_document

try:
    import typer
except ImportError:
    _TYPER_MISSING_MSG = (
        "Typer is required for the Fathom CLI. Install it with: pip install fathom-rules[cli]"
    )
    raise SystemExit(_TYPER_MISSING_MSG)  # noqa: B904

try:
    from rich.console import Console as RichConsole

    _console = RichConsole(stderr=True)
    _HAS_RICH = True
except ImportError:
    _console = None  # type: ignore[assignment]
    _HAS_RICH = False

from fathom import __version__

# Exit codes
_EXIT_SUCCESS = 0
_EXIT_ERROR = 1
_EXIT_NOT_FOUND = 2
_EXIT_MALFORMED = 3

app = typer.Typer(name="fathom", help="Fathom reasoning runtime CLI.")


def _print_error(message: str) -> None:
    """Print an error message using rich if available, otherwise typer.echo."""
    if _HAS_RICH and _console is not None:
        _console.print(f"[bold red]Error:[/bold red] {message}")
    else:
        typer.echo(f"Error: {message}", err=True)


def _print_warning(message: str) -> None:
    """Print a warning message using rich if available, otherwise typer.echo."""
    if _HAS_RICH and _console is not None:
        _console.print(f"[bold yellow]Warning:[/bold yellow] {message}")
    else:
        typer.echo(f"Warning: {message}", err=True)


def _print_success(message: str) -> None:
    """Print a success message using rich if available, otherwise typer.echo."""
    if _HAS_RICH and _console is not None:
        _console.print(f"[bold green]{message}[/bold green]")
    else:
        typer.echo(message)


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(f"fathom {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Fathom reasoning runtime CLI."""


def _collect_yaml_files(path: Path) -> list[Path]:
    """Recursively collect all .yaml and .yml files under *path*."""
    if path.is_file():
        return [path] if path.suffix in (".yaml", ".yml") else []
    return sorted(path.rglob("*.yaml")) + sorted(path.rglob("*.yml"))


def _validate_document(
    data: dict[str, Any],
    file_path: Path,
) -> list[str]:
    """Validate a single YAML document against known Fathom models.

    Delegates to :func:`fathom.yaml_utils.validate_document`.
    """
    return validate_document(data, file_path)


@app.command()
def validate(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a YAML file or directory to validate.",
        exists=True,
    ),
) -> None:
    """Parse YAML files and validate templates, rules, and modules."""
    try:
        yaml_files = _collect_yaml_files(path)
        if not yaml_files:
            _print_error(f"[fathom.cli] validate failed: no YAML files found under {path}")
            raise typer.Exit(code=_EXIT_NOT_FOUND)

        all_errors: list[str] = []
        files_checked = 0

        for yaml_file in yaml_files:
            try:
                content = yaml_file.read_text(encoding="utf-8")
            except OSError as exc:
                all_errors.append(f"{yaml_file}: read error: {exc}")
                continue

            try:
                docs = list(yaml.safe_load_all(content))
            except yaml.YAMLError as exc:
                all_errors.append(f"{yaml_file}: YAML parse error: {exc}")
                continue

            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                doc_errors = _validate_document(doc, yaml_file)
                all_errors.extend(doc_errors)

            files_checked += 1

        if all_errors:
            _print_error(f"[fathom.cli] validate failed: {len(all_errors)} error(s) found")
            for error in all_errors:
                typer.echo(f"  {error}", err=True)
            raise typer.Exit(code=_EXIT_ERROR)

        _print_success(f"Validation passed: {files_checked} file(s) checked, 0 errors.")
    except typer.Exit:
        raise
    except OSError as exc:
        _print_error(f"[fathom.cli] validate failed: file system error: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
    except Exception as exc:
        _print_error(f"[fathom.cli] validate failed: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc


class _CompileFormat(enum.StrEnum):
    """Output format for the compile command."""

    raw = "raw"
    pretty = "pretty"


def _compile_yaml_file(
    file_path: Path,
    compiler: Compiler,
) -> list[str]:
    """Compile a single YAML file into CLIPS construct strings.

    Auto-detects the document type (templates, modules, rules, functions)
    from top-level YAML keys and compiles accordingly.

    Returns:
        List of CLIPS construct strings.
    """
    constructs: list[str] = []

    content = file_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        return constructs

    if "templates" in data:
        for tmpl_defn in compiler.parse_template_file(file_path):
            constructs.append(compiler.compile_template(tmpl_defn))
    elif "modules" in data:
        mod_definitions, focus_order = compiler.parse_module_file(file_path)
        for mod_defn in mod_definitions:
            constructs.append(compiler.compile_module(mod_defn))
        if focus_order:
            constructs.append(compiler.compile_focus_stack(focus_order))
    elif "functions" in data:
        for func_defn in compiler.parse_function_file(file_path):
            result = compiler.compile_function(func_defn)
            if result:
                constructs.append(result)
    elif "rules" in data or "ruleset" in data:
        ruleset = compiler.parse_rule_file(file_path)
        for rule_defn in ruleset.rules:
            constructs.append(
                compiler.compile_rule(rule_defn, ruleset.module),
            )

    return constructs


def _pretty_format(clips_str: str) -> str:
    """Add newlines after opening parens at depth 1 for readability."""
    lines: list[str] = []
    depth = 0
    i = 0
    current_line = ""
    while i < len(clips_str):
        ch = clips_str[i]
        if ch == "(":
            depth += 1
            current_line += ch
        elif ch == ")":
            depth -= 1
            current_line += ch
            if depth == 0:
                lines.append(current_line)
                current_line = ""
        elif ch == "\n":
            current_line += ch
        else:
            current_line += ch
        i += 1
    if current_line.strip():
        lines.append(current_line)
    return "\n".join(lines)


@app.command()
def compile(  # noqa: A001
    path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a YAML file or directory to compile.",
        exists=True,
    ),
    fmt: _CompileFormat = typer.Option(  # noqa: B008
        _CompileFormat.raw,
        "--format",
        "-f",
        help="Output format: raw (valid CLIPS) or pretty (human-readable).",
    ),
) -> None:
    """Compile YAML definitions into CLIPS constructs."""
    try:
        yaml_files = _collect_yaml_files(path)
        if not yaml_files:
            _print_error(f"[fathom.cli] compile failed: no YAML files found under {path}")
            raise typer.Exit(code=_EXIT_NOT_FOUND)

        compiler = Compiler()
        all_constructs: list[str] = []

        for yaml_file in yaml_files:
            try:
                constructs = _compile_yaml_file(yaml_file, compiler)
                all_constructs.extend(constructs)
            except CompilationError as exc:
                _print_error(f"[fathom.cli] compile failed: {exc}")
                raise typer.Exit(code=_EXIT_ERROR) from exc

        if not all_constructs:
            _print_warning("[fathom.cli] compile failed: no compilable constructs found")
            raise typer.Exit(code=_EXIT_ERROR)

        output = "\n".join(all_constructs)
        if fmt == _CompileFormat.pretty:
            output = _pretty_format(output)
        typer.echo(output)
    except typer.Exit:
        raise
    except OSError as exc:
        _print_error(f"[fathom.cli] compile failed: file system error: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
    except Exception as exc:
        _print_error(f"[fathom.cli] compile failed: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc


@app.command()
def info(
    path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a rule pack directory to inspect.",
        exists=True,
    ),
) -> None:
    """Load a rule pack and display loaded constructs."""
    try:
        engine = Engine.from_rules(str(path))
    except CompilationError as exc:
        msg = f"compilation error loading rules from {path}: {exc}"
        _print_error(f"[fathom.cli] info failed: {msg}")
        raise typer.Exit(code=_EXIT_ERROR) from exc
    except OSError as exc:
        _print_error(f"[fathom.cli] info failed: cannot read rule pack at {path}: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
    except Exception as exc:
        _print_error(f"[fathom.cli] info failed: error loading rules from {path}: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc

    # Templates
    templates = engine.template_registry
    typer.echo(f"Templates ({len(templates)}):")
    for name, tmpl_def in sorted(templates.items()):
        slot_info = [f"{s.name}:{s.type.value}" for s in tmpl_def.slots]
        typer.echo(f"  {name}: slots=[{', '.join(slot_info)}]")

    # Modules
    modules = engine.module_registry
    typer.echo(f"\nModules ({len(modules)}):")
    for name, mod_def in sorted(modules.items()):
        typer.echo(f"  {name}: priority={mod_def.priority}")
    if engine.focus_order:
        typer.echo(f"  Focus order: {' -> '.join(engine.focus_order)}")

    # Rules (from registry)
    typer.echo(f"\nRules ({len(engine.rule_registry)}):")
    for name, rule_def in sorted(engine.rule_registry.items()):
        typer.echo(f"  {name}  salience={rule_def.salience}")

    # Functions (keep env access — no public API for CLIPS function enumeration)
    clips_functions = [fn for fn in engine._env.functions() if not str(fn.name).startswith("(")]
    typer.echo(f"\nFunctions ({len(clips_functions)}):")
    for fn in clips_functions:
        typer.echo(f"  {fn.name}")


@app.command()
def test(
    rules_path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a rule pack directory.",
        exists=True,
    ),
    test_path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a YAML test file or directory of test files.",
        exists=True,
    ),
) -> None:
    """Run YAML test cases against a rule pack."""
    try:
        # Load engine from rules path
        try:
            engine = Engine.from_rules(str(rules_path))
        except CompilationError as exc:
            msg = f"compilation error loading rules from {rules_path}: {exc}"
            _print_error(f"[fathom.cli] test failed: {msg}")
            raise typer.Exit(code=_EXIT_ERROR) from exc
        except OSError as exc:
            _print_error(f"[fathom.cli] test failed: cannot read rule pack at {rules_path}: {exc}")
            raise typer.Exit(code=_EXIT_NOT_FOUND) from exc

        # Collect test files
        test_files = _collect_yaml_files(test_path)
        if not test_files:
            _print_error(f"[fathom.cli] test failed: no YAML test files found at {test_path}")
            raise typer.Exit(code=_EXIT_NOT_FOUND)

        passed = 0
        failed = 0
        failures: list[str] = []

        for test_file in test_files:
            try:
                content = test_file.read_text(encoding="utf-8")
            except OSError as exc:
                _print_error(f"[fathom.cli] test failed: error reading {test_file}: {exc}")
                failed += 1
                continue

            data = yaml.safe_load(content)
            if not isinstance(data, list):
                _print_warning(f"{test_file} is not a list of test cases, skipping.")
                continue

            for case in data:
                case_name = case.get("name", "<unnamed>")
                facts_list: list[dict[str, Any]] = case.get("facts", [])
                expected = case.get("expected_decision")

                # Reset engine state for each test case
                engine.reset()

                # Assert facts
                for fact_spec in facts_list:
                    template = fact_spec.get("template", "")
                    fact_data: dict[str, Any] = fact_spec.get("data", {})
                    try:
                        engine.assert_fact(template, fact_data)
                    except Exception as exc:
                        _print_error(f"  FAIL  {case_name} — fact assertion error: {exc}")
                        failed += 1
                        failures.append(f"{case_name}: fact assertion error")
                        break
                else:
                    # Evaluate
                    result = engine.evaluate()
                    if result.decision == expected:
                        typer.echo(f"  PASS  {case_name}")
                        passed += 1
                    else:
                        msg = (
                            f"  FAIL  {case_name} — expected '{expected}', got '{result.decision}'"
                        )
                        typer.echo(msg)
                        failed += 1
                        failures.append(
                            f"{case_name}: expected '{expected}', got '{result.decision}'"
                        )

        # Summary
        total = passed + failed
        if failures:
            _print_error(f"{total} test(s): {passed} passed, {failed} failed")
            raise typer.Exit(code=_EXIT_ERROR)
        _print_success(f"{total} test(s): {passed} passed, {failed} failed")
    except typer.Exit:
        raise
    except Exception as exc:
        _print_error(f"[fathom.cli] test failed: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc


@app.command()
def bench(
    rules_path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a rule pack directory.",
        exists=True,
    ),
    iterations: int = typer.Option(  # noqa: B008
        1000,
        "--iterations",
        "-n",
        help="Number of evaluation iterations.",
    ),
    warmup: int = typer.Option(  # noqa: B008
        100,
        "--warmup",
        "-w",
        help="Number of warmup iterations (excluded from results).",
    ),
) -> None:
    """Benchmark rule evaluation latency."""
    try:
        # Load engine from rules path
        try:
            engine = Engine.from_rules(str(rules_path))
        except CompilationError as exc:
            msg = f"compilation error loading rules from {rules_path}: {exc}"
            _print_error(f"[fathom.cli] bench failed: {msg}")
            raise typer.Exit(code=_EXIT_ERROR) from exc
        except OSError as exc:
            msg = f"cannot read rule pack at {rules_path}: {exc}"
            _print_error(f"[fathom.cli] bench failed: {msg}")
            raise typer.Exit(code=_EXIT_NOT_FOUND) from exc

        # Warmup
        typer.echo(f"Warming up ({warmup} iterations)...")
        for _ in range(warmup):
            engine.reset()
            engine.evaluate()

        # Benchmark
        typer.echo(f"Benchmarking ({iterations} iterations)...")
        timings_us: list[float] = []
        for _ in range(iterations):
            engine.reset()
            start = time.perf_counter()
            engine.evaluate()
            elapsed = time.perf_counter() - start
            timings_us.append(elapsed * 1_000_000)

        # Calculate percentiles
        timings_us.sort()
        p50 = statistics.median(timings_us)
        p95_idx = int(len(timings_us) * 0.95) - 1
        p99_idx = int(len(timings_us) * 0.99) - 1
        p95 = timings_us[max(0, p95_idx)]
        p99 = timings_us[max(0, p99_idx)]
        mean = statistics.mean(timings_us)

        typer.echo(f"\nResults ({iterations} iterations):")
        typer.echo(f"  p50:  {p50:>10.1f} \u00b5s")
        typer.echo(f"  p95:  {p95:>10.1f} \u00b5s")
        typer.echo(f"  p99:  {p99:>10.1f} \u00b5s")
        typer.echo(f"  mean: {mean:>10.1f} \u00b5s")
    except typer.Exit:
        raise
    except Exception as exc:
        _print_error(f"[fathom.cli] bench failed: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc


@app.command("verify-artifact")
def verify_artifact(
    artifact: Path = typer.Argument(  # noqa: B008
        ...,
        help="Artifact to verify.",
    ),
    sig: Path | None = typer.Option(  # noqa: B008
        None,
        "--sig",
        help="Sig path (default: <path>.minisig).",
    ),
    pubkey: Path | None = typer.Option(  # noqa: B008
        None,
        "--pubkey",
        help="Pubkey (default: embedded).",
    ),
) -> None:
    """Verify an artifact's detached minisign signature against a pubkey."""
    sig_path = sig if sig is not None else Path(str(artifact) + ".minisig")
    if pubkey is not None:
        pubkey_path = pubkey
    else:
        pubkey_path = Path(
            str(importlib.resources.files("fathom._data") / "release_pubkey.minisign")
        )

    if not artifact.exists():
        _print_error(f"[fathom.cli] verify-artifact failed: artifact not found: {artifact}")
        raise typer.Exit(code=_EXIT_NOT_FOUND)
    if not sig_path.exists():
        _print_error(f"[fathom.cli] verify-artifact failed: signature not found: {sig_path}")
        raise typer.Exit(code=_EXIT_NOT_FOUND)
    if not pubkey_path.exists():
        _print_error(f"[fathom.cli] verify-artifact failed: pubkey not found: {pubkey_path}")
        raise typer.Exit(code=_EXIT_NOT_FOUND)

    try:
        _verify_artifact(artifact, sig_path, pubkey_path)
    except FileNotFoundError as exc:
        _print_error(f"[fathom.cli] verify-artifact failed: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
    except ReleaseSigError as exc:
        msg = str(exc)
        malformed_markers = (
            "malformed",
            "base64 decode",
            "unexpected payload length",
            "unsupported sig algorithm",
            "key id mismatch",
        )
        if any(marker in msg for marker in malformed_markers):
            _print_error(f"[fathom.cli] verify-artifact failed: {msg}")
            raise typer.Exit(code=_EXIT_MALFORMED) from exc
        _print_error(f"[fathom.cli] verify-artifact failed: {msg}")
        raise typer.Exit(code=_EXIT_ERROR) from exc
    except Exception as exc:
        _print_error(f"[fathom.cli] verify-artifact failed: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc

    typer.echo("ok: signature valid")


@app.command()
def status(
    server: str = typer.Option(  # noqa: B008
        ...,
        "--server",
        help="Fathom server base URL (e.g., http://127.0.0.1:8080).",
    ),
    token: str | None = typer.Option(  # noqa: B008
        None,
        "--token",
        envvar="FATHOM_TOKEN",
        help="Optional bearer token (defaults to FATHOM_TOKEN env var).",
    ),
) -> None:
    """Query a Fathom server's GET /v1/status endpoint."""
    url = f"{server.rstrip('/')}/v1/status"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.get(url, headers=headers, timeout=5.0)
    except httpx.HTTPError as exc:
        _print_error(f"[fathom.cli] status failed: connection error: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc

    if response.status_code != 200:
        _print_error(
            f"[fathom.cli] status failed: HTTP {response.status_code}: {response.text.strip()}"
        )
        raise typer.Exit(code=_EXIT_ERROR)

    try:
        data = response.json()
    except ValueError as exc:
        _print_error(f"[fathom.cli] status failed: invalid JSON response: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc

    typer.echo(f"ruleset_hash: {data.get('ruleset_hash')}")
    typer.echo(f"version:      {data.get('version')}")
    typer.echo(f"loaded_at:    {data.get('loaded_at')}")


def _repl_help() -> None:
    """Print REPL help text."""
    typer.echo("Commands:")
    typer.echo("  assert <template> <json_data>  — Assert a fact")
    typer.echo("  evaluate                       — Run evaluation")
    typer.echo("  query <template>               — Query facts by template")
    typer.echo("  retract <template>             — Retract facts by template")
    typer.echo("  facts                          — List all facts")
    typer.echo("  reset                          — Reset engine state")
    typer.echo("  help                           — Show this help")
    typer.echo("  quit / exit                    — Exit REPL")


def _repl_loop(engine: Engine) -> None:
    """Run the interactive REPL loop."""
    typer.echo("Fathom REPL — type 'help' for commands, 'quit' to exit.")
    while True:
        try:
            line = input("fathom> ").strip()
        except (EOFError, KeyboardInterrupt):
            typer.echo("")
            break

        if not line:
            continue

        parts = line.split(None, 2)
        cmd = parts[0].lower()

        if cmd in ("quit", "exit"):
            break
        elif cmd == "help":
            _repl_help()
        elif cmd == "reset":
            engine.reset()
            typer.echo("Engine state reset.")
        elif cmd == "facts":
            facts = list(engine._env.facts())
            if not facts:
                typer.echo("No facts in working memory.")
            else:
                for fact in facts:
                    typer.echo(f"  {fact}")
        elif cmd == "evaluate":
            result = engine.evaluate()
            typer.echo(f"  decision: {result.decision}")
            typer.echo(f"  reason: {result.reason}")
            if result.rule_trace:
                typer.echo(f"  rule_trace: {result.rule_trace}")
        elif cmd == "assert":
            if len(parts) < 3:
                typer.echo("Usage: assert <template> <json_data>")
                continue
            template = parts[1]
            try:
                data: dict[str, Any] = json.loads(parts[2])
            except json.JSONDecodeError as exc:
                typer.echo(f"Invalid JSON: {exc}")
                continue
            try:
                engine.assert_fact(template, data)
                typer.echo(f"Asserted {template} fact.")
            except Exception as exc:
                typer.echo(f"Error: {exc}")
        elif cmd == "query":
            if len(parts) < 2:
                typer.echo("Usage: query <template>")
                continue
            template = parts[1]
            try:
                facts = engine.query(template)
            except Exception as exc:
                typer.echo(f"Error: {exc}")
                continue
            if not facts:
                typer.echo(f"No facts matching '{template}'.")
            else:
                for row in facts:
                    typer.echo(f"  {template}: {row}")
        elif cmd == "retract":
            if len(parts) < 2:
                typer.echo("Usage: retract <template>")
                continue
            template = parts[1]
            try:
                count = engine.retract(template)
            except Exception as exc:
                typer.echo(f"Error: {exc}")
                continue
            typer.echo(f"Retracted {count} fact(s) matching '{template}'.")
        else:
            typer.echo(f"Unknown command: {cmd}. Type 'help' for commands.")


@app.command()
def repl(
    rules: Path = typer.Option(  # noqa: B008
        None,
        "--rules",
        "-r",
        help="Path to a rule pack directory to load.",
        exists=True,
    ),
) -> None:
    """Start an interactive REPL session."""
    try:
        if rules:
            try:
                engine = Engine.from_rules(str(rules))
                _print_success(f"Loaded rules from {rules}")
            except CompilationError as exc:
                msg = f"compilation error loading rules from {rules}: {exc}"
                _print_error(f"[fathom.cli] repl failed: {msg}")
                raise typer.Exit(code=_EXIT_ERROR) from exc
            except OSError as exc:
                _print_error(f"[fathom.cli] repl failed: cannot read rule pack at {rules}: {exc}")
                raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
        else:
            engine = Engine()

        _repl_loop(engine)
    except typer.Exit:
        raise
    except Exception as exc:
        _print_error(f"[fathom.cli] repl failed: {exc}")
        raise typer.Exit(code=_EXIT_ERROR) from exc


if __name__ == "__main__":
    app()
