#!/usr/bin/env bash
# Regenerate TypeScript types from the Fathom OpenAPI spec using Hey API.
#
# Prerequisites:
#   npm install (to install @hey-api/openapi-ts)
#
# Usage:
#   npm run generate
#   # or directly: bash scripts/generate.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# OPENAPI_SPEC must be generated first (e.g., from FastAPI's /openapi.json endpoint).
OPENAPI_SPEC="${OPENAPI_SPEC:-../../openapi.json}"

OUT_DIR="$PROJECT_DIR/src/generated"

echo "Generating TypeScript types from OpenAPI spec: $OPENAPI_SPEC"
npx @hey-api/openapi-ts \
  -i "$OPENAPI_SPEC" \
  -o "$OUT_DIR" \
  -c fetch

echo "Done. Generated types in $OUT_DIR"
