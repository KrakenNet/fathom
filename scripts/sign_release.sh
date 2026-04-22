#!/usr/bin/env bash
#
# sign_release.sh — Sign and verify release artifacts with minisign.
#
# Usage: sign_release.sh <secret_key_path> <public_key_path>
#
# Iterates over dist/*.whl and dist/*.tar.gz, signs each artifact with the
# provided minisign secret key, then immediately verifies the signature
# against the provided public key. Exits non-zero on the first failure.
#
# Signatures are written as <artifact>.minisig (minisign's default extension,
# matching the broader Ed25519 ecosystem — libsodium, zig, minisign itself).
# Do NOT pass `-x` to force a `.sig` extension: `.sig` conventionally denotes
# GPG/OpenPGP signatures, and `fathom verify-artifact` defaults to `.minisig`.
#
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <secret_key_path> <public_key_path>" >&2
    exit 2
fi

secret_key="$1"
public_key="$2"

if [[ ! -f "$secret_key" ]]; then
    echo "error: secret key not found: $secret_key" >&2
    exit 1
fi

if [[ ! -f "$public_key" ]]; then
    echo "error: public key not found: $public_key" >&2
    exit 1
fi

if ! command -v minisign >/dev/null 2>&1; then
    echo "error: minisign is not installed or not on PATH" >&2
    exit 1
fi

shopt -s nullglob
artifacts=(dist/*.whl dist/*.tar.gz)
shopt -u nullglob

if [[ ${#artifacts[@]} -eq 0 ]]; then
    echo "error: no artifacts found in dist/ (looked for *.whl and *.tar.gz)" >&2
    exit 1
fi

rc=0
for f in "${artifacts[@]}"; do
    echo "Signing: $f"
    if ! minisign -Sm "$f" -s "$secret_key"; then
        echo "error: failed to sign $f" >&2
        rc=1
        break
    fi

    echo "Verifying: $f"
    if ! minisign -Vm "$f" -p "$public_key"; then
        echo "error: failed to verify $f" >&2
        rc=1
        break
    fi
done

exit "$rc"
