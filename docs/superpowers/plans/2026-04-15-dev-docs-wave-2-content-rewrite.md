# Dev Docs Wave 2 — Content Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite Fathom's narrative documentation from scratch against current source, restructure into Diátaxis-inspired quadrants (Tutorials / How-to / Reference / Concepts), and retire legacy pages — with a frontmatter drift gate and tutorial snippet verifier enforcing that docs and code stay in sync.

**Architecture:** Two new CI gates — `scripts/check_doc_sources.py` (compares `last_verified` frontmatter against `git log -1` of each listed source file) and `scripts/verify_tutorial_snippets.py` (extracts fenced code blocks from tutorials and runs them through the compiler / Python subprocess). Content tasks are parallelizable because each page is self-contained under the Diátaxis partition. Legacy retirement is the final task, atomic with markdownlint-exclusion cleanup.

**Tech Stack:** Python 3.14 + uv, pytest, MkDocs Material + mike + mkdocstrings + redirects, PyYAML, GitHub Actions.

**Reference:** See spec at `docs/superpowers/specs/2026-04-15-dev-docs-wave-2-content-rewrite-design.md`.

---

## Preliminary: Vocabulary alignment

The existing `scripts/check_frontmatter.py` already defines:

- `VALID_DIATAXIS = {"tutorial", "how-to", "reference", "explanation", "landing"}`
- `VALID_STATUS = {"stable", "draft", "experimental"}`
- `VALID_AUDIENCES = {"app-developers", "rule-authors", "contributors"}`

**Frontmatter values MUST conform to these sets.** The Concepts *nav tab label* is "Concepts" (user-facing), but the frontmatter *field value* is `diataxis: explanation`. Audiences use the existing three values only; do not invent new ones.

All pages authored in this plan use these values verbatim.

---

## File Structure

### New scripts (created in Phase 1)

- `scripts/check_doc_sources.py` — drift gate. Iterates every `docs/**/*.md` with a `sources:` list, compares last-commit of each source against the page's `last_verified`.
- `scripts/verify_tutorial_snippets.py` — tutorial snippet runner. Extracts fenced blocks from `docs/tutorials/*.md`, feeds YAML to the compiler and Python to a subprocess.
- `tests/test_scripts/test_check_doc_sources.py` — unit tests for the drift gate.
- `tests/test_scripts/test_verify_tutorial_snippets.py` — unit tests for the snippet runner.

### Modified scripts

- `scripts/check_frontmatter.py` — extend to require `sources:` on pages whose `diataxis` is `tutorial`, `how-to`, or `explanation`, and on `reference` pages without `generated: true`.
- `.github/workflows/docs.yml` — add two new CI steps for the gates; remove four legacy-path markdownlint exclusions during Phase 3.
- `mkdocs.yml` — swap Architecture + YAML Reference top-level tabs for Tutorials / How-to / Concepts; extend `redirect_maps` for retired URLs.

### New content pages (Phase 2)

- `docs/tutorials/index.md`, `hello-world.md`, `modules-and-salience.md`, `working-memory.md` — 3 progressive tutorials plus landing.
- `docs/how-to/index.md`, `writing-rules.md`, `fastapi.md`, `cli.md`, `register-function.md`, `load-rule-pack.md`, `embed-sdk.md` — 6 how-tos plus landing.
- `docs/concepts/index.md`, `primitives.md`, `runtime.md`, `yaml-compilation.md`, `audit-attestation.md`, `not-in-v1.md` — 5 concepts plus landing.
- `docs/reference/yaml/template.md`, `rule.md`, `module.md`, `function.md`, `fact.md` — 5 per-construct pages.
- `docs/reference/planned-integrations.md` — single status page for LangChain, CrewAI, OpenAI Agent SDK, Google ADK.

### Rewritten existing pages (Phase 2)

- `docs/_index.md` — Home, add `sources:` frontmatter, update content to match current state.
- `docs/getting-started.md` — rewrite against current install + entry points.
- `docs/reference/yaml/index.md` — add `sources:` pointing to the schema export script + models.

### Deleted in Phase 3

- `docs/core/*` (12 files), `docs/integrations/*` (12 files), `docs/yaml/*` (5 files), `docs/integration.md`, `docs/writing-rules.md` (moved to `docs/how-to/writing-rules.md`), `docs/advanced/**` (unless a specific page is preserved via in-wave rewrite).

---

# Phase 1 — Infrastructure

## Task 1: Drift gate script + tests

**Files:**
- Create: `scripts/check_doc_sources.py`
- Create: `tests/test_scripts/test_check_doc_sources.py`

- [ ] **Step 1: Write failing test for "clean repo passes"**

```python
# tests/test_scripts/test_check_doc_sources.py
import subprocess
import sys
from pathlib import Path


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path.cwd() / "scripts" / "check_doc_sources.py"), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)


def _commit(root: Path, msg: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=root, check=True)


PAGE_TEMPLATE = """---
title: Example
summary: x
audience: [app-developers]
diataxis: explanation
status: stable
last_verified: {verified}
sources:
  - src/module.py
---

body
"""


def test_clean_repo_exits_zero(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("x = 1\n")
    _commit(tmp_path, "src")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        PAGE_TEMPLATE.format(verified="2099-01-01")
    )
    _commit(tmp_path, "docs")
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr + result.stdout
```

