import json
import subprocess
import sys
from pathlib import Path


def test_rule_pack_generator_emits_per_pack_pages(tmp_path: Path) -> None:
    out = tmp_path / "rule-packs"
    result = subprocess.run(
        [sys.executable, "scripts/generate_rule_pack_docs.py", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    expected = {"owasp-agentic.md", "nist-800-53.md", "hipaa.md", "cmmc.md"}
    actual = {p.name for p in out.glob("*.md")}
    assert expected.issubset(actual), f"missing: {expected - actual}"

    catalog = json.loads((out / "rule-packs.json").read_text(encoding="utf-8"))
    assert isinstance(catalog, list) and len(catalog) >= 4
    ids = {entry["id"] for entry in catalog}
    assert {"owasp-agentic", "nist-800-53", "hipaa", "cmmc"}.issubset(ids)

    owasp = (out / "owasp-agentic.md").read_text(encoding="utf-8")
    assert "detect-prompt-injection" in owasp
    assert "salience" in owasp.lower()
