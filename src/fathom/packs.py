"""Rule pack discovery and loading via Python entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

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


def _template_files(templates_dir: Path) -> list[Path]:
    """Template files under *templates_dir*, in the order the Engine loads them."""
    return sorted(templates_dir.glob(TEMPLATE_GLOB))


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

        # Load in correct order using Engine's methods
        templates_dir = pack_dir / "templates"
        modules_dir = pack_dir / "modules"
        functions_dir = pack_dir / "functions"
        rules_dir = pack_dir / "rules"

        pack_templates: list[str] = []
        if templates_dir.is_dir():
            pack_templates = RulePackLoader._check_template_collisions(
                engine, pack_name, templates_dir, state
            )

        try:
            if templates_dir.is_dir():
                engine.load_templates(str(templates_dir))
            if modules_dir.is_dir():
                engine.load_modules(str(modules_dir))
            if functions_dir.is_dir():
                engine.load_functions(str(functions_dir))
            if rules_dir.is_dir():
                engine.load_rules(str(rules_dir))
        except ValueError as exc:
            # Engine loading raises a bare ValueError for e.g. an unknown
            # module in a focus order; the documented pack failure mode is
            # CompilationError.
            raise CompilationError(
                f"Rule pack '{pack_name}' failed to load",
                construct=f"pack:{pack_name}",
                detail=str(exc),
            ) from exc

        # Record ownership last so a failed load leaves no trace. Only claim
        # templates nobody owns yet: when two packs define a template
        # IDENTICALLY the load is allowed, and blindly reassigning ownership
        # to the newcomer would make a later collision message name the wrong
        # original owner.
        for template_name in pack_templates:
            state.template_owner.setdefault(template_name, pack_name)
        state.loaded.add(pack_name)

    @staticmethod
    def _check_template_collisions(
        engine: Engine,
        pack_name: str,
        templates_dir: Path,
        state: _PackState,
    ) -> list[str]:
        """Return the template names *pack_name* defines, rejecting redefinitions.

        Two packs that define the same template name with different slots
        cannot share an Engine (CLIPS refuses to redefine a deftemplate that
        is in use). Detect that here so the caller sees which packs collide
        instead of a raw CLIPS diagnostic.

        The glob must match what ``Engine.load_templates`` loads. If this
        check saw a narrower set, a template it skipped would sail past into
        the raw CLIPS error this exists to replace.
        """
        compiler = Compiler()
        names: list[str] = []
        registry = engine.template_registry
        for file in _template_files(templates_dir):
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
