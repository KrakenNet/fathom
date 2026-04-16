"""Run protoc with protoc-gen-doc to emit Markdown reference for fathom.proto."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

PROTO = Path("protos/fathom.proto")
DEFAULT_OUT = Path("docs/reference/grpc")


def main(out_dir: Path) -> int:
    if not PROTO.exists():
        print(f"fail: {PROTO} not found", file=sys.stderr)
        return 1
    if shutil.which("protoc") is None:
        print("fail: protoc not on PATH", file=sys.stderr)
        return 1
    plugin_path = shutil.which("protoc-gen-doc")
    if plugin_path is None:
        print("fail: protoc-gen-doc not on PATH", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    # Copy with LF-normalized line endings so the committed artifact matches
    # both Windows and Linux regenerations byte-for-byte.
    proto_text = PROTO.read_text(encoding="utf-8")
    (out_dir / "fathom.proto").write_text(
        proto_text, encoding="utf-8", newline="\n"
    )

    cmd = [
        "protoc",
        f"--plugin=protoc-gen-doc={plugin_path}",
        f"--doc_out={out_dir}",
        "--doc_opt=markdown,fathom.md",
        f"-I{PROTO.parent}",
        str(PROTO),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        return result.returncode
    print(f"wrote {out_dir}/fathom.md and {out_dir}/fathom.proto")
    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    sys.exit(main(out))
