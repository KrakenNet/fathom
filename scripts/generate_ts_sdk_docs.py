"""Run typedoc via pnpm (preferred) or npm to emit TS SDK reference Markdown.

Uses ``typedoc-plugin-markdown`` so the generated output lives under
``docs/reference/typescript-sdk/`` as plain Markdown that MkDocs can pick
up without post-processing (beyond LF normalization for cross-platform
byte-for-byte determinism).

typedoc wipes its ``--out`` directory before each run, so we emit into a
scratch staging directory and then copy the result into ``out_dir``.
That preserves the hand-authored ``index.md`` (and the ``.gitkeep``
placeholder) next to the generated module pages.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TS_PKG = Path("packages/fathom-ts")
DEFAULT_OUT = Path("docs/reference/typescript-sdk")

# Typedoc emits these subtrees; anything outside this set in the staging
# directory is an unexpected artifact.
GENERATED_TOPLEVEL = {"classes", "interfaces"}

# These live alongside the generated tree and must survive regeneration.
PRESERVED_FILES = {"index.md", ".gitkeep"}


def _resolve_tool() -> str | None:
    """Return an absolute path to pnpm or npm, preferring pnpm.

    On Windows the shims are ``.cmd`` files; bare-name ``subprocess.run``
    calls can fail to locate them, so we hand subprocess the resolved
    absolute path.
    """
    for name in ("pnpm", "npm"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _normalize_lf(root: Path) -> None:
    """Rewrite every ``.md`` under ``root`` with LF-only line endings."""
    for md in root.rglob("*.md"):
        data = md.read_bytes()
        if b"\r\n" in data:
            md.write_bytes(data.replace(b"\r\n", b"\n"))


def _rewrite_entry_links(root: Path) -> None:
    """Rewrite typedoc's entry-point references to point at ``index.md``.

    typedoc-plugin-markdown injects ``[@fathom-rules/sdk](../README.md)``
    headers on every class/interface page. MkDocs excludes README.md from
    its resolvable doc set, which turns those into broken links under
    ``--strict``. Redirect them to the hand-authored ``index.md`` instead.
    """
    for md in root.rglob("*.md"):
        if md.name == "README.md":
            continue
        text = md.read_text(encoding="utf-8")
        rewritten = text.replace("](../README.md)", "](../index.md)")
        if rewritten != text:
            md.write_text(rewritten, encoding="utf-8", newline="\n")


def _clean_generated(out_dir: Path) -> None:
    """Remove previously generated artifacts from ``out_dir``.

    Preserves hand-authored files listed in :data:`PRESERVED_FILES` so
    the landing page and ``.gitkeep`` survive a regeneration.
    """
    if not out_dir.exists():
        return
    for child in out_dir.iterdir():
        if child.name in PRESERVED_FILES:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy everything under ``src`` into ``dst``, creating dirs as needed."""
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())


def main(out_dir: Path) -> int:
    tool = _resolve_tool()
    if tool is None:
        print("fail: neither pnpm nor npm on PATH", file=sys.stderr)
        return 1
    tool_name = Path(tool).stem.lower()
    out_dir.mkdir(parents=True, exist_ok=True)

    install_args = (
        ["install", "--ignore-scripts"]
        if tool_name == "pnpm"
        else ["install", "--no-audit", "--ignore-scripts"]
    )
    install = subprocess.run(
        [tool, *install_args],
        cwd=TS_PKG,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if install.returncode != 0:
        sys.stderr.write(install.stdout + install.stderr)
        return install.returncode

    # Emit into a scratch directory first: typedoc clears its --out
    # target on every run and would otherwise delete our hand-authored
    # ``index.md``.
    with tempfile.TemporaryDirectory(prefix="fathom-ts-docs-") as staging:
        staging_path = Path(staging)
        # ``--readme none`` skips the project README page (typedoc would
        # otherwise pull in the repo-root README.md and copy every
        # linked Markdown file into an ``_media/`` sibling directory).
        typedoc_cmd = [
            "typedoc",
            "--plugin",
            "typedoc-plugin-markdown",
            "--readme",
            "none",
            # Pin the git ref used in source URLs so regenerations
            # don't drift every commit (typedoc defaults to the
            # current HEAD SHA, which would fail the drift gate).
            "--gitRevision",
            "master",
            "--out",
            str(staging_path.resolve()),
            "src/index.ts",
        ]
        result = subprocess.run(
            [tool, "exec", "--", *typedoc_cmd],
            cwd=TS_PKG,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout + result.stderr)
            return result.returncode

        _normalize_lf(staging_path)
        _rewrite_entry_links(staging_path)
        # Drop typedoc's auto-generated README.md; the hand-authored
        # index.md is the canonical landing page and README.md is
        # excluded from MkDocs' resolvable doc set anyway.
        readme = staging_path / "README.md"
        if readme.exists():
            readme.unlink()
        _clean_generated(out_dir)
        _copy_tree(staging_path, out_dir)

    print(f"wrote TS SDK docs under {out_dir}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
