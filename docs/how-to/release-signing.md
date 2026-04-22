---
title: Verifying release signatures
summary: Install minisign, verify a Fathom wheel or sdist, and understand the custody + rotation policy for the release key.
audience: [app-developers, operators]
diataxis: how-to
status: stable
last_verified: 2026-04-22
sources:
  - scripts/sign_release.sh
  - src/fathom/cli.py
  - src/fathom/_data/release_pubkey.minisign
  - docs/reference/release-signing-pubkey.minisig
  - .github/workflows/pypi-publish.yml
---

# Verifying release signatures

Every Fathom release artifact published to PyPI and attached to a GitHub
Release is signed with [minisign](https://jedisct1.github.io/minisign/)
(detached Ed25519). This how-to shows you how to install minisign,
verify a downloaded wheel or sdist, and understand the custody,
rotation, and revocation policy for the signing key.

## What is signed, and how

- **Artifacts**: every `fathom_rules-*.whl` and `fathom_rules-*.tar.gz`.
- **Algorithm**: Ed25519 via minisign's standard `.minisig` format —
  detached signature, one file per artifact, binary-safe.
- **Where signatures appear**:
  - Alongside each wheel / sdist as `<artifact>.minisig` on the GitHub
    Release page.
  - In the `dist/` directory produced by `scripts/sign_release.sh`
    during the `pypi-publish` workflow.
- **Pubkey**: published at
  [`docs/reference/release-signing-pubkey.minisig`](../reference/release-signing-pubkey.minisig)
  and embedded in the Fathom wheel at
  `fathom/_data/release_pubkey.minisign` so that `fathom
  verify-artifact` works offline.

A `.minisig` file is a small text blob containing an Ed25519 signature
plus a trusted comment. It is not a bundle — the artifact and its
`.minisig` travel together but remain separate files.

## Installing minisign

Pick the instruction that matches your platform. All of them give you a
`minisign` binary on your `PATH`.

- **macOS** (Homebrew):

  ```shell
  brew install minisign
  ```

- **Linux** (Debian, Ubuntu):

  ```shell
  sudo apt install minisign
  ```

  On Fedora / RHEL: `sudo dnf install minisign`. On Arch: `sudo pacman
  -S minisign`.

- **Windows**: download a pre-built binary from the upstream release
  page at
  [`https://github.com/jedisct1/minisign/releases`](https://github.com/jedisct1/minisign/releases)
  and place it somewhere on `PATH`. Alternatively, use WSL and follow
  the Linux instructions above.

Confirm the install:

```shell
minisign -v
```

## Verifying a downloaded artifact

You have two equivalent paths. Use the first if you already have Fathom
installed; use the second if you only have `minisign` and the public
key file.

### Option A — `fathom verify-artifact` (embedded pubkey)

The CLI carries the release pubkey inside the wheel, so once you have
any recent Fathom version installed you can verify later downloads
offline:

```shell
fathom verify-artifact fathom_rules-1.2.0-py3-none-any.whl
```

If `<artifact>.minisig` lives next to the artifact, the CLI picks it up
automatically. Override either side with `--sig <path>` or `--pubkey
<path>` when auditing a specific file. Exit code `0` means the
signature verified; non-zero means the verification failed or the
inputs were malformed — re-download the artifact before trusting it.

### Option B — raw `minisign`

No Fathom install needed. Download the artifact, its `.minisig`, and
the pubkey file from
[`docs/reference/release-signing-pubkey.minisig`](../reference/release-signing-pubkey.minisig),
then:

```shell
minisign -Vm fathom_rules-1.2.0-py3-none-any.whl \
         -p release-signing-pubkey.minisig
```

`minisign` looks for `<artifact>.minisig` by default. Pass `-x <path>`
to point at a signature that lives elsewhere. A `Signature and comment
signature verified` line means the artifact is authentic.

The pubkey's first line is also pasted into every GitHub Release body,
so you can cross-check the key you fetched from the repository against
the one on the release page.

## M-of-N custody policy

The release private key is never held in a single place. Two named
custodians each hold one half of the operational state, and **both
must agree out-of-band before a release tag is pushed**.

- `MINISIGN_KEY_PRIMARY` — GitHub Actions secret, held by custodian A.
  Loaded into `scripts/sign_release.sh` during the `pypi-publish`
  workflow.
- `MINISIGN_KEY_SECONDARY` — offline backup of the same keypair, held
  by custodian B. Used only for rotation, recovery, and the custody
  handshake described below.
- Both custodians confirm the target tag, commit SHA, and intended
  version via a signed email or Signal message before custodian A
  authorises the tag push that triggers signing. No single custodian
  can ship a release on their own, because the handshake is the
  authorisation step — not merely a courtesy.

The policy exists so that a compromise of a single machine, inbox, or
GitHub token cannot produce a valid Fathom release.

## Rotation cadence

- **Scheduled**: rotate the keypair annually. Track the next rotation
  date in the repository's release runbook.
- **On compromise**: rotate immediately if either custodian suspects
  their copy of the key has been exposed, if a custodian's workstation
  is lost or stolen, or if `MINISIGN_KEY_PRIMARY` is ever printed to
  logs.

### Rotation procedure

1. Both custodians meet out-of-band and generate a new keypair with
   `minisign -G`.
2. Update `docs/reference/release-signing-pubkey.minisig` **and**
   `src/fathom/_data/release_pubkey.minisign` with the new public key,
   in a single commit.
3. Distribute the new private key: update the `MINISIGN_KEY_PRIMARY`
   GitHub Actions secret; custodian B stores the new offline backup.
4. Publish a dedicated release note flagging the rotation, including
   the new key ID and the date from which signatures use it.
5. Retire the previous private-key material (securely erase offline
   copies, delete the old GitHub secret).

## Revocation

minisign has no CRL or OCSP equivalent — trust in a key is defined by
the key file you hold. To revoke a compromised key:

1. Follow the rotation procedure above, treating it as an emergency.
2. Issue a release note that explicitly invalidates every artifact
   signed by the previous key and lists which published versions are
   affected.
3. Recommend that users re-fetch and re-verify any still-in-use
   artifacts against the new pubkey before continuing to rely on
   them.

Users who pin the pubkey (for example by vendoring
`release-signing-pubkey.minisig`) should update their pinned copy from
the new release. The embedded pubkey in `fathom/_data/` updates
automatically once users install a release signed under the new key.
