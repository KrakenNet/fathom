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
from typing import TYPE_CHECKING, Any

import httpx
import yaml

from fathom.compiler import Compiler
from fathom.engine import _DECISION_SEQ_GLOBAL, _DECISION_TEMPLATE, Engine
from fathom.errors import CompilationError, ValidationError
from fathom.rego import ConversionResult, convert_ast, export_engine, parse_rego
from fathom.release_sig import ReleaseSigError
from fathom.release_sig import verify_artifact as _verify_artifact
from fathom.yaml_utils import validate_document

if TYPE_CHECKING:
    from fathom.models import HierarchyDefinition, TemplateDefinition

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


def _compilation_error_text(exc: CompilationError) -> str:
    """Render a compilation error including its detail line when present.

    The compiler puts remediation hints (e.g. the list of supported condition
    operators) in ``CompilationError.detail``; without this the CLI drops them.
    """
    if exc.detail:
        return f"{exc}\n  {exc.detail}"
    return str(exc)


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


def _collect_template_registry(
    yaml_files: list[Path],
    compiler: Compiler,
) -> dict[str, TemplateDefinition]:
    """Build a template registry from every template file in *yaml_files*.

    ``compile_rule`` emits literals according to the declared slot type — a
    STRING slot gets a quoted CLIPS string, a SYMBOL slot does not. Without
    the registry it falls back to the untyped form, so ``fathom compile``
    printed ``(agent (id alice@example.com))`` for a ruleset where the real
    Engine builds ``(agent (id "alice@example.com"))``. The unquoted form is
    the one CLIPS rejects with ``[CSTRNCHK1]``, i.e. the command was showing
    CLIPS that the engine would never build and that does not even load.

    Parse failures are ignored here: this pass only gathers type context, and
    the real compile pass below reports the error properly.
    """
    registry: dict[str, TemplateDefinition] = {}
    for yaml_file in yaml_files:
        try:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict) or "templates" not in data:
            continue
        try:
            for tmpl_defn in compiler.parse_template_file(yaml_file):
                registry[tmpl_defn.name] = tmpl_defn
        except CompilationError:
            continue
    return registry


def _sibling_template_files(path: Path) -> list[Path]:
    """Template files belonging to the ruleset *path* lives in.

    ``fathom compile ruleset/rules/r.yaml`` names one file, but the slot
    types it needs live in ``ruleset/templates/``. Fathom's on-disk layout
    puts them there (that is what ``Engine.from_rules`` walks), so pick them
    up rather than silently compiling without type context.
    """
    if not path.is_file() or path.parent.name != "rules":
        return []
    templates_dir = path.parent.parent / "templates"
    if not templates_dir.is_dir():
        return []
    return sorted(templates_dir.rglob("*.yaml")) + sorted(templates_dir.rglob("*.yml"))


def _compile_yaml_file(
    file_path: Path,
    compiler: Compiler,
    templates: dict[str, TemplateDefinition] | None = None,
) -> dict[str, list[str]]:
    """Compile a single YAML file into CLIPS construct strings, by kind.

    Auto-detects the document type (templates, modules, rules, functions)
    from top-level YAML keys and compiles accordingly.

    Keyed by kind rather than returned flat because CLIPS resolves
    references at build time: a defrule naming a deftemplate that has not
    been built yet is an error, and file order is not build order. The
    caller reassembles the whole run in dependency order.

    Args:
        file_path: YAML file to compile.
        compiler: Compiler instance.
        templates: Slot-type context, so emitted literals match what
            :meth:`Engine.from_rules` builds for the same ruleset.

    Returns:
        Mapping of kind (``templates``/``modules``/``focus``/``functions``/
        ``rules``) to the CLIPS construct strings compiled from this file.
    """
    constructs: dict[str, list[str]] = {}

    content = file_path.read_text(encoding="utf-8")
    data = yaml.safe_load(content)
    if not isinstance(data, dict):
        return constructs

    if "templates" in data:
        constructs["templates"] = [
            compiler.compile_template(tmpl_defn)
            for tmpl_defn in compiler.parse_template_file(file_path)
        ]
    elif "modules" in data:
        mod_definitions, focus_order = compiler.parse_module_file(file_path)
        constructs["modules"] = [compiler.compile_module(m) for m in mod_definitions]
        if focus_order:
            constructs["focus"] = [compiler.compile_focus_stack(focus_order)]
    elif "functions" in data:
        # A classification function is only compilable with the hierarchy it
        # references in hand -- `compile_function` raises without it. The
        # engine resolves it off disk in `load_functions`; this did not, so
        # `fathom compile` exited 1 on every pack with a classification
        # function, including the shipped examples/03-classification-blp that
        # `fathom validate` and `fathom info` both accept.
        definitions = compiler.parse_function_file(file_path)
        hierarchies: dict[str, HierarchyDefinition] = {}
        for defn in definitions:
            if defn.hierarchy_ref:
                name = defn.hierarchy_ref.rsplit(".", 1)[0]
                if name not in hierarchies:
                    hierarchies[name] = Engine._resolve_hierarchy(defn.hierarchy_ref, file_path)
        compiled = [compiler.compile_function(f, hierarchies or None) for f in definitions]
        constructs["functions"] = [c for c in compiled if c]
    elif "rules" in data or "ruleset" in data:
        ruleset = compiler.parse_rule_file(file_path)
        constructs["rules"] = [
            compiler.compile_rule(rule_defn, ruleset.module, templates)
            for rule_defn in ruleset.rules
        ]

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


