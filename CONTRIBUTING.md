# Contributing to Fathom

Thanks for your interest in contributing to Fathom! This guide will help you get started.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Development Setup

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/)

```bash
git clone https://github.com/KrakenNet/fathom.git
cd fathom
uv sync
```

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

## Project Structure

```
src/fathom/              Core library
src/fathom/integrations/ FastAPI, gRPC, MCP, LangChain, CrewAI, etc.
src/fathom/rule_packs/   OWASP, NIST 800-53, HIPAA, CMMC compliance packs
tests/                   pytest test suite (1361+ tests)
docs/                    MkDocs Material documentation
examples/                Progressive example projects (01-05)
packages/                Go, TypeScript SDKs, React editor
```

## Code Style

- Ruff for linting and formatting (config in `pyproject.toml`)
- mypy in strict mode for type checking
- Type annotations on all public APIs
- Docstrings on all public classes and functions

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
