#!/usr/bin/env bash
# prepare-commit-msg hook (installed by `make init` via pre-commit): append a
# DCO "Signed-off-by" trailer matching the commit author, so your own commits
# never trip the DCO check — even if your local git email isn't the one GitHub
# maps to org membership. Idempotent; a no-op if a matching sign-off is present.
set -euo pipefail

msg_file="${1:?commit message file path expected}"

name="$(git config user.name || true)"
email="$(git config user.email || true)"
if [ -z "$name" ] || [ -z "$email" ]; then
  exit 0
fi

# Already signed off by this author? Leave it alone.
if grep -qiF "Signed-off-by: ${email}" "$msg_file" 2>/dev/null; then
  exit 0
fi

git interpret-trailers --in-place --trailer "Signed-off-by: ${name} <${email}>" "$msg_file"
