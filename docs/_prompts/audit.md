# KB Audit — Gap Analysis

Run this prompt to find things that exist in the codebase but have no coverage in the knowledge base.

## Instructions

### 1. Schema Coverage

Walk all files in `supabase/volumes/db/init/*.sql` and extract every `CREATE TABLE` statement. For each table:
- Check if the table is mentioned in any KB article's Schema section
- If not, report it as a gap

```bash
grep -h "CREATE TABLE" supabase/volumes/db/init/*.sql | sed 's/CREATE TABLE IF NOT EXISTS/CREATE TABLE/' | sort
```

### 2. Enum Coverage

Extract all `CREATE TYPE ... AS ENUM` statements from `0002-enums.sql`. For each enum:
- Check if all its values are listed in `platform/schema-rules.md`
- If any values are missing, report them

### 3. API Route Coverage

Read `internal/api/router.go` and extract every `Mount*` method call. For each route:
- Check if the route appears in `platform/api-patterns.md` route table
- If not, report it as a gap

### 4. DSPy Module Coverage

Extract all values from the `dspy_module` enum. For each value:
- Check if there's a corresponding article in `docs/agents/modules/`
- If not, report it as a gap

### 5. Frontend Page Coverage

List all directories in `web-dev-ui/src/pages/`. For each page directory:
- Check if the corresponding domain has a KB article with a Conventions section mentioning this page
- If not, report it as a gap

### 6. Go Package Coverage

List all directories in `internal/`. For each package:
- Check if there's a KB article whose Conventions section references this package
- If not, report it as a gap

## Output

```
## Schema Gaps (tables with no KB coverage)
- container_executions (not mentioned in any article)
- audit_ml_events (not mentioned in any article)

## Enum Gaps (values not documented)
- dspy_module: 'code_act' not in agents/modules/ articles

## API Route Gaps
- /api/v1/budgets not documented in api-patterns.md

## Frontend Page Gaps
- web-dev-ui/src/pages/compliance/ not referenced in any article

## Go Package Gaps
- internal/enricher/ not referenced in any article

## Summary
Schema: 5 gaps | Enums: 1 gap | Routes: 2 gaps | Pages: 3 gaps | Packages: 2 gaps
```

## Follow-Up

For each gap, decide:
- **Add to existing article** — If it's a sub-entity of a documented domain
- **Create new article** — If it's a distinct concept needing its own article
- **Ignore** — If it's an internal/utility table that agents never need to know about
