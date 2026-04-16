"""Emit /llms.txt and /llms-full.txt from mkdocs.yml nav + page frontmatter."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _read_frontmatter(md_path: Path) -> tuple[dict[str, Any], str]:
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4 :].lstrip("\n")
    return fm, body


def _walk_nav(nav: list[Any], out: list[tuple[str, str]]) -> None:
    for item in nav:
        if isinstance(item, str):
            out.append(("", item))
        elif isinstance(item, dict):
            for label, value in item.items():
                if isinstance(value, str):
                    out.append((label, value))
                elif isinstance(value, list):
                    _walk_nav(value, out)


def main() -> int:
    root = Path.cwd()
    cfg = yaml.safe_load((root / "mkdocs.yml").read_text(encoding="utf-8"))
    docs_dir = root / cfg.get("docs_dir", "docs")
    site_url = cfg.get("site_url", "").rstrip("/") + "/"
    site_name = cfg.get("site_name", "Site")
    nav = cfg.get("nav", [])

    pages: list[tuple[str, str]] = []
    _walk_nav(nav, pages)

    idx_lines: list[str] = [f"# {site_name}", ""]
    idx_lines.append(cfg.get("site_description") or f"Documentation for {site_name}.")
    idx_lines.append("")
    idx_lines.append("## Pages")
    idx_lines.append("")

    full_parts: list[str] = []

    for label, rel_path in pages:
        md = docs_dir / rel_path
        if not md.exists():
            continue
        fm, body = _read_frontmatter(md)
        url = site_url + rel_path.replace(".md", "/")
        title = fm.get("title") or label or md.stem
        summary = (fm.get("summary") or "").strip()
        summary_suffix = f" — {summary}" if summary else ""
        idx_lines.append(f"- [{title}]({url}){summary_suffix}")
        full_parts.append(f"## {rel_path}\n\n{body}\n")

    (docs_dir / "llms.txt").write_text("\n".join(idx_lines) + "\n", encoding="utf-8")
    (docs_dir / "llms-full.txt").write_text("\n".join(full_parts), encoding="utf-8")
    print(f"wrote {docs_dir / 'llms.txt'} and {docs_dir / 'llms-full.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
