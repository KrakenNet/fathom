"""``POST /v1/compile`` classifies a document exactly like ``fathom compile``.

It answered 200 with no errors for a file of only unknown keys, only
``focus_order``, ``{}``, ``functions: []``, or a classification function with
no ``hierarchy_ref`` -- every one of which ``fathom compile`` refuses -- and it
had no functions branch at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from fathom.cli import app as cli_app
from fathom.integrations.rest import app

if TYPE_CHECKING:
    from pathlib import Path

H = {"Authorization": "Bearer tok"}

DOCS = {
    "unknown_keys": "foo: 1\n",
    "focus_only": "focus_order: [a]\n",
    "empty_mapping": "{}\n",
    "empty_functions": "functions: []\n",
    "function_no_hierarchy": "functions:\n  - name: f\n    params: [a]\n    body: '(+ ?a 1)'\n",
    "rules_unknown_key": "ruleset: r\nmodule: m\nrules: []\nextra: 1\n",
    "templates": (
        "templates:\n  - name: agent\n    slots:\n      - name: id\n        type: symbol\n"
    ),
    "modules": "modules:\n  - name: gov\nfocus_order: [gov]\n",
    "functions_bundled": (
        "hierarchies:\n  - name: lvl\n    levels: [low, high]\n"
        "functions:\n  - name: above\n    type: classification\n"
        "    params: [a, b]\n    hierarchy_ref: lvl\n"
    ),
    "rules": (
        "ruleset: r\nmodule: MAIN\nrules:\n  - name: r1\n    when:\n"
        "      - template: agent\n        conditions:\n"
        "          - slot: id\n            expression: equals(alice)\n"
        "    then:\n      action: allow\n"
    ),
}


@pytest.mark.parametrize("name", sorted(DOCS))
def test_rest_compile_agrees_with_cli(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FATHOM_API_TOKEN", "tok")
    doc = DOCS[name]
    f = tmp_path / "doc.yaml"
    f.write_text(doc)
    cli_failed = CliRunner().invoke(cli_app, ["compile", str(f)]).exit_code != 0

    resp = TestClient(app).post("/v1/compile", headers=H, json={"yaml_content": doc})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert bool(body["errors"]) == cli_failed, (name, body)
    assert bool(body["clips"]) != cli_failed, (name, body)
    assert str(tmp_path) not in resp.text


@pytest.mark.parametrize("name", ["unknown_keys", "focus_only", "empty_mapping"])
def test_validate_refuses_a_document_with_no_constructs(name: str, tmp_path: Path) -> None:
    f = tmp_path / "doc.yaml"
    f.write_text(DOCS[name])
    result = CliRunner().invoke(cli_app, ["validate", str(f)])
    assert result.exit_code != 0, result.output
    # A lone focus_order has its own, more specific refusal.
    if name != "focus_only":
        assert "no Fathom constructs found" in result.output
