"""Rule pack discovery and loading via Python entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from fathom.errors import CompilationError

if TYPE_CHECKING:
    from fathom.engine import Engine


class RulePackLoader:
    """Discovers and loads rule packs via Python entry points."""

    @staticmethod
    def discover(pack_name: str) -> Path:
        """Find a rule pack by name in the fathom.packs entry point group.

        Returns the package directory path.
        Raises CompilationError if not found.
        """
        eps = entry_points(group="fathom.packs")
        for ep in eps:
            if ep.name == pack_name:
                module = ep.load()
                # Get the directory containing the pack's YAML files
                if hasattr(module, "__path__"):
                    return Path(module.__path__[0])
                elif hasattr(module, "__file__") and module.__file__:
                    return Path(module.__file__).parent
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
    def load(engine: Engine, pack_name: str) -> None:
        """Discover and load a rule pack into an Engine.

        Uses Engine's loading methods -- looks for
        templates/, modules/, functions/, rules/ subdirectories.
        """
        pack_dir = RulePackLoader.discover(pack_name)

        # Load in correct order using Engine's methods
        templates_dir = pack_dir / "templates"
        modules_dir = pack_dir / "modules"
        functions_dir = pack_dir / "functions"
        rules_dir = pack_dir / "rules"

        if templates_dir.is_dir():
            engine.load_templates(str(templates_dir))
        if modules_dir.is_dir():
            engine.load_modules(str(modules_dir))
        if functions_dir.is_dir():
            engine.load_functions(str(functions_dir))
        if rules_dir.is_dir():
            engine.load_rules(str(rules_dir))
