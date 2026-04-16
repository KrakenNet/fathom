"""Export Pydantic models in src/fathom/models.py to JSON Schema files."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

MODELS: tuple[tuple[str, str], ...] = (
    ("template", "fathom.models.TemplateDefinition"),
    ("rule", "fathom.models.RulesetDefinition"),
    ("module", "fathom.models.ModuleDefinition"),
    ("function", "fathom.models.FunctionDefinition"),
    ("hierarchy", "fathom.models.HierarchyDefinition"),
)


def _resolve(dotted: str) -> Any:
    module_name, class_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("docs/reference/yaml/schemas")
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for name, dotted in MODELS:
        try:
            model = _resolve(dotted)
        except (ImportError, AttributeError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        schema = model.model_json_schema()
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        (out_dir / f"{name}.schema.json").write_text(
            json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"wrote {name}.schema.json")
    if errors:
        print("errors:", errors, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
