"""README lists the names a reader types: pack names and CLI commands must be real."""

from __future__ import annotations

import re
from importlib.metadata import entry_points
from pathlib import Path

import typer.main

from fathom.cli import app

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")


def _section(heading: str) -> str:
    return README.split(f"**{heading}**", 1)[1].split("\n**", 1)[0]


def test_readme_rule_packs_are_the_entry_point_names() -> None:
    listed = set(re.findall(r"^- `([^`]+)`", _section("Rule packs"), re.M))
    shipped = {ep.name for ep in entry_points(group="fathom.packs")}
    assert listed == shipped


def test_readme_cli_line_names_every_command() -> None:
    line = next(ln for ln in README.splitlines() if ln.startswith("- **CLI**"))
    listed = set(re.findall(r"`fathom ([a-z-]+)`", line))
    commands = set(typer.main.get_command(app).commands)  # type: ignore[attr-defined]
    assert listed == commands
