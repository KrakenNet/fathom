"""Tests for the hash-chained JWS-signed attestation log."""

from __future__ import annotations

import json
import stat
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from fathom.attestation import AttestationService
from fathom.chained_log import (
    CHAIN_ISSUER,
    CHECKPOINT_RECORD_TYPE,
    FORMAT_VERSION,
    GENESIS_RECORD_TYPE,
    AnchorEvent,
    ChainedAttestationLog,
    _canonical,
    _sha256_hex,
    key_fingerprint,
    load_or_create_key,
    verify_chain,
    write_private_key_atomic,
)
from fathom.cli import app
from fathom.errors import AttestationError

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture
def service() -> AttestationService:
    return AttestationService.generate_keypair()


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "chain.jsonl"


def _make_log(log_path: Path, service: AttestationService, n: int = 3) -> ChainedAttestationLog:
    log = ChainedAttestationLog(log_path, service)
    for i in range(n):
        log.append({"event": "test", "i": i})
    return log


class TestAppend:
    def test_append_and_records_roundtrip(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service)
        records = log.records()
        # Line 1 is the auto-written genesis record; payloads follow.
        assert records[0].record["type"] == GENESIS_RECORD_TYPE
        assert [r.record["i"] for r in records[1:]] == [0, 1, 2]
        assert [r.seq for r in records] == [0, 1, 2, 3]
        assert records[0].prev_sha256 is None
        assert records[1].prev_sha256 == records[0].line_sha256
        assert records[2].prev_sha256 == records[1].line_sha256
        assert log.head_sha256 == records[3].line_sha256
        assert log.head_seq == 3

    def test_find_record(self, log_path: Path, service: AttestationService) -> None:
        log = _make_log(log_path, service)
        rec = log.find_record(2)
        assert rec is not None
        assert rec.record == {"event": "test", "i": 1}
        assert log.find_record(99) is None

    def test_public_key_exported_beside_log(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service, n=1)
        assert log.public_key_path == log_path.with_name("chain.jsonl.pub.pem")
        assert log.public_key_path.read_bytes() == service.public_key_pem()

    def test_reopen_resumes_chain(self, log_path: Path, service: AttestationService) -> None:
        log1 = _make_log(log_path, service)
        head = log1.head_sha256
        log1.close()

        log2 = ChainedAttestationLog(log_path, service)
        assert log2.head_seq == 3
        assert log2.head_sha256 == head
        assert log2.log_id == log1.log_id
        rec = log2.append({"event": "after-reopen"})
        assert rec.seq == 4
        assert rec.prev_sha256 == head
        assert log2.verify().ok


class TestVerify:
    def test_valid_chain_verifies(self, log_path: Path, service: AttestationService) -> None:
        log = _make_log(log_path, service)
        result = log.verify()
        assert result.ok
        assert result.count == 3
        assert result.head_sha256 == log.head_sha256
        assert result.error is None
        assert result.anchor_ok is None

    def test_empty_log_verifies(self, log_path: Path, service: AttestationService) -> None:
        log_path.touch()
        result = verify_chain(log_path, service.public_key)
        assert result.ok
        assert result.count == 0
        assert result.head_sha256 is None

    def test_verify_with_pem_path(
        self, log_path: Path, service: AttestationService, tmp_path: Path
    ) -> None:
        _make_log(log_path, service)
        pem = tmp_path / "pub.pem"
        pem.write_bytes(service.public_key_pem())
        assert verify_chain(log_path, pem).ok

    def test_tampered_record_fails(self, log_path: Path, service: AttestationService) -> None:
        _make_log(log_path, service)
        lines = log_path.read_bytes().splitlines()
        obj = json.loads(lines[1])
        obj["record"]["i"] = 999
        lines[1] = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
        log_path.write_bytes(b"\n".join(lines) + b"\n")

        result = verify_chain(log_path, service.public_key)
        assert not result.ok
        # Editing line 1 changes its hash, so line 2's prev pointer breaks.
        assert result.error_line == 3 or "claims mismatch" in (result.error or "")

    def test_deleted_middle_line_fails(self, log_path: Path, service: AttestationService) -> None:
        _make_log(log_path, service)
        lines = log_path.read_bytes().splitlines()
        del lines[1]
        log_path.write_bytes(b"\n".join(lines) + b"\n")

        result = verify_chain(log_path, service.public_key)
        assert not result.ok
        assert result.error_line == 2

    def test_reordered_lines_fail(self, log_path: Path, service: AttestationService) -> None:
        _make_log(log_path, service)
        lines = log_path.read_bytes().splitlines()
        lines[1], lines[2] = lines[2], lines[1]
        log_path.write_bytes(b"\n".join(lines) + b"\n")

        assert not verify_chain(log_path, service.public_key).ok

    def test_wrong_public_key_fails(self, log_path: Path, service: AttestationService) -> None:
        _make_log(log_path, service)
        other = AttestationService.generate_keypair()
        result = verify_chain(log_path, other.public_key)
        assert not result.ok
        # The genesis fingerprint check rejects before any signature work.
        assert "genesis key fingerprint" in (result.error or "")
        assert result.error_line == 1

    def test_malformed_line_reported_not_raised(
        self, log_path: Path, service: AttestationService
    ) -> None:
        _make_log(log_path, service)
        with open(log_path, "ab") as fh:
            fh.write(b'{"torn": tru\n')

        result = verify_chain(log_path, service.public_key)
        assert not result.ok
        assert result.error_line == 5
        assert "line 5" in (result.error or "")


