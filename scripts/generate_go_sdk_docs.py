"""Run gomarkdoc over packages/fathom-go to emit Markdown reference."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

GO_PKG = Path("packages/fathom-go")
DEFAULT_OUT = Path("docs/reference/go-sdk")

# Pin gomarkdoc so regenerations stay byte-identical across machines.
# Bump this version deliberately and re-commit the generated .md when
# upgrading the tool.
GOMARKDOC_VERSION = "v1.1.0"


def _resolve_gomarkdoc() -> str:
    """Locate the gomarkdoc binary, honoring GOBIN/GOPATH overrides."""
    found = shutil.which("gomarkdoc")
    if found:
        return found

    gobin_proc = subprocess.run(
        ["go", "env", "GOBIN"],
        capture_output=True,
        text=True,
        check=True,
    )
    gobin = gobin_proc.stdout.strip()

    gopath_proc = subprocess.run(
        ["go", "env", "GOPATH"],
        capture_output=True,
        text=True,
        check=True,
    )
    gopath = gopath_proc.stdout.strip()
    gopath_bin = str(Path(gopath) / "bin") if gopath else ""

    search_dirs = [d for d in (gobin, gopath_bin) if d]
    names = ["gomarkdoc.exe", "gomarkdoc"] if os.name == "nt" else ["gomarkdoc"]
    for directory in search_dirs:
        for name in names:
            candidate = Path(directory) / name
            if candidate.exists():
                return str(candidate)

    raise RuntimeError(
        f"gomarkdoc not found after install; searched PATH, "
        f"GOBIN={gobin}, GOPATH/bin={gopath_bin}"
    )


def main(out_dir: Path) -> int:
    if shutil.which("go") is None:
        print("fail: go not on PATH", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "fathom-go.md"

    # Install the pinned gomarkdoc into the user's GOBIN.
    install = subprocess.run(
        [
            "go",
            "install",
            f"github.com/princjef/gomarkdoc/cmd/gomarkdoc@{GOMARKDOC_VERSION}",
        ],
        cwd=GO_PKG,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if install.returncode != 0:
        sys.stderr.write(install.stdout + install.stderr)
        return install.returncode

    gomarkdoc = _resolve_gomarkdoc()

    # Explicitly pin the repository URL, default branch, and path. Auto
    # detection works locally but silently produces link-less output on
    # the GH Actions runner — even with ``fetch-depth: 0`` — so the
    # drift gate kept failing on every PR. Forcing these values keeps
    # gomarkdoc's anchor links stable across local and CI regens.
    cmd = [
        gomarkdoc,
        "--repository.url",
        "https://github.com/KrakenNet/fathom",
        "--repository.default-branch",
        "main",
        "--repository.path",
        "/packages/fathom-go",
        "--output",
        str(out_file.resolve()),
        "./...",
    ]
    result = subprocess.run(
        cmd, cwd=GO_PKG, capture_output=True, text=True, check=False, timeout=120
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode

    # LF-normalize gomarkdoc's output so Windows regens match Linux CI.
    text = out_file.read_text(encoding="utf-8")
    out_file.write_text(text, encoding="utf-8", newline="\n")

    print(f"wrote {out_file}")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
