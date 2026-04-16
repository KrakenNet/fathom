#!/usr/bin/env bash
# Publish a new release of fathom-rules to PyPI.
#
# Usage:
#   scripts/publish.sh <version>              # publish to real PyPI
#   scripts/publish.sh <version> --test       # publish to TestPyPI
#   scripts/publish.sh <version> --dry-run    # build + verify, skip upload
#
# Example: scripts/publish.sh 0.3.0
#
# Required env vars:
#   UV_PUBLISH_TOKEN           PyPI API token (pypi-*)           [real PyPI]
#   UV_PUBLISH_TOKEN_TEST      TestPyPI API token (pypi-*)       [--test]
#
# Run from the repo root. Requires: uv, git, jq.

set -euo pipefail

# ---- arg parsing ------------------------------------------------------------
VERSION="${1:-}"
MODE="real"
for arg in "${@:2}"; do
    case "$arg" in
        --test)    MODE="test" ;;
        --dry-run) MODE="dry-run" ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    echo "usage: $0 <version> [--test|--dry-run]" >&2
    exit 2
fi

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([ab][0-9]+|rc[0-9]+)?$ ]]; then
    echo "error: version '$VERSION' is not valid semver (X.Y.Z or X.Y.ZrcN)" >&2
    exit 2
fi

say()  { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

# ---- 1. verify working tree -------------------------------------------------
say "Verifying working tree"
if [[ -n "$(git status --porcelain)" ]]; then
    git status --short
    die "working tree is dirty — commit or stash first"
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "master" && "$BRANCH" != "main" ]]; then
    warn "current branch is '$BRANCH' — releases usually go from master/main"
    read -rp "continue anyway? [y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || die "aborted"
fi

git fetch --tags --quiet
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
    die "tag v$VERSION already exists — bump the version or delete the tag"
fi

# ---- 2. verify versions are in sync ----------------------------------------
say "Verifying version strings"
PYPROJECT_VER="$(grep -E '^version\s*=' pyproject.toml | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
INIT_VER="$(grep -E '^__version__\s*=' src/fathom/__init__.py | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"

[[ "$PYPROJECT_VER" == "$VERSION" ]] \
    || die "pyproject.toml version is $PYPROJECT_VER, expected $VERSION"
[[ "$INIT_VER" == "$VERSION" ]] \
    || die "src/fathom/__init__.py __version__ is $INIT_VER, expected $VERSION"

if ! grep -qE "^## $VERSION" CHANGELOG.md; then
    die "CHANGELOG.md is missing a '## $VERSION' heading"
fi

# ---- 3. quality gates -------------------------------------------------------
say "Running ruff"
uv run ruff check .

say "Running mypy"
uv run mypy src

say "Running pytest"
uv run pytest

# ---- 4. build ---------------------------------------------------------------
say "Cleaning old build artifacts"
rm -rf dist/ build/ src/*.egg-info

say "Building sdist + wheel"
uv build

WHEEL="dist/fathom_rules-${VERSION}-py3-none-any.whl"
SDIST="dist/fathom_rules-${VERSION}.tar.gz"
[[ -f "$WHEEL" ]] || die "expected $WHEEL, not found"
[[ -f "$SDIST" ]] || die "expected $SDIST, not found"

# ---- 5. smoke test the wheel ------------------------------------------------
say "Smoke-testing the built wheel in an isolated env"
ACTUAL=$(uv run --isolated --with "$WHEEL" --no-project \
    python -c "import fathom; print(fathom.__version__)")
[[ "$ACTUAL" == "$VERSION" ]] \
    || die "wheel reports version '$ACTUAL', expected '$VERSION'"
echo "  wheel reports: $ACTUAL"

# ---- 6. upload --------------------------------------------------------------
case "$MODE" in
    dry-run)
        say "Dry-run complete — artifacts in dist/, nothing uploaded"
        exit 0
        ;;
    test)
        [[ -n "${UV_PUBLISH_TOKEN_TEST:-}" ]] \
            || die "UV_PUBLISH_TOKEN_TEST not set"
        say "Uploading to TestPyPI"
        uv publish \
            --publish-url https://test.pypi.org/legacy/ \
            --token "$UV_PUBLISH_TOKEN_TEST" \
            "$WHEEL" "$SDIST"
        echo
        echo "Installed-from-TestPyPI smoke test:"
        echo "  uv run --isolated --no-project \\"
        echo "      --index https://test.pypi.org/simple/ \\"
        echo "      --index-strategy unsafe-best-match \\"
        echo "      --with fathom-rules==$VERSION \\"
        echo "      python -c 'import fathom; print(fathom.__version__)'"
        exit 0
        ;;
    real)
        [[ -n "${UV_PUBLISH_TOKEN:-}" ]] \
            || die "UV_PUBLISH_TOKEN not set"
        say "Uploading to PyPI"
        uv publish --token "$UV_PUBLISH_TOKEN" "$WHEEL" "$SDIST"
        ;;
esac

# ---- 7. tag & push (real-PyPI path only) -----------------------------------
say "Tagging v$VERSION"
git tag -a "v$VERSION" -m "Release $VERSION"
git push origin "v$VERSION"

say "Published fathom-rules==$VERSION"
echo "  PyPI:   https://pypi.org/project/fathom-rules/$VERSION/"
echo "  Tag:    v$VERSION"
