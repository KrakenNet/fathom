import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_postman_collection_generated(tmp_path: Path) -> None:
    if shutil.which("npx") is None:
        pytest.skip("npx not available on this environment")
    out = tmp_path / "fathom.postman_collection.json"
    result = subprocess.run(
        [sys.executable, "scripts/generate_postman_collection.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "info" in data
    assert "item" in data


def test_postman_collection_is_deterministic(tmp_path: Path) -> None:
    if shutil.which("npx") is None:
        pytest.skip("npx not available on this environment")
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    for out in (out_a, out_b):
        result = subprocess.run(
            [sys.executable, "scripts/generate_postman_collection.py", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    assert out_a.read_bytes() == out_b.read_bytes(), (
        "regenerated Postman collection differs — normalizer missed a "
        "non-deterministic field; compare with `diff <(jq . a.json) <(jq . b.json)`"
    )

    data = json.loads(out_a.read_text(encoding="utf-8"))
    assert data["info"]["_postman_id"] == "fathom-00000000-0000-0000-0000-000000000000", (
        "stable _postman_id was not applied"
    )
