"""Dump the FastAPI app's OpenAPI schema to disk."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fathom.integrations.rest import app


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("docs/reference/rest/openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
