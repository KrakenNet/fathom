"""Rule pack discovery and loading, by entry-point name or directory path."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

import yaml

from fathom.compiler import Compiler
from fathom.errors import CompilationError

if TYPE_CHECKING:
    from types import ModuleType

    from fathom.engine import Engine
    from fathom.models import TemplateDefinition

#: Module attribute a rule pack may define to declare packs that must be
#: loaded before it, by their ``fathom.packs`` entry-point name.
#: Example: ``PACK_DEPENDENCIES = ("nist-800-53",)``.
DEPENDENCIES_ATTR = "PACK_DEPENDENCIES"


@dataclass
class _PackState:
    """Which packs an Engine already has, and who owns each template name."""

    loaded: set[str] = field(default_factory=set)
    template_owner: dict[str, str] = field(default_factory=dict)


#: Per-engine pack state, keyed weakly so engines stay collectable.
_pack_state: WeakKeyDictionary[Engine, _PackState] = WeakKeyDictionary()


def forget_packs(engine: Engine) -> None:
    """Drop *engine*'s record of which packs it holds.

    Called by :meth:`fathom.engine.Engine.reload_rules`, which swaps in a
    fresh CLIPS environment and discards the rule registry — so after a
    reload the engine no longer has the pack's rules. Keeping the "already
    loaded" record across that made a subsequent ``load_pack`` a silent
    no-op: the call returned successfully while the pack's rules stayed
    absent, quietly weakening policy. Forgetting the record means the retry
    is attempted and fails loudly if it cannot succeed.
    """
    _pack_state.pop(engine, None)


#: Glob for template files, kept deliberately in step with
#: ``Engine.load_templates``. See ``_check_template_collisions``.
TEMPLATE_GLOB = "*.yaml"

#: The four kinds of definition a pack holds, in the only order that works:
#: rules reference functions and templates, and every rule is scoped to a
#: module. Loading out of this order fails inside CLIPS with a diagnostic
#: about the generated construct rather than about the ordering.
LOAD_ORDER = ("templates", "modules", "functions", "rules")


def _template_files(templates_dir: Path) -> list[Path]:
    """Template files under *templates_dir*, in the order the Engine loads them."""
    return sorted(templates_dir.glob(TEMPLATE_GLOB))


def _group_flat_files(pack_dir: Path) -> dict[str, list[Path]]:
    """Sort loose ``*.yaml`` files in *pack_dir* by their top-level key.

    The fallback layout for a pack that does not use the subdirectory
    convention: one flat directory of YAML whose top-level key says what each
    file holds. Files that parse to something other than a mapping, or whose
    keys name nothing recognised, are skipped rather than guessed at.
    """
    grouped: dict[str, list[Path]] = {kind: [] for kind in LOAD_ORDER}
    for yaml_file in sorted(pack_dir.glob(TEMPLATE_GLOB)):
        with open(yaml_file) as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            continue
        if "templates" in data:
            grouped["templates"].append(yaml_file)
        elif "modules" in data or "focus_order" in data:
            grouped["modules"].append(yaml_file)
        elif "functions" in data:
            grouped["functions"].append(yaml_file)
        elif "rules" in data or "ruleset" in data:
            grouped["rules"].append(yaml_file)
    return grouped


class RulePackLoader:
    """Discovers and loads rule packs via Python entry points."""

    @staticmethod
    def _resolve(pack_name: str) -> tuple[ModuleType, Path]:
        """Return the module and directory of the pack registered as *pack_name*."""
        eps = entry_points(group="fathom.packs")
        for ep in eps:
            if ep.name == pack_name:
                module = ep.load()
                # Get the directory containing the pack's YAML files
                if hasattr(module, "__path__"):
                    return module, Path(module.__path__[0])
                elif hasattr(module, "__file__") and module.__file__:
                    return module, Path(module.__file__).parent
                else:
                    raise CompilationError(
                        f"Rule pack '{pack_name}' has no discoverable path",
                        construct=f"pack:{pack_name}",
                    )
        raise CompilationError(
            f"Rule pack '{pack_name}' not found in fathom.packs entry points",
            construct=f"pack:{pack_name}",
        )

    @staticmethod
    def discover(pack_name: str) -> Path:
        """Find a rule pack by name in the fathom.packs entry point group.

        Returns the package directory path.
        Raises CompilationError if not found.
        """
        return RulePackLoader._resolve(pack_name)[1]

    @staticmethod
    def load(engine: Engine, pack_name: str) -> None:
        """Discover and load a rule pack into an Engine.

        Packs named in the pack module's ``PACK_DEPENDENCIES`` are loaded
        first, and a pack already loaded into *engine* is never loaded twice.

        Uses Engine's loading methods -- looks for
        templates/, modules/, functions/, rules/ subdirectories.

        Raises:
            CompilationError: If the pack (or one of its dependencies) is
                unknown, forms a dependency cycle, redefines a template
                another pack already registered, or fails to load.
        """
        RulePackLoader._load_pack(engine, pack_name, ())

    @staticmethod
    def _load_pack(engine: Engine, pack_name: str, chain: tuple[str, ...]) -> None:
        """Load *pack_name* and its dependencies, tracking the resolution *chain*."""
        state = _pack_state.setdefault(engine, _PackState())
        if pack_name in state.loaded:
            return
        if pack_name in chain:
            raise CompilationError(
                "Circular rule pack dependency: " + " -> ".join([*chain, pack_name]),
                construct=f"pack:{pack_name}",
            )
        module, pack_dir = RulePackLoader._resolve(pack_name)

        for dependency in getattr(module, DEPENDENCIES_ATTR, ()):
            RulePackLoader._load_pack(engine, dependency, (*chain, pack_name))

        try:
            RulePackLoader._load_from_dir(engine, pack_name, pack_dir, state)
        except ValueError as exc:
            # Engine loading raises a bare ValueError for e.g. an unknown
            # module in a focus order; the documented pack failure mode is
            # CompilationError.
            raise CompilationError(
                f"Rule pack '{pack_name}' failed to load",
                construct=f"pack:{pack_name}",
                detail=str(exc),
            ) from exc

    @staticmethod
    def load_dir(engine: Engine, path: str | Path, *, require_content: bool = True) -> None:
        """Load a rule pack from a directory on disk into *engine*.

        The entry-point half of this loader (:meth:`load`) only finds packs
        that ship as installed distributions. A host that keeps packs as
        directories -- vendored, uploaded at runtime, or checked out beside
        the application -- had to call ``load_templates`` / ``load_modules``
        / ``load_functions`` / ``load_rules`` itself, in that exact order,
        with no error if it got the order wrong. This is that ordering,
        exposed.

        A directory is identified by its resolved path, so loading the same
        one twice is a no-op and two packs cannot silently claim the same
        template name. What this does NOT do is resolve
        ``PACK_DEPENDENCIES``: a directory has no module to declare them on,
        so a pack that needs another loaded first must have that one loaded
        by its caller.

        Args:
            engine: The engine to load into.
            path: Directory holding the pack, in either supported layout --
                ``templates/`` ``modules/`` ``functions/`` ``rules/``
                subdirectories, or loose ``*.yaml`` files whose top-level key
                names the kind.
            require_content: Reject a directory holding nothing this loader
                recognises, which is what pointing one level too high looks
                like. ``Engine.from_rules`` passes False: an empty directory
                is how ``FleetEngine`` builds session engines it then seeds
                by hand, and that predates this method.

        Raises:
            CompilationError: If *path* is not a directory, holds nothing
                this loader recognises, or redefines a template the engine
                already has from another pack.
        """
        pack_dir = Path(path).resolve(strict=False)
        if not pack_dir.is_dir():
            raise CompilationError(
                f"Rule pack directory '{path}' is not a directory",
                construct=f"pack:{path}",
            )
        state = _pack_state.setdefault(engine, _PackState())
        label = str(pack_dir)
        if label in state.loaded:
            return
        if require_content and not RulePackLoader._holds_a_pack(pack_dir):
            raise CompilationError(
                f"Rule pack '{label}' holds nothing to load",
                construct=f"pack:{label}",
                detail=(
                    "Expected templates/, modules/, functions/ or rules/ "
                    "subdirectories, or *.yaml files whose top-level key is "
                    "one of templates, modules, functions, rules/ruleset."
                ),
            )
        RulePackLoader._load_from_dir(engine, label, pack_dir, state)

    @staticmethod
    def _holds_a_pack(pack_dir: Path) -> bool:
        """Whether *pack_dir* has anything either layout would load."""
        if any((pack_dir / kind).is_dir() for kind in LOAD_ORDER):
            return True
        return any(_group_flat_files(pack_dir).values())

    @staticmethod
    def _load_from_dir(engine: Engine, label: str, pack_dir: Path, state: _PackState) -> None:
        """Load *pack_dir* into *engine* in ``LOAD_ORDER``, recording ownership.

        Shared by the entry-point loader, :meth:`load_dir`, and
        ``Engine.from_rules``: the ordering rule is subtle enough that a
        second copy of it is a second place to get it wrong.
        """
        subdirs = {kind: pack_dir / kind for kind in LOAD_ORDER}
        by_subdir = any(d.is_dir() for d in subdirs.values())
        grouped = {} if by_subdir else _group_flat_files(pack_dir)

        # Collisions are checked before anything is built, so a pack that
        # would redefine another's template leaves the engine untouched.
        template_files = (
            _template_files(subdirs["templates"])
            if by_subdir and subdirs["templates"].is_dir()
            else grouped.get("templates", [])
        )
        pack_templates = RulePackLoader._check_template_collisions(
            engine, label, template_files, state
        )

        for kind in LOAD_ORDER:
            load = getattr(engine, f"load_{kind}")
            if by_subdir:
                # A whole directory in one call: load_modules treats the set
                # of modules it is given as one declaration for focus
                # purposes, so splitting it per file would not be the same.
                if subdirs[kind].is_dir():
                    load(str(subdirs[kind]))
            else:
                for file in grouped[kind]:
                    load(str(file))

        # Record ownership last so a failed load leaves no trace. Only claim
        # templates nobody owns yet: when two packs define a template
        # IDENTICALLY the load is allowed, and blindly reassigning ownership
        # to the newcomer would make a later collision message name the wrong
        # original owner.
        for template_name in pack_templates:
            state.template_owner.setdefault(template_name, label)
        state.loaded.add(label)

    @staticmethod
    def _check_template_collisions(
        engine: Engine,
        pack_name: str,
        template_files: list[Path],
        state: _PackState,
    ) -> list[str]:
        """Return the template names *pack_name* defines, rejecting redefinitions.

        Two packs that define the same template name with different slots
        cannot share an Engine (CLIPS refuses to redefine a deftemplate that
        is in use). Detect that here so the caller sees which packs collide
        instead of a raw CLIPS diagnostic.

        *template_files* must be exactly the files ``Engine.load_templates``
        will be given. If this check saw a narrower set, a template it
        skipped would sail past into the raw CLIPS error this exists to
        replace.
        """
        compiler = Compiler()
        names: list[str] = []
        registry = engine.template_registry
        for file in template_files:
            definitions: list[TemplateDefinition] = compiler.parse_template_file(file)
            for defn in definitions:
                names.append(defn.name)
                existing = registry.get(defn.name)
                if existing is None or existing == defn:
                    continue
                owner = state.template_owner.get(defn.name)
                origin = f"rule pack '{owner}'" if owner else "this engine"
                raise CompilationError(
                    f"Rule pack '{pack_name}' redefines template "
                    f"'{defn.name}' already registered by {origin}",
                    file=str(file),
                    construct=f"template:{defn.name}",
                    detail=(
                        "Two packs define incompatible templates with the same "
                        "name; load them into separate Engines."
                    ),
                )
        return names