class TestFailClosed:
    def test_torn_write_refuses_append(self, log_path: Path, service: AttestationService) -> None:
        log = _make_log(log_path, service)
        log.close()
        with open(log_path, "ab") as fh:
            fh.write(b'{"partial"')  # torn write: no newline, invalid JSON

        reopened = ChainedAttestationLog(log_path, service)
        assert reopened.corruption is not None
        with pytest.raises(AttestationError, match="refusing append"):
            reopened.append({"event": "nope"})

    def test_broken_chain_refuses_append(
        self, log_path: Path, service: AttestationService
    ) -> None:
        _make_log(log_path, service)
        lines = log_path.read_bytes().splitlines()
        del lines[1]
        log_path.write_bytes(b"\n".join(lines) + b"\n")

        reopened = ChainedAttestationLog(log_path, service)
        with pytest.raises(AttestationError, match="refusing append"):
            reopened.append({"event": "nope"})


class TestAnchors:
    def test_truncation_undetectable_without_anchor(
        self, log_path: Path, service: AttestationService
    ) -> None:
        _make_log(log_path, service)
        lines = log_path.read_bytes().splitlines()
        log_path.write_bytes(b"\n".join(lines[:2]) + b"\n")

        # Standalone verification cannot see the missing tail.
        assert verify_chain(log_path, service.public_key).ok

    def test_expected_head_detects_truncation(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service)
        head = log.head_sha256
        assert head is not None
        assert verify_chain(log_path, service.public_key, expected_head=head).anchor_ok

        lines = log_path.read_bytes().splitlines()
        log_path.write_bytes(b"\n".join(lines[:2]) + b"\n")
        result = verify_chain(log_path, service.public_key, expected_head=head)
        assert not result.ok
        assert result.anchor_ok is False
        assert "truncated" in (result.error or "")

    def test_expected_head_ok_when_log_grew(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service)
        head = log.head_sha256
        assert head is not None
        log.append({"event": "later"})
        result = verify_chain(log_path, service.public_key, expected_head=head)
        assert result.ok
        assert result.anchor_ok is True

    def test_checkpoint_and_anchor_callback(
        self, log_path: Path, service: AttestationService
    ) -> None:
        events: list[AnchorEvent] = []
        log = ChainedAttestationLog(log_path, service, anchor_callback=events.append)
        log.append({"event": "a"})
        cp = log.checkpoint()

        assert cp.record["type"] == CHECKPOINT_RECORD_TYPE
        assert cp.record["head_seq"] == 1  # genesis is seq 0
        assert len(events) == 1
        assert events[0].seq == cp.seq
        assert events[0].head_sha256 == cp.line_sha256
        assert events[0].checkpoint_jws == cp.jws
        assert log.verify().ok

    def test_anchor_token_detects_truncation(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service)
        cp = log.checkpoint()
        log.append({"event": "tail"})

        ok = verify_chain(log_path, service.public_key, anchor_token=cp.jws)
        assert ok.ok and ok.anchor_ok

        # Truncate back past the checkpoint's pinned head.
        lines = log_path.read_bytes().splitlines()
        log_path.write_bytes(b"\n".join(lines[:2]) + b"\n")
        result = verify_chain(log_path, service.public_key, anchor_token=cp.jws)
        assert not result.ok
        assert result.anchor_ok is False

    def test_anchor_token_detects_checkpoint_line_truncation(
        self, log_path: Path, service: AttestationService
    ) -> None:
        """Dropping only the checkpoint line (and after) must still fail."""
        log = _make_log(log_path, service)
        cp = log.checkpoint()

        lines = log_path.read_bytes().splitlines()
        log_path.write_bytes(b"\n".join(lines[: cp.seq]) + b"\n")
        result = verify_chain(log_path, service.public_key, anchor_token=cp.jws)
        assert not result.ok
        assert result.anchor_ok is False

    def test_auto_checkpoint_interval(self, log_path: Path, service: AttestationService) -> None:
        events: list[AnchorEvent] = []
        log = ChainedAttestationLog(
            log_path, service, checkpoint_interval=2, anchor_callback=events.append
        )
        for i in range(4):
            log.append({"i": i})
        types = [r.record.get("type") for r in log.records()]
        assert types.count(CHECKPOINT_RECORD_TYPE) == 2
        assert len(events) == 2
        assert log.verify().ok