- [ ] **Step 2: Run test to verify it fails (script doesn't exist)**

Run: `uv run pytest tests/test_scripts/test_check_doc_sources.py -v`
Expected: FAIL — `scripts/check_doc_sources.py` not found.

- [ ] **Step 3: Implement the script**

```python
# scripts/check_doc_sources.py
"""Drift gate: fail if any page's cited sources were modified after
the page's last_verified date, or if a cited source file is missing.

Exit codes: 0 clean; 1 drift or missing source; 2 misconfig.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml


def _read_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError(f"{path}: unterminated frontmatter")
    return yaml.safe_load(text[3:end]) or {}


def _last_commit_date(source: Path, repo: Path) -> date | None:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", str(source.relative_to(repo))],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return datetime.fromisoformat(result.stdout.strip()).date()


def _check_page(page: Path, repo: Path) -> list[str]:
    try:
        fm = _read_frontmatter(page)
    except ValueError as exc:
        return [f"{page}: {exc}"]
    sources = fm.get("sources")
    if not sources:
        return []
    verified = fm.get("last_verified")
    if isinstance(verified, str):
        verified = date.fromisoformat(verified)
    if not isinstance(verified, date):
        return [f"{page}: last_verified missing or not a date"]
    errors: list[str] = []
    for src in sources:
        src_path = repo / src
        if not src_path.exists():
            errors.append(f"{page}: cited source {src!r} does not exist")
            continue
        last = _last_commit_date(src_path, repo)
        if last is None:
            errors.append(f"{page}: {src!r} is not tracked by git")
            continue
        if last > verified:
            errors.append(
                f"{page}: {src} last modified {last}, "
                f"verified {verified} — re-verify and bump last_verified"
            )
    return errors


def main(argv: list[str]) -> int:
    repo = Path(argv[1] if len(argv) > 1 else ".").resolve()
    docs = repo / "docs"
    if not docs.is_dir():
        print(f"error: {docs} not a directory", file=sys.stderr)
        return 2
    had_errors = False
    for page in sorted(docs.rglob("*.md")):
        if "/superpowers/" in page.as_posix():
            continue
        errors = _check_page(page, repo)
        for e in errors:
            print(e, file=sys.stderr)
        if errors:
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scripts/test_check_doc_sources.py::test_clean_repo_exits_zero -v`
Expected: PASS.

- [ ] **Step 5: Add drift-detection test**

Append to `tests/test_scripts/test_check_doc_sources.py`:

```python
def test_source_modified_after_verified_fails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "src").mkdir()
    src = tmp_path / "src" / "module.py"
    src.write_text("x = 1\n")
    _commit(tmp_path, "src v1")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        PAGE_TEMPLATE.format(verified="2000-01-01")
    )
    _commit(tmp_path, "docs")
    src.write_text("x = 2\n")
    _commit(tmp_path, "src v2")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "last modified" in result.stderr


def test_missing_source_fails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        PAGE_TEMPLATE.format(verified="2099-01-01")
    )
    _commit(tmp_path, "docs")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_page_without_sources_is_skipped(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: landing\nstatus: stable\nlast_verified: 2099-01-01\n---\n"
    )
    _commit(tmp_path, "docs")
    result = _run(tmp_path)
    assert result.returncode == 0
```

- [ ] **Step 6: Run full test file**

Run: `uv run pytest tests/test_scripts/test_check_doc_sources.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_doc_sources.py tests/test_scripts/test_check_doc_sources.py
git commit -m "feat(docs): add frontmatter drift gate (check_doc_sources.py)"
```

---

## Task 2: Extend frontmatter validator to require `sources:` on narrative pages

**Files:**
- Modify: `scripts/check_frontmatter.py`
- Modify: `tests/test_scripts/test_check_frontmatter.py`

- [ ] **Step 1: Add failing test**

In `tests/test_scripts/test_check_frontmatter.py`, add:

```python
def test_explanation_page_without_sources_rejected(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: explanation\nstatus: stable\nlast_verified: 2026-04-15\n---\n"
    )
    from scripts.check_frontmatter import main
    rc = main(["check_frontmatter", str(page)])
    assert rc == 1


def test_explanation_page_with_sources_accepted(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: explanation\nstatus: stable\nlast_verified: 2026-04-15\n"
        "sources:\n  - src/x.py\n---\n"
    )
    from scripts.check_frontmatter import main
    rc = main(["check_frontmatter", str(page)])
    assert rc == 0


def test_generated_reference_page_exempt_from_sources(tmp_path: Path) -> None:
    page = tmp_path / "p.md"
    page.write_text(
        "---\ntitle: x\nsummary: x\naudience: [app-developers]\n"
        "diataxis: reference\nstatus: stable\nlast_verified: 2026-04-15\n"
        "generated: true\n---\n"
    )
    from scripts.check_frontmatter import main
    rc = main(["check_frontmatter", str(page)])
    assert rc == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripts/test_check_frontmatter.py::test_explanation_page_without_sources_rejected -v`
Expected: FAIL (currently passes — no sources enforcement).

- [ ] **Step 3: Implement rule**

In `scripts/check_frontmatter.py`, modify `_validate`:

```python
NARRATIVE_DIATAXIS = {"tutorial", "how-to", "explanation"}


def _validate(fm: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    missing = REQUIRED - fm.keys()
    if missing:
        errs.append(f"missing fields: {sorted(missing)}")
    if (d := fm.get("diataxis")) and d not in VALID_DIATAXIS:
        errs.append(f"diataxis must be one of {sorted(VALID_DIATAXIS)}, got {d!r}")
    if (s := fm.get("status")) and s not in VALID_STATUS:
        errs.append(f"status must be one of {sorted(VALID_STATUS)}, got {s!r}")
    aud = fm.get("audience")
    if isinstance(aud, list):
        bad = set(aud) - VALID_AUDIENCES
        if bad:
            errs.append(f"unknown audience values: {sorted(bad)}")
    d = fm.get("diataxis")
    needs_sources = d in NARRATIVE_DIATAXIS or (
        d == "reference" and not fm.get("generated")
    )
    if needs_sources:
        srcs = fm.get("sources")
        if not isinstance(srcs, list) or not srcs:
            errs.append("sources: required and must be a non-empty list")
    return errs
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_scripts/test_check_frontmatter.py -v`
Expected: all tests PASS (new three + existing).

- [ ] **Step 5: Commit**

```bash
git add scripts/check_frontmatter.py tests/test_scripts/test_check_frontmatter.py
git commit -m "feat(docs): require sources frontmatter on narrative pages"
```

---

## Task 3: Tutorial snippet runner + tests

**Files:**
- Create: `scripts/verify_tutorial_snippets.py`
- Create: `tests/test_scripts/test_verify_tutorial_snippets.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scripts/test_verify_tutorial_snippets.py
import subprocess
import sys
import textwrap
from pathlib import Path


SCRIPT = Path.cwd() / "scripts" / "verify_tutorial_snippets.py"


def _run(tutorials_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(tutorials_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_good_python_block_passes(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(textwrap.dedent("""\
        # t

        ```python
        x = 1 + 1
        assert x == 2
        ```
        """))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout


def test_bad_python_block_fails(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(textwrap.dedent("""\
        ```python
        raise RuntimeError("nope")
        ```
        """))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "RuntimeError" in r.stderr


def test_no_verify_skipped(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(textwrap.dedent("""\
        ```python no-verify
        raise RuntimeError("nope")
        ```
        """))
    r = _run(tmp_path)
    assert r.returncode == 0


def test_consecutive_python_blocks_share_scope(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(textwrap.dedent("""\
        ```python
        x = 5
        ```

        ```python
        assert x == 5
        ```
        """))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr + r.stdout


def test_reset_breaks_scope(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(textwrap.dedent("""\
        ```python
        x = 5
        ```

        ```python reset
        assert x == 5
        ```
        """))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "NameError" in r.stderr
```

- [ ] **Step 2: Run test to verify it fails (script doesn't exist)**

Run: `uv run pytest tests/test_scripts/test_verify_tutorial_snippets.py -v`
Expected: FAIL — script not found.

- [ ] **Step 3: Implement the script**

```python
# scripts/verify_tutorial_snippets.py
"""Extract fenced Python code blocks from tutorial pages and execute them.

Python blocks are executed in a subprocess with fathom importable.
YAML content is verified by being loaded inside the Python block that
references it — no separate YAML runner.

Tag ``no-verify`` skips a block. Tag ``reset`` starts a fresh subprocess
for python blocks (default: consecutive python blocks share scope).

Exit codes: 0 clean; 1 snippet failure; 2 misconfig.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

FENCE = re.compile(r"^```(\w+)([^\n]*)$", re.MULTILINE)


@dataclass
class Block:
    lang: str
    tags: set[str]
    body: str
    page: Path
    line: int


def _extract(page: Path) -> list[Block]:
    text = page.read_text(encoding="utf-8")
    blocks: list[Block] = []
    lines = text.splitlines(keepends=True)
    i = 0
    line_no = 1
    while i < len(lines):
        m = FENCE.match(lines[i].rstrip("\n"))
        if m:
            lang = m.group(1)
            tags = set(m.group(2).split())
            start = i + 1
            start_line = line_no + 1
            j = start
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            body = "".join(lines[start:j])
            blocks.append(Block(lang=lang, tags=tags, body=body, page=page, line=start_line))
            line_no += j - i + 1
            i = j + 1
        else:
            line_no += 1
            i += 1
    return blocks


def _run_python_group(blocks: list[Block]) -> tuple[int, str]:
    program = "\n".join(b.body for b in blocks)
    with tempfile.TemporaryDirectory(prefix="fathom-snip-") as d:
        r = subprocess.run(
            [sys.executable, "-c", program],
            cwd=d,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    return r.returncode, r.stderr


def _process(page: Path) -> list[str]:
    blocks = _extract(page)
    errors: list[str] = []
    py_group: list[Block] = []
    for b in blocks:
        if "no-verify" in b.tags:
            continue
        if b.lang != "python":
            continue
        if "reset" in b.tags and py_group:
            rc, err = _run_python_group(py_group)
            if rc != 0:
                errors.append(f"{page}:{py_group[0].line} {err}")
            py_group = []
        py_group.append(b)
    if py_group:
        rc, err = _run_python_group(py_group)
        if rc != 0:
            errors.append(f"{page}:{py_group[0].line} {err}")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "docs/tutorials").resolve()
    if not root.is_dir():
        print(f"error: {root} not a directory", file=sys.stderr)
        return 2
    had_errors = False
    for page in sorted(root.rglob("*.md")):
        for e in _process(page):
            print(e, file=sys.stderr)
            had_errors = True
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_scripts/test_verify_tutorial_snippets.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_tutorial_snippets.py tests/test_scripts/test_verify_tutorial_snippets.py
git commit -m "feat(docs): add tutorial snippet verifier"
```

---

## Task 4: Wire the two new gates into CI

**Files:**
- Modify: `.github/workflows/docs.yml`

- [ ] **Step 1: Add CI steps**

In `.github/workflows/docs.yml`, locate the existing "SDK coverage" step and add two new steps immediately after it, before the Markdown lint step:

```yaml
      - name: Doc source drift gate
        run: uv run python scripts/check_doc_sources.py

      - name: Tutorial snippet verification
        run: uv run python scripts/verify_tutorial_snippets.py docs/tutorials
        if: hashFiles('docs/tutorials/*.md') != ''
```

The `if:` guard on the tutorial step lets the gate pass cleanly before any tutorial exists (Phase 2 tasks create them).

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docs.yml
git commit -m "ci(docs): add drift gate and tutorial snippet gate"
```

---

## Task 5: Nav scaffold in `mkdocs.yml`

**Files:**
- Modify: `mkdocs.yml`

Add the new top-level sections *alongside* the existing Architecture / YAML Reference / Guides sections. The old sections stay live through Phase 2 so legacy pages continue resolving until retirement. New sections start empty and fill as Phase 2 tasks land.

- [ ] **Step 1: Extend nav**

Replace the `nav:` block in `mkdocs.yml` with:

```yaml
nav:
  - Home: _index.md
  - Getting Started: getting-started.md
  - Tutorials:
      - Overview: tutorials/index.md
      - Hello-world policy: tutorials/hello-world.md
      - Modules & salience: tutorials/modules-and-salience.md
      - Working memory across evaluations: tutorials/working-memory.md
  - How-to Guides:
      - Overview: how-to/index.md
      - Writing rules: how-to/writing-rules.md
      - Integrating with FastAPI: how-to/fastapi.md
      - Using the CLI: how-to/cli.md
      - Registering a Python function: how-to/register-function.md
      - Loading a rule pack: how-to/load-rule-pack.md
      - Embedding via SDK: how-to/embed-sdk.md
  - Concepts:
      - Overview: concepts/index.md
      - Five Primitives: concepts/primitives.md
      - Runtime & Working Memory: concepts/runtime.md
      - YAML Compilation: concepts/yaml-compilation.md
      - Audit & Attestation: concepts/audit-attestation.md
      - CLIPS Features Not In v1: concepts/not-in-v1.md
  - Reference:
      - Overview: reference/index.md
      - Python SDK: reference/python-sdk/index.md
      - Go SDK: reference/go-sdk/index.md
      - TypeScript SDK: reference/typescript-sdk/index.md
      - REST API:
          - Overview: reference/rest/index.md
          - Try It: reference/rest/try.md
      - gRPC API: reference/grpc/index.md
      - MCP Tools: reference/mcp/index.md
      - YAML:
          - Schemas: reference/yaml/index.md
          - Template: reference/yaml/template.md
          - Rule: reference/yaml/rule.md
          - Module: reference/yaml/module.md
          - Function: reference/yaml/function.md
          - Fact: reference/yaml/fact.md
      - CLI: reference/cli/index.md
      - VSCode Tooling: reference/tooling/vscode/index.md
      - Rule Packs:
          - OWASP Agentic: reference/rule-packs/owasp-agentic.md
          - NIST 800-53: reference/rule-packs/nist-800-53.md
          - HIPAA: reference/rule-packs/hipaa.md
          - CMMC: reference/rule-packs/cmmc.md
      - Planned Integrations: reference/planned-integrations.md
```

Leave the old "Guides", "Architecture", and "YAML Reference" nav sections in place for now — they'll be removed in Phase 3 along with the legacy files.

Actually: **remove** the old "Guides" (`Writing Rules` + `Integration Overview`) section immediately — `how-to/writing-rules.md` subsumes it and Integration Overview is being retired. Add redirects now:

In `mkdocs.yml` `redirect_maps`, add:

```yaml
        writing-rules.md: how-to/writing-rules.md
        integration.md: how-to/index.md
```

Keep Architecture and YAML Reference nav sections temporarily; Task 29 removes them.

- [ ] **Step 2: Confirm build still works**

Run: `uv run mkdocs build --strict 2>&1 | tail -20`
Expected: many warnings about missing new pages (tutorials/*, how-to/*, concepts/*). Note: strict build will FAIL at this point — that's fine, the build just needs to succeed after Phase 2. Skip this step if strict fails; use `uv run mkdocs build` (non-strict) to confirm no syntax errors in the YAML.

Actually use non-strict: `uv run mkdocs build 2>&1 | tail -20`
Expected: warnings but no YAML parse errors.

- [ ] **Step 3: Commit**

```bash
git add mkdocs.yml
git commit -m "chore(docs): scaffold Wave 2 nav (Tutorials/How-to/Concepts)"
```

---

# Phase 2 — Content

Each Phase-2 task follows the same sub-skeleton: **outline → draft → local verify → commit**. Steps below spell it out for Task 6 and abbreviate it for subsequent content tasks (the structure is identical).

**Shared frontmatter template for every content page:**

```yaml
---
title: <page title>
summary: <one-line blurb>
audience: [<one or more of: app-developers, rule-authors, contributors>]
diataxis: <tutorial | how-to | explanation | reference | landing>
status: stable
last_verified: 2026-04-15
sources:
  - <repo-relative path to every source file the page describes>
---
```

Landing pages (`*/index.md`) declare `diataxis: landing` and do NOT need `sources:` — the validator exempts `landing`.

---

## Task 6: Tutorial 1 — Hello-world policy

**Files:**
- Create: `docs/tutorials/index.md`
- Create: `docs/tutorials/hello-world.md`

- [ ] **Step 1: Write tutorials landing**

`docs/tutorials/index.md`:

```markdown
---
title: Tutorials
summary: Progressive, hands-on tutorials that walk you through building policy engines with Fathom.
audience: [app-developers, rule-authors]
diataxis: landing
status: stable
last_verified: 2026-04-15
---

# Tutorials

1. [Hello-world policy](hello-world.md) — install Fathom, write your first rule, evaluate a fact.
2. [Modules & salience](modules-and-salience.md) — split rules across modules, control execution order.
3. [Working memory across evaluations](working-memory.md) — persist facts between `evaluate()` calls.

Each tutorial takes ~20 minutes and assumes no prior CLIPS or Fathom knowledge.
```

- [ ] **Step 2: Outline the tutorial**

Open and read (for source citations, not prose):
- `src/fathom/engine.py` — the Engine class surface
- `src/fathom/compiler.py` — the Compiler class surface
- `src/fathom/models.py` — TemplateDefinition, RuleDefinition, etc.

Draft outline for `docs/tutorials/hello-world.md`:

1. Install (`pip install fathom-rules`).
2. Write a single-template YAML file.
3. Write a single-rule YAML file that matches the template.
4. Load them into an `Engine`.
5. Assert a fact.
6. Call `evaluate()` and inspect the audit record.

- [ ] **Step 3: Write the tutorial**

`docs/tutorials/hello-world.md`:

```markdown
---
title: Hello-world policy
summary: Install Fathom, write a template and a rule in YAML, evaluate a fact, and inspect the audit record.
audience: [app-developers, rule-authors]
diataxis: tutorial
status: stable
last_verified: 2026-04-15
sources:
  - src/fathom/engine.py
  - src/fathom/compiler.py
  - src/fathom/models.py
---

# Hello-world policy

In this tutorial you'll install Fathom, define one template and one rule in YAML, load them into an engine, assert a fact, and read the audit record that comes back.

## 1. Install

```bash no-verify
pip install fathom-rules
```

## 2. Define a template

A template is the schema for a fact. Save this as `agent.yaml`:

```yaml
templates:
  - name: agent
    slots:
      - name: id
        type: string
        required: true
      - name: clearance
        type: symbol
        required: true
        allowed_values: [public, confidential, secret]
```

## 3. Define a rule

Save this as `rules.yaml`:

```yaml
ruleset: demo
version: "1.0"
module: MAIN
rules:
  - name: allow-public
    when:
      - template: agent
        conditions:
          - slot: clearance
            expression: "== public"
    then:
      action: allow
```

## 4. Load and evaluate

<!-- authored as a single Python program; snippet runner concatenates these blocks -->

```python no-verify
from fathom.engine import Engine

engine = Engine()
engine.load_template_file("agent.yaml")
engine.load_ruleset_file("rules.yaml")

engine.assert_fact("agent", {"id": "a-1", "clearance": "public"})
record = engine.evaluate()

print(record.decision)       # -> "allow"
print(record.rules_fired)    # -> ["allow-public"]
```

The `no-verify` tag skips snippet execution because the install step and file paths aren't part of the test harness. The engine calls themselves are verified in [working memory](working-memory.md), which builds on this example with a real in-memory path.

## What just happened?

- Fathom compiled your YAML to CLIPS constructs via `fathom.compiler.Compiler` and loaded them into an embedded CLIPS environment.
- Your fact matched the condition `clearance == public`, the rule fired, and the rule's `then.action: allow` became the decision on the audit record.
- The `AuditRecord` captures which rules fired, the final decision, and any user-asserted facts — see [Audit & Attestation](../concepts/audit-attestation.md).

## Next

- [Modules & salience](modules-and-salience.md) — add a deny rule with higher priority.
```

> **Implementation note to the subagent:** Verify every API call (`engine.load_template_file`, `engine.load_ruleset_file`, `engine.assert_fact`, `engine.evaluate`, `record.decision`, `record.rules_fired`) exists in `src/fathom/engine.py` and `src/fathom/models.py` before committing. If any call has a different name, rewrite the prose to match the real API — do not invent.

- [ ] **Step 4: Run local gates**

Run in order:
```bash
uv run python scripts/check_frontmatter.py docs/tutorials/hello-world.md
uv run python scripts/check_doc_sources.py
uv run python scripts/verify_tutorial_snippets.py docs/tutorials
uv run mkdocs build 2>&1 | grep -i warn | head
```
Expected: first three exit 0; mkdocs warnings only about other not-yet-created pages in the Wave 2 nav.

- [ ] **Step 5: Commit**

```bash
git add docs/tutorials/index.md docs/tutorials/hello-world.md
git commit -m "docs(tutorials): add hello-world policy tutorial"
```

---

## Task 7: Tutorial 2 — Modules & salience

**Files:**
- Create: `docs/tutorials/modules-and-salience.md`

- [ ] **Step 1: Read source for citation**

Files to cite: `src/fathom/models.py` (ModuleDefinition, RuleDefinition.salience), `src/fathom/compiler.py` (compile_module).

- [ ] **Step 2: Outline**

1. Motivation: fail-closed policy needs deny-beats-allow.
2. Define two modules: `allow_rules` and `deny_rules` (or salience-only single module).
3. Write a deny rule with `salience: 100` and an allow rule with `salience: 0`.
4. Evaluate a fact that matches both; show deny wins.

- [ ] **Step 3: Author the page**

Follow the frontmatter + snippet-discipline from Task 6. YAML rule snippets should be runnable through the snippet runner; Python/engine interaction blocks can be `no-verify` if they use the same dependencies as the Task-6 tutorial (installation, file paths), but any pure-engine block should run.

Authored content must:
- Reference `salience: N` field per `RuleDefinition.salience` in `src/fathom/models.py`.
- Reference module focus stack per `Compiler.compile_focus_stack` in `src/fathom/compiler.py`.
- Show actual engine output for a fact that matches both rules.

- [ ] **Step 4: Local verify and commit**

```bash
uv run python scripts/check_frontmatter.py docs/tutorials/modules-and-salience.md
uv run python scripts/check_doc_sources.py
uv run python scripts/verify_tutorial_snippets.py docs/tutorials
git add docs/tutorials/modules-and-salience.md
git commit -m "docs(tutorials): add modules and salience tutorial"
```

---

## Task 8: Tutorial 3 — Working memory across evaluations

**Files:**
- Create: `docs/tutorials/working-memory.md`

- [ ] **Step 1: Read source**

Cite: `src/fathom/engine.py` (session lifecycle, `evaluate()`, working memory persistence).

- [ ] **Step 2: Outline**

1. Explain that `assert_fact` persists across `evaluate()` calls in the same `Engine` instance.
2. Demonstrate: assert fact A, evaluate, assert fact B, evaluate — rules see both on the second call.
3. Contrast with stateless systems (OPA/Cedar) — Fathom's core differentiator.
4. Show how to explicitly clear working memory (whatever method `Engine` exposes; if none, explicitly state that the session is the unit of lifetime and recommend creating a new Engine).

- [ ] **Step 3: Author, verify, commit** (same pattern as Tasks 6-7).

---

## Task 9: How-to — Writing rules

**Files:**
- Create: `docs/how-to/index.md`
- Create: `docs/how-to/writing-rules.md`

- [ ] **Step 1: Landing page**

```markdown
---
title: How-to Guides
summary: Task-oriented recipes for common Fathom operations.
audience: [app-developers, rule-authors]
diataxis: landing
status: stable
last_verified: 2026-04-15
---

# How-to Guides

- [Writing rules](writing-rules.md)
- [Integrating with FastAPI](fastapi.md)
- [Using the CLI](cli.md)
- [Registering a Python function](register-function.md)
- [Loading a rule pack](load-rule-pack.md)
- [Embedding via SDK](embed-sdk.md)
```

- [ ] **Step 2: Migrate existing writing-rules.md**

The existing `docs/writing-rules.md` is legacy — do NOT copy its prose. Open `src/fathom/models.py` (RuleDefinition, ConditionEntry, ThenBlock, AssertSpec, FactPattern) and author fresh prose covering:

- Rule skeleton (`ruleset`, `module`, `rules` list).
- `when` clauses: template, alias, conditions.
- `ConditionEntry` fields: `slot`, `expression`, `bind`, `test` — with one example per.
- `then` block: `action` (allow/deny/defer) and optional `assert` blocks.
- Salience overview (cross-link to the tutorial).

Frontmatter: `diataxis: how-to`, sources = `[src/fathom/models.py, src/fathom/compiler.py]`.

- [ ] **Step 3: Local verify and commit**

```bash
uv run python scripts/check_frontmatter.py docs/how-to/index.md docs/how-to/writing-rules.md
uv run python scripts/check_doc_sources.py
git add docs/how-to/index.md docs/how-to/writing-rules.md
git commit -m "docs(how-to): rewrite writing-rules against current models"
```

---

## Task 10: How-to — Integrating with FastAPI

**Files:**
- Create: `docs/how-to/fastapi.md`

- [ ] **Step 1: Read source**

Cite: `src/fathom/integrations/rest.py` (the FastAPI app, endpoint shapes). Optionally `src/fathom/engine.py` for engine construction patterns.

- [ ] **Step 2: Author**

Content covers:
- Fathom already ships a FastAPI app (`src/fathom/integrations/rest.py`); explain its endpoints (compile, evaluate).
- Show how to mount it in an existing FastAPI application (`app.mount("/fathom", fathom_app)` or equivalent — verify the actual export).
- Show how to wrap the Engine directly inside a custom FastAPI endpoint (bypassing the bundled app).
- Cover auth: reference whatever auth is currently present (check `src/fathom/integrations/rest.py` for e.g. API-key middleware).

Frontmatter: `diataxis: how-to`, sources = `[src/fathom/integrations/rest.py]` (plus engine.py if referenced).

- [ ] **Step 3: Verify + commit.**

---

## Task 11: How-to — Using the CLI

**Files:**
- Create: `docs/how-to/cli.md`

- [ ] **Step 1: Read source**

Cite: `src/fathom/cli.py`. Also check what `scripts/generate_cli_docs.py` produces in `docs/reference/cli/`.

- [ ] **Step 2: Author**

- Explain `fathom` entry point, list available commands (compile, evaluate, etc. — derive from cli.py).
- For each command, one-line purpose + one worked example.
- Cross-link to `reference/cli/index.md` for the full flag matrix.

Frontmatter: sources = `[src/fathom/cli.py]`.

- [ ] **Step 3: Verify + commit.**

---

## Task 12: How-to — Registering a Python function

**Files:**
- Create: `docs/how-to/register-function.md`

- [ ] **Step 1: Read source**

Cite: `src/fathom/engine.py` (`Engine.register_function`). Verify the exact signature.

- [ ] **Step 2: Author**

- Explain when to register a function (classification, temporal, or arbitrary Python callable available in rules).
- Show signature: `engine.register_function(name: str, fn: Callable[..., Any]) -> None` — match exact signature from code.
- Show two examples: (a) a classification-style predicate used in a rule's `expression`, (b) a function called from a `then.assert` slot value.
- Reference `ConditionEntry.test` for calling registered functions from the LHS.

Frontmatter: sources = `[src/fathom/engine.py]`.

- [ ] **Step 3: Verify + commit.**

---

## Task 13: How-to — Loading a rule pack

**Files:**
- Create: `docs/how-to/load-rule-pack.md`

- [ ] **Step 1: Read source**

Cite: whatever rule-pack loader exists — look under `src/fathom/` for rule-pack entry points. If none, cite `src/fathom/engine.py` load methods and the rule-packs directory structure (`docs/reference/rule-packs/` metadata).

- [ ] **Step 2: Author**

- Explain rule packs (OWASP Agentic, NIST, HIPAA, CMMC from Wave 1) as curated rule sets.
- Show how to install (if packaged separately) and load into an engine.
- Cross-link to `reference/rule-packs/*` for the inventory.

Frontmatter: sources as determined from reading.

- [ ] **Step 3: Verify + commit.**

---

## Task 14: How-to — Embedding via SDK

**Files:**
- Create: `docs/how-to/embed-sdk.md`

- [ ] **Step 1: Read source**

Cite: `packages/fathom-go/` client entry, `packages/fathom-ts/src/index.ts`, and the Python embedding path (`src/fathom/engine.py` direct import vs REST client). List the specific files that show each SDK's primary client class.

- [ ] **Step 2: Author**

Three parallel sections (Python / Go / TypeScript), each showing:
- Install.
- Client construction (for remote SDKs: point at a Fathom REST server).
- One call: compile + evaluate + read audit.
- Cross-link to the per-language Reference page for full surface.

Frontmatter sources list all three SDK entry points and `src/fathom/integrations/rest.py`.

- [ ] **Step 3: Verify + commit.**

---

## Task 15: Concept — Five Primitives

**Files:**
- Create: `docs/concepts/index.md`
- Create: `docs/concepts/primitives.md`

- [ ] **Step 1: Landing page**

```markdown
---
title: Concepts
summary: Understanding-oriented explanations of how Fathom works.
audience: [app-developers, rule-authors, contributors]
diataxis: landing
status: stable
last_verified: 2026-04-15
---

# Concepts

- [Five Primitives](primitives.md)
- [Runtime & Working Memory](runtime.md)
- [YAML Compilation](yaml-compilation.md)
- [Audit & Attestation](audit-attestation.md)
- [CLIPS Features Not In v1](not-in-v1.md)
```

- [ ] **Step 2: Read source**

Cite: `src/fathom/models.py` (TemplateDefinition, RuleDefinition, ModuleDefinition, FunctionDefinition, FactPattern, AssertSpec), `src/fathom/compiler.py`.

- [ ] **Step 3: Author primitives.md**

One section per primitive: Template, Fact, Rule, Module, Function. Each section:
- One-line definition.
- The Pydantic model it maps to (link to reference).
- The CLIPS construct it compiles to (deftemplate, assert, defrule, defmodule, deffunction).
- One tiny example, YAML only, no prose about execution.

Frontmatter: `diataxis: explanation`, sources as above.

- [ ] **Step 4: Verify + commit.**

---

## Task 16: Concept — Runtime & Working Memory

**Files:**
- Create: `docs/concepts/runtime.md`

Cite: `src/fathom/engine.py` (Engine construction, session lifecycle, evaluate), `src/fathom/evaluator.py` (if it contains the evaluation loop). Content covers: clipspy embedding, session = Engine instance, working memory persistence semantics, concurrent-session guidance (what's thread-safe, what isn't — read the code to answer).

---

## Task 17: Concept — YAML Compilation

**Files:**
- Create: `docs/concepts/yaml-compilation.md`

Cite: `src/fathom/compiler.py` (all `compile_*` methods), `src/fathom/models.py` (Pydantic gates). Content covers: the pipeline YAML → Pydantic validation → Compiler → CLIPS text → clipspy env load; where validation happens, where compilation happens, what's "passthrough" raw CLIPS.

---

## Task 18: Concept — Audit & Attestation

**Files:**
- Create: `docs/concepts/audit-attestation.md`

Cite: `src/fathom/models.py` (AuditRecord, AssertedFact), `src/fathom/engine.py` (the hook that populates `asserted_facts`). Content covers: what's in an audit record, what "attestation" means in Fathom (if there's an attestation module — check the code; if none exists today, say so and cross-link to the planned-integrations page rather than inventing).

---

## Task 19: Concept — CLIPS Features Not In v1

**Files:**
- Create: `docs/concepts/not-in-v1.md`

Cite: nothing from src/ (this page is explicitly about what is *not* implemented). `sources:` list is empty, which the validator accepts only on landing pages. **Workaround:** declare `diataxis: explanation` plus `sources: [README.md]` (the project README documents scope) — adjust the validator if this becomes painful, but for one page the README citation is honest.

Content: COOL, backward-chaining, message-handlers, instance-based pattern matching, the visual editor — each with: what it is, why excluded from v1, and what the user should do today (usually: wait, or use an equivalent primitive that IS shipped).

---

## Task 20-24: YAML Reference per-construct pages

Five tasks, one per construct: Template, Rule, Module, Function, Fact.

**Files (one per task):**
- Create: `docs/reference/yaml/template.md`
- Create: `docs/reference/yaml/rule.md`
- Create: `docs/reference/yaml/module.md`
- Create: `docs/reference/yaml/function.md`
- Create: `docs/reference/yaml/fact.md`

Each page:
- Frontmatter `diataxis: reference`, sources = `[src/fathom/models.py]` at minimum.
- Renders the construct's JSON Schema inline (link to the schema file that already exists under `docs/reference/yaml/schemas/`).
- Field-by-field table: field name, type, required, default, description. Pulls descriptions from the Pydantic model's `Field(..., description=...)` args where present.
- One minimal example YAML snippet.
- One realistic example YAML snippet.
- Cross-link to the corresponding Concepts page.

Commit each page separately: `docs(reference): add YAML <construct> reference page`.

---

## Task 25: Planned Integrations page

**Files:**
- Create: `docs/reference/planned-integrations.md`

- [ ] **Step 1: Author**

```markdown
---
title: Planned Integrations
summary: Framework adapters that are planned but not yet shipped.
audience: [app-developers]
diataxis: reference
status: stable
last_verified: 2026-04-15
generated: false
sources:
  - README.md
---

# Planned Integrations

These AI-framework adapters are on the roadmap but not yet implemented. No code ships with `fathom-rules` for these frameworks today.

| Framework            | Status   | Tracking issue |
|----------------------|----------|----------------|
| LangChain            | planned  | (none yet)     |
| CrewAI               | planned  | (none yet)     |
| OpenAI Agent SDK     | planned  | (none yet)     |
| Google ADK           | planned  | (none yet)     |

To use Fathom with any of these today, call the REST or gRPC endpoints directly — see [Integrating with FastAPI](../how-to/fastapi.md) for the pattern.
```

- [ ] **Step 2: Verify + commit.**

---

## Task 26: Rewrite Home + Getting Started

**Files:**
- Modify: `docs/_index.md`
- Modify: `docs/getting-started.md`

- [ ] **Step 1: Home**

Rewrite `docs/_index.md` with full frontmatter (diataxis: landing works for homepages per existing VALID_DIATAXIS). Content: one paragraph on what Fathom is, deep-link grid into Tutorials / How-to / Concepts / Reference.

- [ ] **Step 2: Getting Started**

Rewrite `docs/getting-started.md` against the current install and entry surfaces:
- `pip install fathom-rules`.
- Point at the Hello-world tutorial as the first hands-on step.
- Frontmatter: `diataxis: tutorial`, `sources: [src/fathom/engine.py]`.

- [ ] **Step 3: Verify + commit.**

---

## Task 27: Update Wave-1 YAML schema landing with `sources:`

**Files:**
- Modify: `docs/reference/yaml/index.md`

- [ ] **Step 1: Add sources**

The current page is hand-authored but has no `sources:`. Add:

```yaml
sources:
  - src/fathom/models.py
  - scripts/export_json_schemas.py
```

- [ ] **Step 2: Verify (sources drift gate must pass) + commit.**

---

# Phase 3 — Retirement + Completion

## Task 28: Legacy file retirement

**Files:**
- Delete: `docs/core/**`, `docs/integrations/**`, `docs/yaml/**`, `docs/integration.md`, `docs/writing-rules.md`, `docs/advanced/**` (audit per below).
- Modify: `.github/workflows/docs.yml`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Audit `docs/advanced/**`**

Run: `ls docs/advanced/` and open each file. Default is `git rm`. Any file preserved must have been rewritten under Concepts or How-to in Phase 2 with `sources:` — if it wasn't, delete it.

- [ ] **Step 2: Remove legacy files**

```bash
git rm -r docs/core docs/integrations docs/yaml
git rm docs/integration.md docs/writing-rules.md
git rm -r docs/advanced   # adjust per Step 1
```

- [ ] **Step 3: Update `mkdocs.yml`**

Remove the old `Architecture:` and `YAML Reference:` top-level nav sections. The final nav contains exactly the sections listed in Task 5.

Extend `redirect_maps` with:

```yaml
        core/primitives.md: concepts/primitives.md
        core/runtime.md: concepts/runtime.md
        core/yaml-compiler.md: concepts/yaml-compilation.md
        core/fact-asserter.md: concepts/runtime.md
        core/forward-chaining.md: concepts/runtime.md
        core/backward-chaining.md: concepts/not-in-v1.md
        core/working-memory.md: concepts/runtime.md
        core/audit-log.md: concepts/audit-attestation.md
        core/attestation.md: concepts/audit-attestation.md
        core/message-handlers.md: concepts/not-in-v1.md
        core/cool.md: concepts/not-in-v1.md
        core/visual-editor.md: concepts/not-in-v1.md
        integrations/cli.md: how-to/cli.md
        integrations/go-sdk.md: reference/go-sdk/index.md
        integrations/typescript-sdk.md: reference/typescript-sdk/index.md
        integrations/grpc.md: reference/grpc/index.md
        integrations/mcp.md: reference/mcp/index.md
        integrations/sidecar.md: how-to/fastapi.md
        integrations/prometheus.md: reference/rest/index.md
        integrations/langchain.md: reference/planned-integrations.md
        integrations/crew-ai.md: reference/planned-integrations.md
        integrations/open-ai-agent-sdk.md: reference/planned-integrations.md
        integrations/google-adk.md: reference/planned-integrations.md
        yaml/yaml-templates.md: reference/yaml/template.md
        yaml/yaml-facts.md: reference/yaml/fact.md
        yaml/yaml-rule-language.md: reference/yaml/rule.md
        yaml/yaml-modules.md: reference/yaml/module.md
        yaml/yaml-functions.md: reference/yaml/function.md
```

- [ ] **Step 4: Remove markdownlint exclusions**

In `.github/workflows/docs.yml` markdownlint step, remove these lines:

```
            !docs/core/**
            !docs/integration.md
            !docs/integrations/**
            !docs/yaml/**
```

Also remove `!docs/advanced/**` if present and if the directory is now deleted.

Update the codespell skip list similarly.

- [ ] **Step 5: Full local verification**

```bash
uv run mkdocs build --strict
uv run python scripts/check_doc_sources.py
uv run python scripts/check_frontmatter.py
uv run python scripts/verify_tutorial_snippets.py docs/tutorials
uv run codespell docs/ --skip "docs/reference/*,docs/llms*.txt,docs/changelog.json,docs/superpowers/*"
```

Expected: all commands exit 0. `mkdocs build --strict` must complete with no warnings.

Run lychee (or equivalent) locally if available to confirm internal links; the CI lychee step will gate in any case.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: retire legacy core/integrations/yaml pages; enable gates"
```

---

## Task 29: Wave 2 completion record

**Files:**
- Create: `docs/superpowers/plans/2026-04-15-dev-docs-wave-2-completion.md`

- [ ] **Step 1: Author the record**

Mirror the structure of the Wave 1 completion record at `docs/superpowers/plans/2026-04-15-dev-docs-wave-1-reference-completion.md`:

- **Landed:** bullet list of every task from this plan.
- **Deferred:** any follow-ups surfaced during execution (symbol-level drift granularity, AI-framework adapter implementations, tutorial notebook backing, etc.).
- **Open follow-ups:** tracking items for future waves.
- **Verification commands:** exact commands that prove the wave is done.

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-15-dev-docs-wave-2-completion.md
git commit -m "docs(plans): record Wave 2 completion"
```

---

# Final checks

After Task 29, run:

```bash
uv run pytest
uv run mkdocs build --strict
uv run python scripts/check_doc_sources.py
uv run python scripts/check_frontmatter.py
uv run python scripts/verify_tutorial_snippets.py docs/tutorials
```

All must exit 0.

Push and let CI confirm on a PR.
