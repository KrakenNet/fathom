import json
import subprocess
import sys
from pathlib import Path


def test_export_writes_valid_openapi(tmp_path: Path) -> None:
    out = tmp_path / "openapi.json"
    result = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["openapi"].startswith("3.")
    assert "Fathom" in data["info"]["title"]
    assert "paths" in data and len(data["paths"]) > 0


def test_committed_spec_is_in_sync_with_the_app(tmp_path: Path) -> None:
    """The published spec must match what the code actually serves.

    A stale ``docs/reference/rest/openapi.json`` is a wire-contract lie: it
    shipped advertising ``maxItems: 1000`` on ``EvaluateRequest.facts`` after
    the code had moved on, and without the ErrorResponse envelope at all.
    """
    out = tmp_path / "openapi.json"
    result = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    committed = Path("docs/reference/rest/openapi.json").read_text(encoding="utf-8")
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(committed), (
        "docs/reference/rest/openapi.json is stale — run "
        "`python scripts/export_openapi.py docs/reference/rest/openapi.json`"
    )


def test_spec_documents_the_error_envelope() -> None:
    """Every error the API returns uses ErrorResponse, so the spec must say so.

    Without a declared ``responses`` mapping, FastAPI publishes its default
    422 shape — a ``detail`` LIST of error objects — which is not what the
    app returns. A client generated from the spec cannot parse a real error.
    """
    data = json.loads(Path("docs/reference/rest/openapi.json").read_text(encoding="utf-8"))
    assert "ErrorResponse" in data["components"]["schemas"]
    ref = "#/components/schemas/ErrorResponse"
    for path in ("/v1/evaluate", "/v1/facts", "/v1/query", "/v1/compile"):
        responses = data["paths"][path]["post"]["responses"]
        assert "422" in responses, path
        schema = responses["422"]["content"]["application/json"]["schema"]
        assert schema.get("$ref") == ref, (path, schema)
