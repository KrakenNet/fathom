"""Generate Python SDK reference stubs under docs/reference/python-sdk/.

Reads ``fathom.__all__`` and writes one short Markdown stub per public
symbol. Each stub uses a ``:::`` mkdocstrings directive so the actual
API reference (signatures, docstrings, type hints) is rendered at
``mkdocs build`` time from live source. Also writes an ``index.md``
landing page that links every symbol.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fathom

DEFAULT_OUT = Path("docs/reference/python-sdk")


def _stub_body(qualname: str) -> str:
    return f"# `fathom.{qualname}`\n\n::: fathom.{qualname}\n"


def _index_body(symbols: list[str]) -> str:
    lines = [
        "# Python SDK Reference",
        "",
        "Generated from `fathom.__all__` at docs-build time via mkdocstrings.",
        "",
        "## Public symbols",
        "",
    ]
    lines.extend(f"- [`{s}`]({s.lower()}.md)" for s in symbols)
    lines.append("")
    return "\n".join(lines)


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear previous run so deleted symbols don't leave orphan pages
    for child in out_dir.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            # No nested dirs expected; be tolerant
            for sub in child.rglob("*"):
                if sub.is_file():
                    sub.unlink()
            child.rmdir()
        else:
            child.unlink()

    symbols = [s for s in fathom.__all__ if not s.startswith("_")]
    for name in symbols:
        (out_dir / f"{name.lower()}.md").write_text(_stub_body(name), encoding="utf-8")
    (out_dir / "index.md").write_text(_index_body(symbols), encoding="utf-8")

    print(f"wrote {len(symbols) + 1} Python SDK stubs under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