class TestFormatV1:
    def test_genesis_line_and_envelope_shape(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service, n=1)
        lines = [json.loads(line) for line in log_path.read_bytes().splitlines()]
        assert all(line["v"] == FORMAT_VERSION for line in lines)
        genesis = lines[0]["record"]
        assert genesis["type"] == GENESIS_RECORD_TYPE
        assert genesis["log_id"] == log.log_id
        assert genesis["key_fingerprint"] == key_fingerprint(service.public_key)

    def test_kid_header_on_every_line(self, log_path: Path, service: AttestationService) -> None:
        import jwt as pyjwt

        log = _make_log(log_path, service, n=2)
        fp = key_fingerprint(service.public_key)
        for rec in log.records():
            assert pyjwt.get_unverified_header(rec.jws)["kid"] == fp

    def test_count_excludes_meta_records(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service, n=3)
        log.checkpoint()
        result = log.verify()
        assert result.ok
        assert result.count == 3  # genesis + checkpoint not counted
        assert result.log_id == log.log_id

    def test_unsupported_version_fails(self, log_path: Path, service: AttestationService) -> None:
        _make_log(log_path, service, n=1)
        lines = log_path.read_bytes().splitlines()
        obj = json.loads(lines[1])
        obj["v"] = 2
        lines[1] = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
        log_path.write_bytes(b"\n".join(lines) + b"\n")

        result = verify_chain(log_path, service.public_key)
        assert not result.ok
        assert "unsupported format version" in (result.error or "")

    def test_missing_genesis_fails(self, tmp_path: Path, service: AttestationService) -> None:
        """A structurally valid line 1 that is not a genesis record is rejected."""
        record = {"event": "no-genesis"}
        iat = 1700000000
        claims = {
            "iss": CHAIN_ISSUER,
            "iat": iat,
            "seq": 0,
            "prev_sha256": None,
            "record_sha256": _sha256_hex(_canonical(record)),
            "log_id": "forged",
            "v": FORMAT_VERSION,
        }
        token = service.sign_claims(claims, headers={"kid": key_fingerprint(service.public_key)})
        line = _canonical(
            {"iat": iat, "jws": token, "prev_sha256": None, "record": record, "seq": 0, "v": 1}
        )
        log_path = tmp_path / "no-genesis.jsonl"
        log_path.write_bytes(line + b"\n")

        result = verify_chain(log_path, service.public_key)
        assert not result.ok
        assert "missing genesis record" in (result.error or "")
        assert result.error_line == 1

    def test_reopen_with_different_key_fails_closed(
        self, log_path: Path, service: AttestationService
    ) -> None:
        log = _make_log(log_path, service, n=1)
        log.close()
        other = AttestationService.generate_keypair()
        reopened = ChainedAttestationLog(log_path, other)
        assert reopened.corruption is not None
        assert "genesis key fingerprint" in reopened.corruption
        with pytest.raises(AttestationError, match="refusing append"):
            reopened.append({"event": "wrong-key"})
        # The wrong-key open must not clobber the correct exported pubkey.
        assert reopened.public_key_path.read_bytes() == service.public_key_pem()

    def test_anchor_token_rejected_on_other_log_same_key(
        self, tmp_path: Path, service: AttestationService
    ) -> None:
        """Anchor from log A must not verify against log B (same key)."""
        log_a = _make_log(tmp_path / "a.jsonl", service)
        cp = log_a.checkpoint()
        log_b = _make_log(tmp_path / "b.jsonl", service)
        assert log_a.log_id != log_b.log_id

        result = verify_chain(log_b.path, service.public_key, anchor_token=cp.jws)
        assert not result.ok
        assert result.anchor_ok is False


