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


def test_spec_declares_every_status_the_routes_return() -> None:
    """Reload and the session GET routes listed only 200 and 422.

    Reload answers 400/401/413/500/503 too, and the session GETs answer 400
    for a missing ``X-Session-Id`` (which the spec marked optional), 401 and
    404. The reload 200 body had no schema.
    """
    data = json.loads(Path("docs/reference/rest/openapi.json").read_text(encoding="utf-8"))
    ref = "#/components/schemas/ErrorResponse"
    reload = data["paths"]["/v1/rules/reload"]["post"]["responses"]
    for code in ("400", "401", "413", "422", "500", "503"):
        assert reload[code]["content"]["application/json"]["schema"]["$ref"] == ref, code
    assert reload["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/RulesetReloadResponse"
    )
    for path in ("/v1/templates", "/v1/rules", "/v1/modules"):
        op = data["paths"][path]["get"]
        for code in ("400", "401", "404"):
            assert op["responses"][code]["content"]["application/json"]["schema"]["$ref"] == ref
        header = [p for p in op["parameters"] if p["name"] == "X-Session-Id"]
        assert len(header) == 1 and header[0]["required"] is True, (path, header)
