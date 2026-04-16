"""Convert docs/reference/rest/openapi.json → Postman v2 collection via npx.

The converter emits a random ``_postman_id``, per-item UUIDs, and
schema-faker-seeded example payloads. All three change between runs, so
the post-processor in this module stabilizes each of them before writing
the collection back to disk. The drift gate (``git diff docs/reference``)
relies on this determinism.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_FAKER_KEY = re.compile(r"^key_\d+$")

DEFAULT_IN = Path("docs/reference/rest/openapi.json")
DEFAULT_OUT = Path("docs/reference/rest/fathom.postman_collection.json")

# Deterministic stand-in for the random UUID openapi-to-postmanv2 generates.
_STABLE_POSTMAN_ID = "fathom-00000000-0000-0000-0000-000000000000"

# Options passed to openapi-to-postmanv2 via ``-O``. We still post-process
# because ``schemaFaker=false`` does not fully suppress random payload
# generation for open-ended ``additionalProperties`` maps.
_CONVERTER_OPTIONS = ",".join(
    [
        "schemaFaker=false",
        "parametersResolution=Example",
    ]
)


def _stabilize_value(value: Any) -> Any:
    """Recursively replace scalar leaves with type-stable placeholders.

    The faker emits ``true``/``false``/``42``/``3.14``/``"string"`` at
    random for schemas without explicit examples. We collapse each scalar
    to a deterministic stand-in of the same JSON type so importers still
    get a well-typed template.
    """
    if isinstance(value, dict):
        # Collapse faker-seeded ``additionalProperties`` maps (keys like
        # ``key_0``/``key_1``/...) to a single canonical entry. The count
        # and leaf types vary per run, so we replace the whole map.
        if value and all(_FAKER_KEY.match(k) for k in value.keys()):
            return {"<key>": "<value>"}
        return {k: _stabilize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stabilize_value(x) for x in value]
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0
    if isinstance(value, float):
        return 0.0
    if isinstance(value, str):
        return value  # strings in payloads are already `<string>` placeholders
    return value


def _stabilize_json_string(raw: str) -> str:
    """Parse ``raw`` as JSON, stabilize, and re-serialize with sorted keys."""
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    stabilized = _stabilize_value(parsed)
    return json.dumps(stabilized, indent=2, sort_keys=True)


def _walk(node: Any, parent_key: str | None = None) -> Any:
    """Recursively stabilize collection content.

    - Drops all ``id`` keys (Postman regenerates on import).
    - Rewrites ``body``/``raw`` JSON strings with sorted keys and typed
      placeholder leaves.
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k == "id":
                continue
            out[k] = _walk(v, parent_key=k)
        return out
    if isinstance(node, list):
        return [_walk(x, parent_key=parent_key) for x in node]
    if parent_key in {"body", "raw"} and isinstance(node, str):
        return _stabilize_json_string(node)
    return node


def _normalize(collection: dict) -> dict:
    """Strip fields that openapi-to-postmanv2 populates non-deterministically."""
    info = collection.get("info", {})
    info["_postman_id"] = _STABLE_POSTMAN_ID
    collection["info"] = info
    return _walk(collection)


def main(out_path: Path) -> int:
    if not DEFAULT_IN.exists():
        print(f"fail: {DEFAULT_IN} not found; run export_openapi.py first", file=sys.stderr)
        return 1
    npx = shutil.which("npx")
    if npx is None:
        print("fail: npx not on PATH; install Node 18+ and re-run", file=sys.stderr)
        return 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        npx,
        "-y",
        "openapi-to-postmanv2@5",
        "-s",
        str(DEFAULT_IN),
        "-o",
        str(out_path),
        "-p",
        "-O",
        _CONVERTER_OPTIONS,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=300
        )
    except subprocess.TimeoutExpired:
        print(
            "fail: openapi-to-postmanv2 timed out after 300s; check network/registry",
            file=sys.stderr,
        )
        return 1
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    # Post-process for determinism.
    data = json.loads(out_path.read_text(encoding="utf-8"))
    data = _normalize(data)
    out_path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
