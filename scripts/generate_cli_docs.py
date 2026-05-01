"""Generate per-command CLI reference by invoking `fathom <cmd> --help`.

One Markdown page per Typer @app.command() in fathom.cli.app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Pin terminal width and disable ANSI escapes BEFORE Typer/Rich imports.
# Rich reads COLUMNS at Console construction time and only honors NO_COLOR
# / FORCE_COLOR if they are present in os.environ before its first import.
#
# Use unconditional assignment, NOT ``setdefault``: GitHub Actions' bash
# runner inherits ``COLUMNS=80`` from the parent shell environment, so
# the previous ``setdefault`` was a no-op on CI and produced 80-column
# tables that drifted from the 100-column tables generated locally.
# Likewise NO_COLOR / TERM=dumb must override whatever the runner ships.
os.environ["COLUMNS"] = "100"
os.environ["TERMINAL_WIDTH"] = "100"
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"

DEFAULT_OUT = Path("docs/reference/cli")


def _help_for(command_name: str | None) -> str:
    from typer.testing import CliRunner

    from fathom.cli import app

    # Click's CliRunner ignores ``COLUMNS`` because the invocation is not
    # a real TTY; it falls back to its own 80-column default unless the
    # caller passes ``terminal_width`` explicitly. Pin to 100 here so the
    # generated CLI docs match across local regens and the CI runner.
    runner = CliRunner()
    args = [command_name, "--help"] if command_name else ["--help"]
    result = runner.invoke(app, args, terminal_width=100)
    if result.exit_code != 0:
        raise RuntimeError(
            f"fathom {command_name} --help failed "
            f"(exit {result.exit_code}): {result.output}"
        )
    return result.output


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