def _clips_loads(output: str) -> bool:
    """Whether *output* builds cleanly, in an env prepared as the Engine does.

    ``--format raw`` promises CLIPS that loads, so this checks rather than
    asserts. The usual cause of a failure is a compile unit that is not
    self-contained: ``cmmc`` names templates and a module the
    ``nist-800-53`` pack it depends on owns, so it compiled to constructs
    referencing things nothing in the unit defines and the command exited 0
    over CLIPS that raises on line 1.

    Only a whole ruleset directory is held to this. A single YAML file is a
    fragment by construction -- a rules file names the module and templates
    its siblings define, which this command reads for slot types and does not
    emit -- so its output is not expected to stand alone.

    CLIPS writes its own diagnostics through a C-level router, so they reach
    the terminal on their own and are more use than anything reformatted
    here; the caller only adds the verdict.
    """
    import tempfile

    import clips

    env = clips.Environment()
    Engine()._register_external_functions(env=env)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "compile-check.clp"
        path.write_text(output, encoding="utf-8")
        try:
            env.load(str(path))
        except Exception:  # noqa: BLE001 - any CLIPS complaint means "no"
            return False
    return True


def _assemble(by_kind: dict[str, list[str]]) -> list[str]:
    """Order one compile run so the emitted CLIPS actually loads.

    ``fathom compile`` printed constructs in file order, which is the order
    ``sorted()`` walks a pack directory -- ``modules/`` then ``rules/`` then
    ``templates/``. CLIPS resolves references when a construct is built, so
    that stream failed on its first defrule and, before that, on its first
    defmodule: ``(import MAIN ?ALL)`` is an error until MAIN exports, and
    every rule's RHS names ``__fathom_decision`` and
    ``?*fathom-decision-seq*``, which only the engine was building.

    So the output opens with the same preamble :class:`Engine` builds and
    then follows the engine's own build order. It still needs Fathom's
    external functions (``fathom-matches`` and friends) registered on the
    environment, exactly as the engine registers them before compiling any
    rule -- those are Python callbacks and cannot be expressed in CLIPS text.

    The declared focus order is emitted as a trailing comment: ``(focus ...)``
    is a command the evaluator issues per evaluation, not a construct, and a
    loader rejects it.
    """
    ordered = [_DECISION_SEQ_GLOBAL, _DECISION_TEMPLATE]
    if by_kind.get("modules"):
        ordered.append("(defmodule MAIN (export ?ALL))")
    for kind in ("templates", "modules", "functions", "rules"):
        ordered.extend(by_kind.get(kind, []))
    ordered.extend(
        f"; focus order (issued per evaluation, not a construct): {f}"
        for f in by_kind.get("focus", [])
    )
    return ordered


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
        by_kind: dict[str, list[str]] = {}
        # Two passes: gather slot types first so rule literals are emitted
        # exactly as Engine.from_rules would emit them for this ruleset.
        templates = _collect_template_registry(
            yaml_files + _sibling_template_files(path), compiler
        )

        for yaml_file in yaml_files:
            try:
                for kind, constructs in _compile_yaml_file(yaml_file, compiler, templates).items():
                    by_kind.setdefault(kind, []).extend(constructs)
            except CompilationError as exc:
                _print_error(f"[fathom.cli] compile failed: {_compilation_error_text(exc)}")
                raise typer.Exit(code=_EXIT_ERROR) from exc

        if not any(by_kind.values()):
            _print_warning("[fathom.cli] compile failed: no compilable constructs found")
            raise typer.Exit(code=_EXIT_ERROR)

        output = "\n".join(_assemble(by_kind))
        if path.is_dir() and not _clips_loads(output):
            _print_error(
                "[fathom.cli] compile failed: the compiled constructs do not load "
                "(CLIPS diagnostics above). The unit is not self-contained: either "
                "it depends on another pack — compile the two directories together — "
                "or it is part of one, and the whole ruleset directory is the unit."
            )
            raise typer.Exit(code=_EXIT_ERROR)
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
        msg = f"compilation error loading rules from {path}: {_compilation_error_text(exc)}"
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

    # Functions (keep env access — no public API for CLIPS function enumeration).
    #
    # CLIPS enumerates deffunctions in the *current* module, and building a
    # pack's last defmodule leaves that module current -- so this reported
    # "Functions (0)" for every pack, hiding the twelve fathom-* operators the
    # engine registers into MAIN. Switch to MAIN to list them, then restore
    # the module the engine left focused.
    env = engine._env
    previous_module = env.current_module
    env.current_module = env.find_module("MAIN")
    try:
        clips_functions = [fn for fn in env.functions() if not str(fn.name).startswith("(")]
    finally:
        env.current_module = previous_module
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
            msg = (
                f"compilation error loading rules from {rules_path}: "
                f"{_compilation_error_text(exc)}"
            )
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
                failures.append(f"{test_file}: read error")
                continue

            data = yaml.safe_load(content)
            if not isinstance(data, list):
                _print_error(f"[fathom.cli] test failed: {test_file} is not a list of test cases")
                failed += 1
                failures.append(f"{test_file}: not a list of test cases")
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
        if total == 0:
            _print_error(f"[fathom.cli] test failed: no test cases ran from {test_path}")
            raise typer.Exit(code=_EXIT_ERROR)
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
            msg = (
                f"compilation error loading rules from {rules_path}: "
                f"{_compilation_error_text(exc)}"
            )
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