class TestKeyHandling:
    def test_atomic_key_creation_0600(self, tmp_path: Path) -> None:
        key_path = tmp_path / "keys" / "chain.key"
        service = load_or_create_key(key_path)
        if sys.platform != "win32":  # Windows does not enforce POSIX modes
            mode = stat.S_IMODE(key_path.stat().st_mode)
            assert mode == 0o600
        assert not key_path.with_name("chain.key.tmp").exists()
        assert key_path.with_name("chain.key.pub.pem").read_bytes() == service.public_key_pem()

    def test_load_or_create_roundtrip(self, tmp_path: Path) -> None:
        key_path = tmp_path / "chain.key"
        first = load_or_create_key(key_path)
        second = load_or_create_key(key_path)
        assert first.public_key_pem() == second.public_key_pem()

    def test_write_private_key_atomic_returns_pub_path(
        self, tmp_path: Path, service: AttestationService
    ) -> None:
        pub = write_private_key_atomic(service, tmp_path / "k.pem")
        assert pub.read_bytes() == service.public_key_pem()


class TestCli:
    def _setup(self, tmp_path: Path) -> tuple[Path, Path, ChainedAttestationLog]:
        service = AttestationService.generate_keypair()
        log_path = tmp_path / "chain.jsonl"
        log = _make_log(log_path, service)
        return log_path, log.public_key_path, log

    def test_verify_chain_ok(self, tmp_path: Path) -> None:
        log_path, pub, _ = self._setup(tmp_path)
        result = runner.invoke(app, ["verify-chain", str(log_path), "--pubkey", str(pub)])
        assert result.exit_code == 0
        assert "chain valid" in result.output

    def test_verify_chain_json(self, tmp_path: Path) -> None:
        log_path, pub, _ = self._setup(tmp_path)
        result = runner.invoke(
            app, ["verify-chain", str(log_path), "--pubkey", str(pub), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["count"] == 3

    def test_verify_chain_tampered_exits_1(self, tmp_path: Path) -> None:
        log_path, pub, _ = self._setup(tmp_path)
        lines = log_path.read_bytes().splitlines()
        del lines[1]
        log_path.write_bytes(b"\n".join(lines) + b"\n")
        result = runner.invoke(app, ["verify-chain", str(log_path), "--pubkey", str(pub)])
        assert result.exit_code == 1

    def test_verify_chain_missing_log_exits_2(self, tmp_path: Path) -> None:
        _, pub, _ = self._setup(tmp_path)
        result = runner.invoke(
            app, ["verify-chain", str(tmp_path / "missing.jsonl"), "--pubkey", str(pub)]
        )
        assert result.exit_code == 2

    def test_verify_chain_expected_head_truncated(self, tmp_path: Path) -> None:
        log_path, pub, log = self._setup(tmp_path)
        head = log.head_sha256
        assert head is not None
        lines = log_path.read_bytes().splitlines()
        log_path.write_bytes(b"\n".join(lines[:1]) + b"\n")
        result = runner.invoke(
            app,
            [
                "verify-chain",
                str(log_path),
                "--pubkey",
                str(pub),
                "--expected-head",
                head,
            ],
        )
        assert result.exit_code == 1
        assert "truncated" in result.output
