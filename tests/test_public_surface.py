"""Bind the declared public surface to the one the package actually exposes.

`VERSIONING.md` promises that everything in `fathom.__all__` keeps working and
that everything else may move without notice. A promise nobody checks drifts:
the list rots as symbols are added, and callers cannot tell which half of the
document is current. These tests fail on that drift instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

import pytest

import fathom
from fathom import (
    attestation,
    audit,
    chained_log,
    compiler,
    engine,
    errors,
    fleet,
    integrations,
    models,
    packs,
    rego,
)

VERSIONING = Path(__file__).resolve().parents[1] / "VERSIONING.md"
_EXAMPLE_BLP = Path(__file__).resolve().parents[1] / "examples" / "03-classification-blp"

_COVERED_BLOCK = re.compile(
    r"<!-- BEGIN COVERED SYMBOLS -->\n(.*?)\n<!-- END COVERED SYMBOLS -->",
    re.S,
)
_BULLET = re.compile(r"^- `([^`]+)`$", re.M)

#: Every module VERSIONING.md names as having its own covered ``__all__``.
DOCUMENTED_MODULES = [
    attestation,
    audit,
    chained_log,
    compiler,
    engine,
    errors,
    fleet,
    integrations,
    models,
    packs,
    rego,
]

#: The covered modules that need an optional extra to import. Checked the same
#: way, and skipped where the extra is not installed.
EXTRA_MODULES = [
    "fathom.fleet_pg",
    "fathom.fleet_redis",
    "fathom.integrations.crewai",
    "fathom.integrations.google_adk",
    "fathom.integrations.grpc_server",
    "fathom.integrations.langchain",
    "fathom.integrations.mcp_server",
    "fathom.integrations.openai_agents",
    "fathom.integrations.rest",
]

_TABLE_ROW = re.compile(r"^\| `(fathom[\w.]*)` \|", re.M)


def _documented_symbols() -> list[str]:
    match = _COVERED_BLOCK.search(VERSIONING.read_text(encoding="utf-8"))
    assert match is not None, "VERSIONING.md is missing its COVERED SYMBOLS markers"
    return _BULLET.findall(match.group(1))


def test_versioning_md_lists_exactly_the_exported_symbols() -> None:
    documented = _documented_symbols()
    assert documented == sorted(fathom.__all__), (
        "VERSIONING.md and fathom.__all__ disagree. Adding a symbol to __all__ "
        "commits the project to keeping it working, so the list in "
        "VERSIONING.md has to be updated in the same change."
    )


@pytest.mark.parametrize("name", sorted(fathom.__all__))
def test_every_exported_symbol_resolves(name: str) -> None:
    """Including the lazy ones, which a typo would turn into an AttributeError."""
    assert getattr(fathom, name, None) is not None


def _assert_declares_a_surface(module: object) -> None:
    names = getattr(module, "__all__", None)
    assert names, f"{module.__name__} is named in VERSIONING.md but declares no __all__"
    assert list(names) == sorted(names), f"{module.__name__}.__all__ is not sorted"
    for name in names:
        assert hasattr(module, name), f"{module.__name__}.__all__ names a missing {name!r}"


@pytest.mark.parametrize("module", DOCUMENTED_MODULES, ids=lambda m: m.__name__)
def test_documented_modules_declare_a_surface(module: object) -> None:
    _assert_declares_a_surface(module)


@pytest.mark.parametrize("name", EXTRA_MODULES)
def test_documented_extra_modules_declare_a_surface(name: str) -> None:
    _assert_declares_a_surface(pytest.importorskip(name))


def test_versioning_md_tables_exactly_the_checked_modules() -> None:
    """A module added to the table but not here would be covered and unchecked."""
    tabled = _TABLE_ROW.findall(VERSIONING.read_text(encoding="utf-8"))
    checked = [m.__name__ for m in DOCUMENTED_MODULES] + EXTRA_MODULES
    assert sorted(tabled) == sorted(checked)


def test_pack_format_is_what_versioning_md_covers() -> None:
    """The pack format is covered: the entry-point group, layout and dependency hook."""
    assert packs.LOAD_ORDER == ("templates", "modules", "functions", "rules")
    assert packs.DEPENDENCIES_ATTR == "PACK_DEPENDENCIES"
    text = VERSIONING.read_text(encoding="utf-8")
    shipped = [
        ep.name for ep in distribution("fathom-rules").entry_points if ep.group == "fathom.packs"
    ]
    assert shipped, "fathom-rules registers no fathom.packs entry points"
    missing = [name for name in shipped if f"`{name}`" not in text]
    assert not missing, f"shipped rule packs not named in VERSIONING.md: {missing}"


def test_top_level_exports_come_from_a_module_that_declares_them() -> None:
    """A re-export must be public where it is defined, not only at the top.

    Exporting a name from ``fathom`` while its own module keeps it internal
    leaves two answers to "is this covered?", and the wrong one is reachable
    by the import path the docs use.
    """
    surfaces = {n for m in DOCUMENTED_MODULES for n in getattr(m, "__all__", ())}
    unbacked = [n for n in fathom.__all__ if not n.startswith("__") and n not in surfaces]
    assert not unbacked, f"exported from fathom but not from their own module: {unbacked}"


def test_types_covered_methods_return_or_raise_are_exported() -> None:
    """Engine.agenda/rule_matches return these, reload_rules raises the last."""
    for name in ("Activation", "RuleMatches", "RulesetSignatureError"):
        assert name in fathom.__all__, name


def test_ruleset_signature_error_is_a_fathom_error() -> None:
    from fathom.integrations.ruleset_sig import RulesetSignatureError

    assert RulesetSignatureError is fathom.RulesetSignatureError
    assert issubclass(RulesetSignatureError, fathom.FathomError)


def test_compiler_declares_its_surface() -> None:
    from fathom import compiler

    assert compiler.__all__ == ["Compiler"]


@pytest.mark.parametrize("prop", ["template_registry", "module_registry", "rule_registry"])
def test_engine_registries_are_read_only(prop: str) -> None:
    eng = fathom.Engine.from_rules(str(_EXAMPLE_BLP))
    view = getattr(eng, prop)
    assert view
    with pytest.raises(TypeError):
        view["x"] = None  # type: ignore[index]
    assert not hasattr(view, "clear")


@pytest.mark.parametrize("prop", ["template_registry", "module_registry", "rule_registry"])
def test_engine_registry_values_are_copies(prop: str) -> None:
    """Mutating a returned definition must not reach the engine."""
    eng = fathom.Engine.from_rules(str(_EXAMPLE_BLP))
    name, value = next(iter(getattr(eng, prop).items()))
    before = value.model_dump()
    for field_name in type(value).model_fields:
        attr = getattr(value, field_name)
        if isinstance(attr, list):
            attr.clear()
    assert getattr(eng, prop)[name].model_dump() == before
    assert next(iter(getattr(eng, prop).values())).model_dump() == before


def test_engine_hierarchy_is_a_copy() -> None:
    eng = fathom.Engine.from_rules(str(_EXAMPLE_BLP))
    eng.hierarchy("clearance").levels.clear()
    assert eng.hierarchy("clearance").levels


def test_engine_hierarchy_accessor() -> None:
    eng = fathom.Engine.from_rules(str(_EXAMPLE_BLP))
    assert eng.hierarchy("clearance").levels[0] == "unclassified"
    with pytest.raises(fathom.ValidationError, match="nope"):
        eng.hierarchy("nope")


def test_rego_surface_shape() -> None:
    """Text in, keyword template like convert_ast; no private or constant names."""
    import inspect

    params = inspect.signature(rego.convert_source).parameters
    assert list(params) == ["source", "filename", "template"]
    assert (
        params["template"].default
        == inspect.signature(rego.convert_ast).parameters["template"].default
    )
    assert all(p.kind is p.KEYWORD_ONLY for n, p in params.items() if n != "source")
    assert list(inspect.signature(rego.flatten_input).parameters) == ["document"]
    assert "convert_file" not in rego.__all__
    assert "OPA_DOWNLOAD_URL" not in rego.__all__
    assert inspect.signature(rego.export_engine).parameters["engine"].annotation in (
        "Engine",
        engine.Engine,
    )


def test_convert_source_honours_template() -> None:
    if shutil.which("opa") is None:
        pytest.skip("opa binary not installed")
    source = 'package p\n\nallow if input.role == "admin"\n'
    result = rego.convert_source(source, template="req")
    assert result.templates[0]["name"] == "req"
    assert result.rules[0]["when"][0]["template"] == "req"


@pytest.mark.parametrize(
    ("module", "missing", "extra"),
    [
        ("fathom.attestation", "jwt", "attestation"),
        ("fathom.chained_log", "jwt", "attestation"),
        ("fathom.integrations.rest", "fastapi", "server"),
    ],
)
def test_covered_extra_module_names_its_extra(module: str, missing: str, extra: str) -> None:
    """Importing without the extra says which extra to install, not just the package."""
    code = (
        f"import sys; sys.modules[{missing!r}] = None\n"
        f"try:\n    import {module}\n"
        "except ImportError as exc:\n    print(exc)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert f"fathom-rules[{extra}]" in out


def test_type_checkers_reject_a_misspelled_export(tmp_path: Path) -> None:
    """The PEP 562 hook must not make every ``fathom.<typo>`` type as Any."""
    api = pytest.importorskip("mypy.api")
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import fathom\nx = fathom.AttestationService\ny = fathom.Enigne\n", encoding="utf-8"
    )
    out, _, status = api.run(["--no-incremental", "--follow-imports=silent", str(probe)])
    assert status == 1, out
    assert '"Enigne"' in out and "probe.py:3:" in out and "probe.py:2:" not in out, out
