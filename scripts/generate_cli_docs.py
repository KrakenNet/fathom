"""Generate per-command CLI reference by invoking `fathom <cmd> --help`.

One Markdown page per Typer @app.command() in fathom.cli.app.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Pin terminal width BEFORE Typer/Rich imports. Rich reads COLUMNS at
# Console construction time; without this pin, the drift gate fails on
# any machine whose terminal differs from CI's default width.
#
# Notes:
#  - COLUMNS / TERMINAL_WIDTH must be force-set (not setdefault): when
#    pytest runs the script via subprocess, COLUMNS is typically unset
#    and Rich falls back to its 80-col default.
#  - We don't bother trying to suppress ANSI emission via env vars: Rich
#    treats *any* FORCE_COLOR value (including "0") as force-on, and the
#    GITHUB_ACTIONS=true env CI sets independently re-enables color even
#    under NO_COLOR=1. Stripping ANSI from the captured help text after
#    the fact (see _ANSI_ESCAPE below) is the only reliable approach.
os.environ["COLUMNS"] = "100"
os.environ["TERMINAL_WIDTH"] = "100"

# CSI sequences used by Rich for bold/dim/color: ESC [ ... letter.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

DEFAULT_OUT = Path("docs/reference/cli")


def _help_for(command_name: str | None) -> str:
    from typer.testing import CliRunner

    from fathom.cli import app

    runner = CliRunner()
    args = [command_name, "--help"] if command_name else ["--help"]
    result = runner.invoke(app, args)
    if result.exit_code != 0:
        raise RuntimeError(
            f"fathom {command_name} --help failed "
            f"(exit {result.exit_code}): {result.output}"
        )
    return _ANSI_ESCAPE.sub("", result.output)


def _page(command_name: str, help_text: str) -> str:
    return "\n".join(
        [
            "---",
            f"title: fathom {command_name}",
            f"summary: CLI reference for `fathom {command_name}`",
            "audience: [app-developers, rule-authors]",
            "diataxis: reference",
            "status: stable",
            "last_verified: 2026-04-15",
            "---",
            "",
            f"# `fathom {command_name}`",
            "",
            "```",
            help_text.rstrip(),
            "```",
            "",
        ]
    )


def _index(commands: list[str]) -> str:
    lines = [
        "---",
        "title: CLI Reference",
        "summary: Index of `fathom` CLI commands",
        "audience: [app-developers, rule-authors]",
        "diataxis: reference",
        "status: stable",
        "last_verified: 2026-04-15",
        "---",
        "",
        "# CLI Reference",
        "",
        "| Command | |",
        "|---|---|",
    ]
    for cmd in commands:
        lines.append(f"| [`fathom {cmd}`]({cmd}.md) | |")
    lines.append("")
    return "\n".join(lines)


def main(out_dir: Path) -> int:
    from fathom.cli import app

    out_dir.mkdir(parents=True, exist_ok=True)
    # Typer stores the explicit name on CommandInfo.name; when registered via a
    # bare @app.command() decorator, that is None and the CLI name is derived
    # from the callback's __name__. Our six commands are single-word functions,
    # so __name__ matches the Typer-rendered command name.
    commands = sorted(
        (cmd.name or (cmd.callback.__name__ if cmd.callback else ""))
        for cmd in app.registered_commands
    )
    commands = [c for c in commands if c]

    for name in commands:
        help_text = _help_for(name)
        (out_dir / f"{name}.md").write_text(_page(name, help_text), encoding="utf-8", newline="\n")

    (out_dir / "index.md").write_text(_index(commands), encoding="utf-8", newline="\n")
    print(f"wrote CLI reference for {len(commands)} command(s) under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