@app.command("verify-chain")
def verify_chain_cmd(
    log_path: Path = typer.Argument(  # noqa: B008
        ...,
        help="Chained attestation log (JSONL) to verify.",
    ),
    pubkey: Path = typer.Option(  # noqa: B008
        ...,
        "--pubkey",
        help="Ed25519 public key PEM (exported beside the log as <log>.pub.pem).",
    ),
    expected_head: str | None = typer.Option(
        None,
        "--expected-head",
        help="Out-of-band mirrored line hash; fails if absent (tail truncation).",
    ),
    anchor_token: str | None = typer.Option(
        None,
        "--anchor-token",
        help="Checkpoint JWS token; its pinned head must appear in the log.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit the verification result as JSON.",
    ),
) -> None:
    """Offline-verify a hash-chained attestation log (chain + signatures)."""
    from dataclasses import asdict

    from fathom.chained_log import verify_chain
    from fathom.errors import AttestationError

    if not log_path.exists():
        _print_error(f"[fathom.cli] verify-chain failed: log not found: {log_path}")
        raise typer.Exit(code=_EXIT_NOT_FOUND)
    if not pubkey.exists():
        _print_error(f"[fathom.cli] verify-chain failed: pubkey not found: {pubkey}")
        raise typer.Exit(code=_EXIT_NOT_FOUND)

    try:
        result = verify_chain(
            log_path, pubkey, expected_head=expected_head, anchor_token=anchor_token
        )
    except AttestationError as exc:
        _print_error(f"[fathom.cli] verify-chain failed: {exc}")
        raise typer.Exit(code=_EXIT_MALFORMED) from exc
    except ValueError as exc:
        # cryptography raises ValueError on a PEM it cannot parse, which
        # escaped as a traceback and exit 1. The docs promise 2 when the key
        # file cannot be read, and a file that is not a key cannot be read as
        # one.
        _print_error(f"[fathom.cli] verify-chain failed: cannot read public key {pubkey}: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc

    if json_output:
        typer.echo(json.dumps(asdict(result), indent=2))
    elif result.ok:
        anchored = " (anchor ok)" if result.anchor_ok else ""
        _print_success(
            f"ok: chain valid — {result.count} records, head {result.head_sha256}{anchored}"
        )
    else:
        _print_error(f"[fathom.cli] verify-chain failed: {result.error}")

    if not result.ok:
        raise typer.Exit(code=_EXIT_ERROR)


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
    typer.echo("")
    typer.echo("Example:")
    typer.echo('  assert request {"action": "read", "user": "alice"}')


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
            facts = engine.all_facts()
            if not facts:
                typer.echo("No facts in working memory.")
            else:
                for fact in facts:
                    template = fact["__template__"]
                    slots = {k: v for k, v in fact.items() if k != "__template__"}
                    typer.echo(f"  ({template} {slots})")
        elif cmd == "evaluate":
            result = engine.evaluate()
            typer.echo(f"  decision: {result.decision}")
            typer.echo(f"  reason: {result.reason}")
            if result.rule_trace:
                typer.echo(f"  rule_trace: {result.rule_trace}")
        elif cmd == "assert":
            if len(parts) < 3:
                typer.echo("Usage: assert <template> <json_data>")
                typer.echo('  e.g. assert request {"action": "read", "user": "alice"}')
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
    rules: Path | None = typer.Option(  # noqa: B008
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
                msg = (
                    f"compilation error loading rules from {rules}: {_compilation_error_text(exc)}"
                )
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


# ===========================================================================
# convert -- move a policy between Fathom and another engine
# ===========================================================================

convert_app = typer.Typer(
    name="convert",
    help="Convert policies between Fathom YAML and other engines.",
    no_args_is_help=True,
)
app.add_typer(convert_app)


def _write_pack(out_dir: Path, result: ConversionResult) -> list[Path]:
    """Write a ConversionResult as a loadable Fathom pack directory."""
    written: list[Path] = []
    payloads = {
        "templates": {"templates": result.templates},
        "modules": {"modules": result.modules, "focus_order": [result.module]},
        "rules": {
            "module": result.module,
            "ruleset": result.module,
            "rules": result.rules,
        },
    }
    for kind, payload in payloads.items():
        target_dir = out_dir / kind
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{result.module}.yaml"
        target.write_text(
            yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        written.append(target)
    return written


def _report_conversion(result: ConversionResult) -> None:
    """Print notes and skips to stderr, loudly enough that they are not missed."""
    for note in result.notes:
        _print_warning(f"[fathom.cli] convert note: {note}")
    for skipped in result.skipped:
        _print_warning(f"[fathom.cli] convert skipped: {skipped}")


def _report_export(result: Any) -> None:
    """Report an export, grouping skips by reason.

    A ruleset built on cross-fact joins refuses every rule for the same
    reason; printing that reason 144 times buries the two rules refused for a
    different one.
    """
    for note in result.notes:
        _print_warning(f"[fathom.cli] export note: {note}")
    grouped: dict[str, list[str]] = {}
    for skipped in result.skipped:
        grouped.setdefault(skipped.reason, []).append(skipped.rule)
    for reason, names in grouped.items():
        shown = ", ".join(names[:3]) + (f", +{len(names) - 3} more" if len(names) > 3 else "")
        _print_warning(f"[fathom.cli] export skipped {len(names)} rule(s) ({shown}): {reason}")


@convert_app.command("to-rego")
def convert_to_rego(
    ruleset: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a Fathom ruleset directory.",
        exists=True,
        file_okay=False,
    ),
    out_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--out",
        "-o",
        help="File to write the Rego to. Without it, the policy is printed.",
    ),
    package: str | None = typer.Option(
        None,
        "--package",
        "-p",
        help="Rego package name. Defaults to the module the rules declare.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit nonzero if any rule was skipped, not only if none exported.",
    ),
) -> None:
    """Export the stateless subset of a Fathom ruleset as Rego.

    Only rules that match one fact against literals have a Rego form. Rules
    that join across facts, assert new facts, or use a temporal or
    classification operator are reported and left out -- those are the parts
    of Fathom that Rego has no counterpart for, and writing them out as
    something Rego accepts would mean writing a different policy.
    """
    try:
        engine = Engine.from_rules(str(ruleset))
    except CompilationError as exc:
        _print_error(f"[fathom.cli] export failed: {_compilation_error_text(exc)}")
        raise typer.Exit(code=_EXIT_MALFORMED) from exc
    except (OSError, ValidationError) as exc:
        _print_error(f"[fathom.cli] export failed: cannot load {ruleset}: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc

    result = export_engine(engine, package=package)
    _report_export(result)

    if not result.exported_anything:
        _print_error(
            "[fathom.cli] export failed: no rule in this ruleset is in the exportable subset"
        )
        raise typer.Exit(code=_EXIT_ERROR)

    if out_file is None:
        typer.echo(result.source)
    else:
        try:
            out_file.write_text(result.source, encoding="utf-8")
        except OSError as exc:
            _print_error(f"[fathom.cli] export failed: cannot write to {out_file}: {exc}")
            raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
        _print_success(f"wrote {out_file}")

    _print_success(
        f"exported {result.rule_count} rule(s) to package {result.package}; "
        f"{len(result.skipped)} rule(s) skipped"
    )
    if strict and result.skipped:
        raise typer.Exit(code=_EXIT_ERROR)


@convert_app.command("rego")
def convert_rego(
    policy: Path = typer.Argument(  # noqa: B008
        ...,
        help="Path to a .rego policy file.",
        exists=True,
        dir_okay=False,
    ),
    out_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--out",
        "-o",
        help="Directory to write templates/, modules/ and rules/ into. "
        "Without it, the YAML is printed.",
    ),
    template: str = typer.Option(
        "input",
        "--template",
        "-t",
        help="Name for the synthesised template holding Rego's `input` document.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit nonzero if any construct was skipped, not only if none converted.",
    ),
) -> None:
    """Convert a Rego policy into Fathom YAML.

    Translates the stateless subset -- `allow`/`deny` rules whose bodies
    compare `input` fields against literals. Anything outside it is reported
    and left out rather than approximated, so what is written is faithful and
    what is missing is listed. Requires the `opa` binary, which does the
    parsing.
    """
    try:
        source = policy.read_text(encoding="utf-8")
        result = convert_ast(parse_rego(source, filename=policy.name), template=template)
    except CompilationError as exc:
        _print_error(f"[fathom.cli] convert failed: {_compilation_error_text(exc)}")
        raise typer.Exit(code=_EXIT_MALFORMED) from exc
    except OSError as exc:
        _print_error(f"[fathom.cli] convert failed: cannot read {policy}: {exc}")
        raise typer.Exit(code=_EXIT_NOT_FOUND) from exc

    _report_conversion(result)

    if not result.converted_anything:
        _print_error(
            "[fathom.cli] convert failed: nothing in this policy is in the convertible subset"
        )
        raise typer.Exit(code=_EXIT_ERROR)

    if out_dir is None:
        typer.echo(
            yaml.safe_dump(
                {
                    "templates": result.templates,
                    "modules": result.modules,
                    "focus_order": [result.module],
                    "module": result.module,
                    "ruleset": result.module,
                    "rules": result.rules,
                },
                sort_keys=False,
                default_flow_style=False,
            )
        )
    else:
        try:
            written = _write_pack(out_dir, result)
        except OSError as exc:
            _print_error(f"[fathom.cli] convert failed: cannot write to {out_dir}: {exc}")
            raise typer.Exit(code=_EXIT_NOT_FOUND) from exc
        for path in written:
            _print_success(f"wrote {path}")

    _print_success(
        f"converted {len(result.rules)} rule(s) from {result.package}; "
        f"{len(result.skipped)} construct(s) skipped"
    )
    if strict and result.skipped:
        raise typer.Exit(code=_EXIT_ERROR)


if __name__ == "__main__":
    app()
