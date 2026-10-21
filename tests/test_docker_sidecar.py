"""The README's REST-sidecar commands must work against the shipped image.

They did not: the image declared ``VOLUME /rules`` but never pointed
``FATHOM_RULESET_ROOT`` at it, so every evaluate was a 500, and the README's
``docker run`` passed no token (401) and its ``curl`` no ``Content-Type``
(422). The live check is a docker run; these pin the three pieces of text.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_image_points_the_ruleset_root_at_its_volume() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    volume = re.search(r'^VOLUME \["([^"]+)"\]', dockerfile, re.M)
    assert volume is not None
    assert re.search(rf"FATHOM_RULESET_ROOT={re.escape(volume.group(1))}\b", dockerfile)


def test_readme_sidecar_command_passes_a_token_and_a_content_type() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("**As a REST sidecar**", 1)[1].split("**As a gRPC sidecar**", 1)[0]
    assert "-e FATHOM_API_TOKEN" in section
    assert "Content-Type: application/json" in section
