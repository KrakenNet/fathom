"""Extract fenced Python code blocks from tutorial pages and execute them.

Python blocks are executed in a subprocess with fathom importable.
YAML content is verified by being loaded inside the Python block that
references it — no separate YAML runner.

Tag ``no-verify`` skips a block. Tag ``reset`` starts a fresh subprocess
for python blocks (default: consecutive python blocks share scope).

Exit codes: 0 clean; 1 snippet failure; 2 misconfig.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

FENCE = re.compile(r"^```(\w+)([^\n]*)$")

_TIMEOUT_SECONDS = 60


@dataclass
class Block:
    lang: str
    tags: set[str]
    body: str
    page: Path
    line: int


def _extract(page: Path) -> list[Block]:
    text = page.read_text(encoding="utf-8")
    blocks: list[Block] = []
    lines = text.splitlines(keepends=True)
    i = 0
    line_no = 1
    while i < len(lines):
        m = FENCE.match(lines[i].rstrip("\n"))
        if m:
            lang = m.group(1)
            tags = set(m.group(2).split())
            start = i + 1
            start_line = line_no + 1
            j = start
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            body = "".join(lines[start:j])
            blocks.append(Block(lang=lang, tags=tags, body=body, page=page, line=start_line))
            line_no += j - i + 1
            i = j + 1
        else:
            line_no += 1
            i += 1
    return blocks


def _run_python_group(blocks: list[Block]) -> tuple[int, str]:
    program = "\n".join(b.body for b in blocks)
    with tempfile.TemporaryDirectory(prefix="fathom-snip-") as d:
        try:
            r = subprocess.run(
                [sys.executable, "-c", program],
                cwd=d,
                capture_output=True,
                text=True,
                check=False,
                timeout=_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return 1, f"timed out after {_TIMEOUT_SECONDS} s"
    return r.returncode, r.stderr


def _process(page: Path) -> list[str]:
    blocks = _extract(page)
    errors: list[str] = []
    py_group: list[Block] = []
    for b in blocks:
        if "no-verify" in b.tags:
            continue
        if b.lang != "python":
            continue
        if "reset" in b.tags and py_group:
            rc, err = _run_python_group(py_group)
            if rc != 0:
                errors.append(f"{page}:{py_group[0].line} {err}")
            py_group = []
        py_group.append(b)
    if py_group:
        rc, err = _run_python_group(py_group)
        if rc != 0:
            errors.append(f"{page}:{py_group[0].line} {err}")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "docs/tutorials").resolve()
    if not root.is_dir():
        print(f"error: {root} not a directory", file=sys.stderr)
        return 2
    had_errors = False
    for page in sorted(root.rglob("*.md")):
        for e in _process(page):
            print(e, file=sys.stderr)
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
