# Fathom docs orchestration

.PHONY: init docs-gen docs-gen-foreign docs-build docs-serve docs-lint docs-clean docs-check

# One-command dev setup: install deps + pre-commit hooks (incl. the
# prepare-commit-msg stage that auto-adds the DCO sign-off).
init:
	uv sync
	uv run pre-commit install --hook-type pre-commit --hook-type prepare-commit-msg
	chmod +x scripts/dco_signoff.sh

# Generators - native Python, run in every environment.
docs-gen:
	uv run python scripts/export_openapi.py
	uv run python scripts/export_json_schemas.py
	uv run python scripts/generate_cli_docs.py
	uv run python scripts/generate_rule_pack_docs.py
	uv run python scripts/generate_mcp_manifest.py
	uv run python scripts/changelog_to_json.py
	uv run python scripts/generate_llms_txt.py
	uv run python scripts/generate_python_sdk_docs.py

# Generators that require foreign toolchains (Go, Node, protoc). Each line
# skips ONLY when its toolchain is genuinely absent; when the toolchain IS
# present, a generator failure propagates (nonzero exit) instead of being
# swallowed as a "skip". The old `... || echo skip` masked real failures,
# so a dev could commit stale docs that CI (with the toolchain) then
# regenerates differently — a false drift-gate failure on an unrelated PR.
docs-gen-foreign:
	@if command -v npx >/dev/null 2>&1; then uv run python scripts/generate_postman_collection.py; else echo "skip: postman (npx missing)"; fi
	@if command -v protoc >/dev/null 2>&1 && command -v protoc-gen-doc >/dev/null 2>&1; then uv run python scripts/generate_grpc_docs.py; else echo "skip: grpc (protoc/protoc-gen-doc missing)"; fi
	@if command -v go >/dev/null 2>&1; then uv run python scripts/generate_go_sdk_docs.py; else echo "skip: go-sdk (go missing)"; fi
	@if command -v pnpm >/dev/null 2>&1 || command -v npm >/dev/null 2>&1; then uv run python scripts/generate_ts_sdk_docs.py; else echo "skip: ts-sdk (pnpm/npm missing)"; fi

# Strict build (fails on any warning)
docs-build: docs-gen docs-gen-foreign
	uv run mkdocs build --strict

# Local preview (no strict mode for iteration speed)
docs-serve: docs-gen docs-gen-foreign
	uv run mkdocs serve

# Lint hand-written pages (excludes generated reference)
docs-lint:
	uv run markdownlint-cli2 "docs/**/*.md" "#docs/reference/**" "#docs/llms*.txt" "#docs/superpowers/**" "#docs/_prompts/**"
	uv run codespell docs/ --skip "docs/reference/*,docs/llms*.txt,docs/changelog.json,docs/superpowers/*"

# All-in-one verification
docs-check: docs-build docs-lint
	uv run python scripts/check_version_sync.py
	uv run python scripts/check_docstrings.py
	uv run python scripts/check_frontmatter.py

docs-clean:
	rm -rf site/ docs/reference/python-sdk/
