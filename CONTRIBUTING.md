# Contributing to Fathom

Thanks for your interest in contributing to Fathom! This guide will help you get started.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Development Setup

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/KrakenNet/fathom.git
cd fathom
uv sync --all-extras
```

`--all-extras` is required: the full test suite and type-check import the optional integration dependencies (FastAPI, MCP, cryptography, Prometheus, etc.). A plain `uv sync` installs only the dev group, and `uv run pytest` then fails to collect those tests.

## Running Checks

```bash
uv run pytest                   # run tests
uv run ruff check src/ tests/   # lint
uv run ruff format src/ tests/  # format
uv run mypy src/                # type check
uv run pytest --cov=fathom      # coverage report
uv run mkdocs serve             # docs preview
```

All of these run automatically in CI on every pull request.

## How to Contribute

### Finding something to work on

Browse open issues by label:

- **`good first issue`** — start here; scoped tasks that need no deep codebase knowledge.
- **`help wanted`** — issues where we'd welcome a contributor.
- **`needs-decision` / `needs-design`** — approach isn't settled yet; please don't open a PR. Comment with your thoughts instead.

For anything non-trivial, comment on the issue to claim it before you start, so we don't duplicate effort.

### Bug Reports

Use the [bug report template](https://github.com/KrakenNet/fathom/issues/new?template=bug_report.yml). Include:

- Fathom version (`python -c "import fathom; print(fathom.__version__)"`)
- Python version (`python --version`)
- Operating system
- Minimal reproduction steps

### Feature Requests

Use the [feature request template](https://github.com/KrakenNet/fathom/issues/new?template=feature_request.yml). Describe the use case, not just the solution.

### Pull Requests

1. Fork the repo and create a branch from `main`
2. Write tests for new functionality
3. Ensure all checks pass (see "Running Checks" above)
4. Update documentation if you're changing public API
5. Open a pull request

### Changing a public surface

`VERSIONING.md` lists what this project promises to keep working, and
`tests/test_public_surface.py` fails when that list and `fathom.__all__` drift
apart. Adding a name to `__all__` is a commitment, not a convenience — update
`VERSIONING.md` in the same change, and say in the changelog what a caller has
to do if you changed or removed one.

### Documentation that cites your code

Every page under `docs/` lists the files it describes in its frontmatter
`sources:`, with a `last_verified:` date. If your branch edits a file some page
cites, the required `docs` job fails until that page is re-verified **in the
same branch**: read the claims it makes about your file, correct the ones your
change made false, and set `last_verified:` to today.

```bash
uv run python scripts/check_doc_sources.py --changed-vs origin/main  # what CI gates
uv run python scripts/check_doc_sources.py                           # everything stale, anywhere
```

Only the sources your branch touched are gated. The whole-repo sweep is a
warning in the advisory `docs-quality` job — it is a maintenance list, not
your problem to clear.

Line numbers in a citation (`src/fathom/engine.py` line 1179) move when the
file does; re-check them rather than only bumping the date.

### Sign-off (DCO)

Every commit must be signed off, certifying you wrote the change (or have the right to submit it) under the project license. Add the sign-off line by committing with `-s`:

```bash
git commit -s -m "your message"
```

Forgot to sign off? You don't need to rewrite history — when the `DCO` check fails it comments the exact one-line command to push a remediation commit; just run it and push. (`git rebase --signoff origin/main` also works.)

## Releases

Releases are cut by release-please: merging to `main` maintains a release PR
that bumps the version everywhere it appears — `pyproject.toml`,
`src/fathom/__init__.py`, and the version lines in `README.md` and
`docs/index.md` — and tags it `vX.Y.Z`, which publishes to PyPI, GHCR and the
docs site.

The TypeScript SDK (`packages/fathom-ts/`) is a separate release-please
component on its own version line. Commits touching it bump
`packages/fathom-ts/package.json` and tag `fathom-ts-vX.Y.Z`; only that tag
runs `npm-publish.yml`. An engine release never publishes the SDK.

`CHANGELOG.md` is curated during the cycle: user-facing changes go under
`## [Unreleased]` in the PR that makes them. On the release PR,
`release-please-docs.yml` runs `scripts/promote_changelog.py`, which renames
that section to `## [X.Y.Z] - date`, and regenerates the docs artifacts
(`docs/changelog.json` included). Do not hand-write the release heading: a
second `## [X.Y.Z]` would duplicate the promoted one.
`scripts/check_version_sync.py` (the `lint` job) fails when the version in
`pyproject.toml` has no matching heading in `CHANGELOG.md`.

The generated notes on the GitHub release carry the full commit list; the
changelog entry is the curated summary of what it means for a user.

### Cutting 1.0.0

`bump-minor-pre-major` sends a breaking change to the next `0.x` minor, so
release-please never proposes 1.0.0 by itself. To cut it, land one PR on
`main` that:

1. Deletes the "Pre-1.0 semantics" section of `VERSIONING.md` and the pre-1.0
   halves of "Deprecation" and "Supported versions" (each says which half
   applies from 1.0), and drops "Fathom is pre-1.0" from its intro.
2. Replaces "Fathom is pre-1.0" in the README `## Stability` section and in
   the `## Stability` section of `docs/index.md` (`docs/llms-full.txt` is
   regenerated from it by `make docs-gen`).
3. Rewrites the "pre-1.0, upgrading to the current minor" sentence under
   "Supported versions" in `SECURITY.md` to match the 1.0 half of
   `VERSIONING.md`'s "Supported versions".
4. Changes the `pyproject.toml` classifier to
   `Development Status :: 5 - Production/Stable`.
5. Carries this footer in its squash-merge commit message — GitHub builds that
   message from the PR, so check the footer is still there before you click
   merge:

   ```
   Release-As: 1.0.0
   ```

The footer must sit on a commit that changes only engine files. Do not use an
empty commit: release-please hands a commit with no files to every component,
and the TypeScript SDK would be released as 1.0.0 with it. release-please then
opens a 1.0.0 release PR, and `promote_changelog.py` turns `## [Unreleased]`
into the `## [1.0.0]` entry as for any release. `bump-minor-pre-major` has no effect from 1.0 on and can stay.

## Project Structure

```
src/fathom/              Core library
src/fathom/integrations/ FastAPI, gRPC, MCP, LangChain, CrewAI, etc.
src/fathom/rule_packs/   OWASP, NIST 800-53, HIPAA, CMMC, SSVC compliance packs
protos/                  gRPC protocol definitions (fathom.proto)
scripts/                 Doc generators, schema/OpenAPI exporters, release tooling
tests/                   pytest test suite (1695 tests)
docs/                    MkDocs Material documentation
examples/                Progressive example projects (01-05)
packages/                fathom-studio (Policy Studio), Go and TypeScript SDKs, React editor
```

## Code Style

- Ruff for linting and formatting (config in `pyproject.toml`)
- mypy in strict mode for type checking
- Type annotations on all public APIs
- Docstrings on all public classes and functions

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
