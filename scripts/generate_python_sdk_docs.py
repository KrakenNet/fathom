"""Generate Python SDK reference stubs under docs/reference/python-sdk/.

Reads ``fathom.__all__`` and writes one short Markdown stub per public
symbol. Each stub uses a ``:::`` mkdocstrings directive so the actual
API reference (signatures, docstrings, type hints) is rendered at
``mkdocs build`` time from live source. Also writes an ``index.md``
landing page that links every symbol, plus the optional fleet stores,
which are not in ``fathom.__all__`` because importing them needs an extra.
"""

from __future__ import annotations

import sys
from pathlib import Path

import fathom

DEFAULT_OUT = Path("docs/reference/python-sdk")

# Public classes outside ``fathom.__all__``: their modules import an optional
# dependency, so ``import fathom`` cannot re-export them.
OPTIONAL = {
    "fleet_redis.RedisFactStore": "fleet",
    "fleet_pg.PostgresFactStore": "fleet-pg",
}


def _stub_body(qualname: str) -> str:
    return f"# `fathom.{qualname}`\n\n::: fathom.{qualname}\n"


def _name(qualname: str) -> str:
    return qualname.rsplit(".", 1)[-1]


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
    lines += ["", "## Optional fleet stores", ""]
    lines.extend(
        f"- [`fathom.{q}`]({_name(q).lower()}.md) — `pip install fathom-rules[{extra}]`"
        for q, extra in OPTIONAL.items()
    )
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
    for q in OPTIONAL:
        (out_dir / f"{_name(q).lower()}.md").write_text(_stub_body(q), encoding="utf-8")
    (out_dir / "index.md").write_text(_index_body(symbols), encoding="utf-8")

    print(f"wrote {len(symbols) + len(OPTIONAL) + 1} Python SDK stubs under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
