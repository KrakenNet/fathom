"""Append-only hash-chained JSONL attestation log with JWS signing.

Each line is a compact JSON object (format version 1)::

    {"iat": ..., "jws": "<compact JWS>", "prev_sha256": ..., "record": {...}, "seq": N, "v": 1}

- ``prev_sha256`` is the SHA-256 (hex) of the previous raw line bytes
  (without the trailing newline); ``None`` for the genesis line.
- ``jws`` is an Ed25519 (EdDSA) compact JWS over
  ``{iss, iat, seq, prev_sha256, record_sha256, log_id, v}`` so every line
  binds its position, predecessor, record content, owning log, and format
  version under the signing key. The JWS protected header carries
  ``kid`` -- the SHA-256 (hex) of the raw 32-byte Ed25519 public key --
  so multi-key verification (rotation) can resolve the right key.
- Line 1 is always a **genesis record**
  ``{"type": "fathom.genesis", "log_id": ..., "key_fingerprint": ...}``
  written automatically when a log is created. ``log_id`` (uuid4 hex) is
  signed into every subsequent line, so a chain copied from one log
  cannot be passed off as another (splice detection) and anchor tokens
  are bound to their log.
- The hash chain covers the full line (signature included), so deletion,
  reordering, or edits anywhere break linkage; signatures prevent an
  attacker without the key from rebuilding a consistent chain.

Tail truncation is undetectable from the file alone. Two anchors cover it:

- ``checkpoint()`` appends a signed checkpoint record whose JWS is a
  portable token pinning the chain head; mirror it out-of-band.
- ``anchor_callback`` receives an :class:`AnchorEvent` after every
  checkpoint so consumers can mirror the head hash elsewhere.

:func:`verify_chain` is the offline verifier entry point: it needs only the
log file and the public key PEM (exported beside the log on open).

Operational guarantees:

- Key creation is atomic (tmp write -> chmod 0600 -> rename).
- A malformed line (e.g. torn write) fails closed: the log refuses further
  appends; :func:`verify_chain` reports the offending line instead of
  raising.
- Reopened logs resume the chain from the existing tail (scan on open).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_public_key,
)

from fathom.attestation import AttestationService, verify_token
from fathom.errors import AttestationError

CHAIN_ISSUER = "fathom-chain"
CHECKPOINT_RECORD_TYPE = "fathom.checkpoint"
GENESIS_RECORD_TYPE = "fathom.genesis"
FORMAT_VERSION = 1

_LINE_FIELDS = {"iat", "jws", "prev_sha256", "record", "seq", "v"}
_META_RECORD_TYPES = {GENESIS_RECORD_TYPE, CHECKPOINT_RECORD_TYPE}


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def key_fingerprint(public_key: Ed25519PublicKey) -> str:
    """SHA-256 hex of the raw 32-byte Ed25519 public key (the JWS ``kid``)."""
    return _sha256_hex(public_key.public_bytes(Encoding.Raw, PublicFormat.Raw))


@dataclass(frozen=True)
class ChainedRecord:
    """One verified-shape line of a chained attestation log."""

    seq: int
    iat: int
    prev_sha256: str | None
    record: dict[str, Any]
    jws: str
    line_sha256: str
    """SHA-256 of the raw line bytes; the chain head when this is the tail."""


@dataclass(frozen=True)
class AnchorEvent:
    """Emitted to ``anchor_callback`` after a checkpoint is appended.

    Mirror ``head_sha256`` (or the portable ``checkpoint_jws`` token)
    out-of-band; feed either back to :func:`verify_chain` to detect tail
    truncation.
    """

    seq: int
    head_sha256: str
    checkpoint_jws: str


@dataclass(frozen=True)
class ChainVerification:
    """Result of verifying a chained log."""

    ok: bool
    count: int
    """Payload records verified (excludes the genesis and checkpoint records)."""
    head_seq: int | None
    head_sha256: str | None
    error: str | None = None
    error_line: int | None = None
    """1-based line number of the first invalid line, if any."""
    anchor_ok: bool | None = None
    """True/False when an anchor was supplied, ``None`` otherwise."""
    log_id: str | None = None
    """The log's identity from its genesis record. Pin it out-of-band to
    detect a whole-chain splice from another log signed by the same key."""


class _ScanState:
    """Tail state recovered by scanning an existing log."""

    def __init__(self) -> None:
        self.count = 0
        self.record_count = 0
        self.head_seq: int | None = None
        self.head_sha256: str | None = None
        self.error: str | None = None
        self.error_line: int | None = None
        self.line_hashes: list[str] = []
        self.jws_tokens: set[str] = set()
        self.log_id: str | None = None
        self.genesis_fingerprint: str | None = None


def _scan(
    path: Path,
    *,
    collect_hashes: bool = False,
    verify_key: Ed25519PublicKey | None = None,
) -> _ScanState:
    """Single-pass scan: JSON shape, version, seq monotonicity, hash linkage.

    Line 1 must be the genesis record; its ``log_id`` and key fingerprint
    are captured into the state. When *verify_key* is given, every line's
    JWS is also verified (signature, ``kid`` header, exact claims). Stops
    at the first invalid line, recording its 1-based number.
    """
    state = _ScanState()
    if not path.exists():
        return state
    expected_kid = key_fingerprint(verify_key) if verify_key is not None else None

    def _fail(error: str, lineno: int) -> _ScanState:
        state.error = error
        state.error_line = lineno
        return state

    with open(path, "rb") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip(b"\n")
            if raw[-1:] != b"\n":
                return _fail(f"malformed line {lineno}: missing newline (torn write)", lineno)
            try:
                obj = json.loads(line)
            except ValueError:
                return _fail(f"malformed line {lineno}: invalid JSON (torn write?)", lineno)
            if not isinstance(obj, dict) or not _LINE_FIELDS.issubset(obj):
                return _fail(f"malformed line {lineno}: missing chain fields", lineno)
            if obj["v"] != FORMAT_VERSION:
                return _fail(
                    f"unsupported format version {obj['v']!r} at line {lineno} "
                    f"(expected {FORMAT_VERSION})",
                    lineno,
                )
            if obj["seq"] != state.count:
                return _fail(
                    f"malformed line {lineno}: seq {obj['seq']!r}, expected {state.count}",
                    lineno,
                )
            if obj["prev_sha256"] != state.head_sha256:
                return _fail(
                    f"broken chain at line {lineno}: prev_sha256 {obj['prev_sha256']!r} "
                    f"does not match previous line hash {state.head_sha256!r}",
                    lineno,
                )
            record = obj["record"]
            if state.count == 0:
                if (
                    not isinstance(record, dict)
                    or record.get("type") != GENESIS_RECORD_TYPE
                    or not isinstance(record.get("log_id"), str)
                    or not isinstance(record.get("key_fingerprint"), str)
                ):
                    return _fail("malformed line 1: missing genesis record", 1)
                state.log_id = record["log_id"]
                state.genesis_fingerprint = record["key_fingerprint"]
                if expected_kid is not None and state.genesis_fingerprint != expected_kid:
                    return _fail("genesis key fingerprint does not match the public key", 1)
            if verify_key is not None:
                try:
                    claims = verify_token(obj["jws"], verify_key)
                except AttestationError as exc:
                    return _fail(f"invalid signature at line {lineno}: {exc}", lineno)
                kid = jwt.get_unverified_header(obj["jws"]).get("kid")
                if kid != expected_kid:
                    return _fail(
                        f"kid mismatch at line {lineno}: signed {kid!r}, "
                        f"expected {expected_kid!r}",
                        lineno,
                    )
                expected_claims = {
                    "iss": CHAIN_ISSUER,
                    "iat": obj["iat"],
                    "seq": obj["seq"],
                    "prev_sha256": obj["prev_sha256"],
                    "record_sha256": _sha256_hex(_canonical(record)),
                    "log_id": state.log_id,
                    "v": FORMAT_VERSION,
                }
                if claims != expected_claims:
                    return _fail(
                        f"signature claims mismatch at line {lineno}: "
                        f"signed {claims}, computed {expected_claims}",
                        lineno,
                    )
            state.head_sha256 = _sha256_hex(line)
            state.head_seq = state.count
            state.count += 1
            if not (isinstance(record, dict) and record.get("type") in _META_RECORD_TYPES):
                state.record_count += 1
            if collect_hashes:
                state.line_hashes.append(state.head_sha256)
                state.jws_tokens.add(obj["jws"])
    return state


def _parse_line(line: bytes) -> ChainedRecord:
    obj = json.loads(line)
    return ChainedRecord(
        seq=obj["seq"],
        iat=obj["iat"],
        prev_sha256=obj["prev_sha256"],
        record=obj["record"],
        jws=obj["jws"],
        line_sha256=_sha256_hex(line),
    )


def write_private_key_atomic(service: AttestationService, path: str | Path) -> Path:
    """Write the service's private key PEM atomically with mode 0600.

    tmp write -> chmod 0600 (at create) -> fsync -> rename. The public half
    is written beside it as ``<path>.pub.pem``. Returns the public key path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, service.private_key_pem())
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(tmp, path)
    pub_path = path.with_name(path.name + ".pub.pem")
    pub_path.write_bytes(service.public_key_pem())
    return pub_path


