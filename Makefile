# Fathom docs orchestration

.PHONY: docs-gen docs-gen-foreign docs-build docs-serve docs-lint docs-clean docs-check

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

# Generators that require foreign toolchains (Go, Node, protoc). Run in CI
# unconditionally; locally they skip cleanly if the toolchain is missing.
docs-gen-foreign:
	uv run python scripts/generate_postman_collection.py || echo "skip: postman (npx missing)"
	uv run python scripts/generate_grpc_docs.py || echo "skip: grpc (protoc missing)"
	uv run python scripts/generate_go_sdk_docs.py || echo "skip: go-sdk (go missing)"
	uv run python scripts/generate_ts_sdk_docs.py || echo "skip: ts-sdk (pnpm/npm missing)"

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
