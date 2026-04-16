# KB Lint — Health Check

Run this prompt to verify the knowledge base is internally consistent.

## Instructions

1. **List all articles:**
   ```bash
   find docs/ -name "*.md" -not -path "*/superpowers/*" -not -path "*/_prompts/*" -not -name "_index.md"
   ```

2. **For each article, check:**

   a. **Frontmatter completeness** — Must have all 5 fields: `domain`, `scope`, `keywords`, `reads-before`, `depends-on`. Report ERROR for any missing field.

   b. **"Do Not" section** — Every article must have a `## Do Not` section. Report ERROR if missing.

   c. **Line count:**
   - Over 300 lines → ERROR (hard max violated, must split)
   - Over 200 lines → WARNING (soft max exceeded)
   - Under 200 lines → OK

   d. **`depends-on` references** — Every path in `depends-on` must resolve to an existing `.md` file relative to `docs/`. Report ERROR for broken references.

   e. **Inline link validation** — Every `[text](path.md)` link in the body must resolve to an existing file. Report ERROR for broken links.

   f. **Concept linking** — Scan for mentions of other domain names (agents, tools, governors, workflows, knowledge, integrations, portals) without accompanying links. Report WARNING for unlinked domain references.

3. **Check routing table (`docs/_index.md`):**
   - Every article should appear in at least one routing entry. Report INFO for orphan articles.
   - Every file referenced in the routing table must exist. Report ERROR for broken routing references.

4. **Output report:**

   Group findings by severity:
   ```
   ## ERRORS (must fix)
   - [file.md] Missing frontmatter field: keywords
   - [file.md] Broken depends-on reference: agents/nonexistent.md

   ## WARNINGS (should fix)
   - [file.md] Over 200 lines (235)
   - [file.md] Mentions "governors" without linking

   ## INFO
   - [file.md] Not referenced in _index.md routing table

   ## SUMMARY
   Articles: 62 | Errors: 0 | Warnings: 3 | Info: 1
   ```