def load_or_create_key(path: str | Path) -> AttestationService:
    """Load an Ed25519 private key PEM, creating it atomically if missing."""
    path = Path(path)
    if path.exists():
        return AttestationService.from_private_key_bytes(path.read_bytes())
    service = AttestationService.generate_keypair()
    write_private_key_atomic(service, path)
    return service


class ChainedAttestationLog:
    """Append-only hash-chained JSONL log signed with an Ed25519 key.

    Args:
        path: JSONL log file (created if missing; resumed if present).
        service: Signing service. Its public key is exported beside the
            log as ``<path>.pub.pem`` for offline verifiers.
        checkpoint_interval: If > 0, automatically append a checkpoint
            record after every N regular appends.
        anchor_callback: Called with an :class:`AnchorEvent` after every
            checkpoint (manual or automatic). Exceptions propagate.
    """

    def __init__(
        self,
        path: str | Path,
        service: AttestationService,
        *,
        checkpoint_interval: int = 0,
        anchor_callback: Callable[[AnchorEvent], None] | None = None,
    ) -> None:
        self._path = Path(path)
        self._service = service
        self._checkpoint_interval = checkpoint_interval
        self._anchor_callback = anchor_callback
        self._appends_since_checkpoint = 0
        self._fh: IO[bytes] | None = None

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fingerprint = key_fingerprint(service.public_key)
        state = _scan(self._path)
        self._corruption = state.error
        self._next_seq = state.count
        self._head_sha256 = state.head_sha256

        self.public_key_path = self._path.with_name(self._path.name + ".pub.pem")

        if state.count == 0 and self._corruption is None:
            # New (or empty) log: mint an identity and write the genesis
            # record so every subsequent line is bound to this log.
            self._log_id = uuid.uuid4().hex
            self.public_key_path.write_bytes(service.public_key_pem())
            self._append(
                {
                    "type": GENESIS_RECORD_TYPE,
                    "log_id": self._log_id,
                    "key_fingerprint": self._fingerprint,
                }
            )
        else:
            self._log_id = state.log_id or ""
            if self._corruption is None and state.genesis_fingerprint != self._fingerprint:
                # Signing with a different key than the genesis pinned would
                # produce a log no single public key can verify: fail closed.
                self._corruption = (
                    f"signing key fingerprint {self._fingerprint} does not match "
                    f"log genesis key fingerprint {state.genesis_fingerprint}"
                )
            if state.genesis_fingerprint == self._fingerprint:
                # Re-export only when this service holds the log's pinned
                # key, so opening with the wrong key can never clobber the
                # correct public key exported beside the log.
                self.public_key_path.write_bytes(service.public_key_pem())

    @property
    def path(self) -> Path:
        return self._path

    @property
    def log_id(self) -> str:
        """The log's identity from its genesis record (empty if corrupt)."""
        return self._log_id

    @property
    def head_seq(self) -> int | None:
        return self._next_seq - 1 if self._next_seq else None

    @property
    def head_sha256(self) -> str | None:
        return self._head_sha256

    @property
    def corruption(self) -> str | None:
        """Description of detected corruption, if any. Appends fail-closed."""
        return self._corruption

    def append(self, record: dict[str, Any]) -> ChainedRecord:
        """Sign and append one record; returns the written line's metadata.

        Raises AttestationError if the log is corrupt (fail closed).
        """
        chained = self._append(record)
        self._appends_since_checkpoint += 1
        if self._checkpoint_interval > 0 and (
            self._appends_since_checkpoint >= self._checkpoint_interval
        ):
            self.checkpoint()
        return chained

    def checkpoint(self) -> ChainedRecord:
        """Append a signed checkpoint record pinning the current head.

        Fires ``anchor_callback`` with the new head (the checkpoint line's
        own hash) and the checkpoint's portable JWS token.
        """
        chained = self._append(
            {
                "type": CHECKPOINT_RECORD_TYPE,
                "head_seq": self.head_seq,
                "head_sha256": self._head_sha256,
            }
        )
        self._appends_since_checkpoint = 0
        if self._anchor_callback is not None:
            self._anchor_callback(
                AnchorEvent(
                    seq=chained.seq,
                    head_sha256=chained.line_sha256,
                    checkpoint_jws=chained.jws,
                )
            )
        return chained

    def _append(self, record: dict[str, Any]) -> ChainedRecord:
        if self._corruption is not None:
            raise AttestationError(
                f"chained log {self._path} is corrupt; refusing append: {self._corruption}",
                operation="append",
            )
        iat = int(time.time())
        seq = self._next_seq
        prev = self._head_sha256
        claims = {
            "iss": CHAIN_ISSUER,
            "iat": iat,
            "seq": seq,
            "prev_sha256": prev,
            "record_sha256": _sha256_hex(_canonical(record)),
            "log_id": self._log_id,
            "v": FORMAT_VERSION,
        }
        token = self._service.sign_claims(claims, headers={"kid": self._fingerprint})
        line = _canonical(
            {
                "iat": iat,
                "jws": token,
                "prev_sha256": prev,
                "record": record,
                "seq": seq,
                "v": FORMAT_VERSION,
            }
        )
        if self._fh is None:
            fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            self._fh = os.fdopen(fd, "ab")
        self._fh.write(line + b"\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._next_seq = seq + 1
        self._head_sha256 = _sha256_hex(line)
        return ChainedRecord(
            seq=seq,
            iat=iat,
            prev_sha256=prev,
            record=record,
            jws=token,
            line_sha256=self._head_sha256,
        )

    def records(self) -> list[ChainedRecord]:
        """All parseable records. Raises on a malformed line.

        Chain/signature validity is the job of :meth:`verify`.
        """
        result: list[ChainedRecord] = []
        if not self._path.exists():
            return result
        with open(self._path, "rb") as fh:
            for lineno, raw in enumerate(fh, start=1):
                try:
                    result.append(_parse_line(raw.rstrip(b"\n")))
                except (ValueError, KeyError) as exc:
                    raise AttestationError(
                        f"malformed line {lineno} in {self._path}", operation="records"
                    ) from exc
        return result

    def find_record(self, seq: int) -> ChainedRecord | None:
        """Return the record at *seq*, or None."""
        for rec in self.records():
            if rec.seq == seq:
                return rec
        return None

    def verify(self) -> ChainVerification:
        """Full offline verification using this log's own public key."""
        return verify_chain(self._path, self._service.public_key)

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> ChainedAttestationLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _load_public_key(public_key: Ed25519PublicKey | bytes | str | Path) -> Ed25519PublicKey:
    if isinstance(public_key, Ed25519PublicKey):
        return public_key
    pem = Path(public_key).read_bytes() if isinstance(public_key, str | Path) else public_key
    key = load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise AttestationError("Public key is not Ed25519", operation="verify")
    return key


def verify_chain(
    path: str | Path,
    public_key: Ed25519PublicKey | bytes | str | Path,
    *,
    expected_head: str | None = None,
    anchor_token: str | None = None,
) -> ChainVerification:
    """Offline verifier: structure, hash linkage, and every JWS signature.

    Args:
        path: Chained JSONL log file.
        public_key: Ed25519 public key (object, PEM bytes, or PEM path).
        expected_head: Out-of-band mirrored line hash. Verification fails
            (``anchor_ok=False``) if it is not one of the log's line
            hashes — i.e. the tail containing it was truncated.
        anchor_token: A checkpoint JWS previously emitted via
            :class:`AnchorEvent`. The checkpoint line carrying this exact
            token must still be present in the log, so truncating the
            checkpoint line itself is detected.

    All supplied anchors must hold. Never raises on log content; malformed
    input is reported via ``error``/``error_line``.
    """
    log_path = Path(path)
    key = _load_public_key(public_key)
    state = _scan(log_path, collect_hashes=True, verify_key=key)

    if state.error is not None:
        return ChainVerification(
            ok=False,
            count=state.record_count,
            head_seq=state.head_seq,
            head_sha256=state.head_sha256,
            error=state.error,
            error_line=state.error_line,
            anchor_ok=None,
            log_id=state.log_id,
        )

    anchor_supplied = anchor_token is not None or expected_head is not None
    anchor_error: str | None = None
    if anchor_token is not None:
        try:
            verify_token(anchor_token, key)
        except AttestationError as exc:
            anchor_error = f"anchor token verification failed: {exc}"
        else:
            if anchor_token not in state.jws_tokens:
                anchor_error = "anchor checkpoint line not present in log — tail truncated?"
    if (
        anchor_error is None
        and expected_head is not None
        and (expected_head not in state.line_hashes)
    ):
        anchor_error = f"expected head {expected_head!r} not present in log — tail truncated?"

    return ChainVerification(
        ok=anchor_error is None,
        count=state.record_count,
        head_seq=state.head_seq,
        head_sha256=state.head_sha256,
        error=anchor_error,
        error_line=None,
        anchor_ok=anchor_error is None if anchor_supplied else None,
        log_id=state.log_id,
    )
