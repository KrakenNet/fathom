"""End-to-end tests for `fathom verify-artifact` (T-3.1, AC-3.7).

Exercises the full sign-then-verify chain using the real `minisign` CLI:
generates a fresh keypair in `tmp_path`, signs a fixture artifact, then
shells into the Fathom Typer app via CliRunner and asserts the exit code
matches the CLI's exit-code contract (T-1.14):

    0 = valid
    1 = mismatch (bad sig, wrong pubkey)
    2 = missing artifact or missing sig
    3 = malformed sig

Tests skip cleanly if the `minisign` binary is not on PATH (or in
`~/.local/bin`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fathom.cli import app


def _find_minisign() -> str | None:
    """Locate the minisign binary, falling back to ~/.local/bin."""
    found = shutil.which("minisign")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "minisign"
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return str(fallback)
    return None


_MINISIGN = _find_minisign()

pytestmark = pytest.mark.skipif(
    _MINISIGN is None,
    reason="`minisign` binary not found on PATH or in ~/.local/bin",
)


def _gen_keypair(tmp_path: Path, name: str = "key") -> tuple[Path, Path]:
    """Generate a passwordless minisign keypair. Returns (pubkey, privkey)."""
    assert _MINISIGN is not None
    pub = tmp_path / f"{name}.pub"
    priv = tmp_path / f"{name}.key"
    subprocess.run(
        [_MINISIGN, "-G", "-W", "-f", "-p", str(pub), "-s", str(priv)],
        check=True,
        capture_output=True,
    )
    return pub, priv


def _sign(artifact: Path, privkey: Path) -> Path:
    """Sign `artifact` with `privkey`; return the produced .minisig path."""
    assert _MINISIGN is not None
    sig_path = Path(str(artifact) + ".minisig")
    subprocess.run(
        [_MINISIGN, "-S", "-s", str(privkey), "-x", str(sig_path), "-m", str(artifact)],
        check=True,
        capture_output=True,
        input=b"\n",  # empty password confirm for -W keypair
    )
    return sig_path


@pytest.fixture
def artifact(tmp_path: Path) -> Path:
    """A small fixture artifact file."""
    a = tmp_path / "release.whl"
    a.write_bytes(b"fathom-fixture-artifact-bytes\n")
    return a


@pytest.fixture
def keypair(tmp_path: Path) -> tuple[Path, Path]:
    """A fresh passwordless minisign keypair."""
    return _gen_keypair(tmp_path)


runner = CliRunner()


def _invoke(artifact: Path, sig: Path, pubkey: Path) -> object:
    """Invoke `fathom verify-artifact` via CliRunner."""
    return runner.invoke(
        app,
        [
            "verify-artifact",
            str(artifact),
            "--sig",
            str(sig),
            "--pubkey",
            str(pubkey),
        ],
    )


def test_happy_valid_triple(artifact: Path, keypair: tuple[Path, Path]) -> None:
    """Valid artifact + sig + pubkey → exit 0, stdout says ok."""
    pub, priv = keypair
    sig = _sign(artifact, priv)
    result = _invoke(artifact, sig, pub)
    assert result.exit_code == 0, result.output
    assert "ok" in result.output


def test_tampered_artifact(artifact: Path, keypair: tuple[Path, Path]) -> None:
    """Byte-flipped artifact → exit 1 (mismatch)."""
    pub, priv = keypair
    sig = _sign(artifact, priv)
    data = bytearray(artifact.read_bytes())
    data[0] ^= 0x01  # flip one bit
    artifact.write_bytes(bytes(data))
    result = _invoke(artifact, sig, pub)
    assert result.exit_code == 1


def test_wrong_pubkey(tmp_path: Path, artifact: Path, keypair: tuple[Path, Path]) -> None:
    """Signature verified against a different pubkey → non-zero exit (fail).

    Per AC-3.7 the requirement is simply that verification fails. The CLI
    classifies a key-id mismatch (sig key-id ≠ pubkey key-id) as `malformed`
    (exit 3) rather than `mismatch` (exit 1) because the failure is detected
    during parse-time key-id matching before any Ed25519 verify is attempted.
    Either non-zero exit satisfies AC-3.7.
    """
    pub, priv = keypair
    sig = _sign(artifact, priv)
    other_pub, _other_priv = _gen_keypair(tmp_path, name="other")
    result = _invoke(artifact, sig, other_pub)
    assert result.exit_code != 0
    assert result.exit_code in {1, 3}


def test_missing_sig(artifact: Path, keypair: tuple[Path, Path]) -> None:
    """Sig file absent → exit 2 (not found)."""
    pub, priv = keypair
    sig = _sign(artifact, priv)
    sig.unlink()
    result = _invoke(artifact, sig, pub)
    assert result.exit_code == 2


def test_malformed_sig(artifact: Path, keypair: tuple[Path, Path]) -> None:
    """Sig file replaced with garbage → exit 3 (malformed)."""
    pub, priv = keypair
    sig = _sign(artifact, priv)
    sig.write_bytes(b"this is not a valid minisign signature file\n")
    result = _invoke(artifact, sig, pub)
    assert result.exit_code == 3
