"""Convert a Keep-a-Changelog Markdown file into JSON."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

VERSION_HEADING = re.compile(r"^##\s*\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})")
SECTION_HEADING = re.compile(r"^###\s+([A-Za-z]+)")
BULLET = re.compile(r"^[-*]\s+(.+)")

KNOWN_SECTIONS = {"added", "changed", "deprecated", "removed", "fixed", "security"}


def parse(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_section: str | None = None
    for raw in text.splitlines():
        if m := VERSION_HEADING.match(raw):
            if current is not None:
                entries.append(current)
            current = {"version": m.group(1), "date": m.group(2)}
            for k in KNOWN_SECTIONS:
                current[k] = []
            current_section = None
        elif m := SECTION_HEADING.match(raw):
            name = m.group(1).strip().lower()
            current_section = name if name in KNOWN_SECTIONS else None
        elif m := BULLET.match(raw):
            if current is not None and current_section is not None:
                current[current_section].append(m.group(1).strip())
    if current is not None:
        entries.append(current)
    return entries


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("CHANGELOG.md")
    out = Path(argv[2]) if len(argv) > 2 else Path("docs/changelog.json")
    text = src.read_text(encoding="utf-8")
    data = parse(text)
    if not data and text.strip():
        print(
            f"error: {src} has content but parser matched zero versions. "
            "Expected '## [X.Y.Z] - YYYY-MM-DD' headings (Keep-a-Changelog 1.1.0).",
            file=sys.stderr,
        )
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(data)} versions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
