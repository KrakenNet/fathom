# KB Update — Targeted Article Refresh

Run this prompt to update one or more KB articles to match current code.

## Input

Specify the scope: a single article path (e.g., `agents/overview.md`) or a domain (e.g., `all articles in governors/`).

## Source Files Reference

Use this mapping to find the authoritative source code for each domain:

| Domain | Schema Files | Go Packages | Frontend Pages |
|--------|-------------|-------------|----------------|
| Platform | All `supabase/volumes/db/init/*.sql`, `internal/api/router.go`, `internal/api/responses.go` | `internal/api/` | `web-dev-ui/src/components/ui/` |
| Agents | `0010-agent_schema.sql`, `0012-agent-module-config.sql`, `0013-optimization_runs.sql`, `0014-agent-metadata.sql` | `internal/agent/` | `web-dev-ui/src/pages/agents/` |
| Tools | `0011-tool_schema.sql`, `0101-smart_tool_registry.sql` | `internal/agent/tool_executor.go`, `internal/agent/pipeline/` | `web-dev-ui/src/pages/tools/`, `pipelines/` |
| Governors | `0093-governor_schema.sql` | `internal/governor/` | `web-dev-ui/src/pages/governors/` |
| Workflows | `0094-workflow_schema.sql`, `0097-request_schema.sql`, `0099_alert_escalation.sql` | `internal/workflow/`, `internal/workflow/engine/` | `web-dev-ui/src/pages/workflows/` |
| Knowledge | `0096-rag_schema.sql`, `1000-knowledge_bases.sql` | `internal/rag/`, `internal/knowledge/`, `internal/knowledgebase/`, `internal/memory/`, `internal/retrieval/` | `web-dev-ui/src/pages/documents/`, `knowledge-graph/`, `knowledge-bases/`, `memories/` |
| Integrations | `0009-integration_schema.sql` | `internal/integration/` | `web-dev-ui/src/pages/integrations/` |
| ML | `0101-ml_gomlx_schema.sql`, `0093-training_schema.sql` | `internal/gomlx/`, `internal/onnxrt/` | `web-dev-ui/src/pages/datasets/`, `training/` |

## Instructions

1. **Read the specified article(s).**

2. **Identify and read the relevant source files** from the table above.

3. **Compare article claims against code:**
   - Schema section: Do column names, types, defaults, and constraints match the actual CREATE TABLE statements?
   - Enum values: Do listed values match the actual CREATE TYPE statements in `0002-enums.sql`?
   - API routes: Do listed routes match actual `Mount*` methods in `router.go`?
   - File paths in Conventions section: Do they still exist?
   - Behavior descriptions: Do they match what the Go code actually does?

4. **Update the article:**
   - Fix any discrepancies found
   - Preserve the article format (frontmatter, section structure)
   - Preserve all existing links
   - Add links for any new concepts referenced
   - Stay within the 200-line soft max (300 hard max)

5. **Verify the updated article:**
   - Run `wc -l` to confirm line count
   - Check all links resolve
   - Check frontmatter is complete

## Output

Report what changed:
```
## Updated: agents/overview.md
- Added column `module_config` to Schema section (added in 0012-agent-module-config.sql)
- Updated dspy_module enum values (added 'smart_ralph')
- Fixed file path in Conventions (handler_tools.go → handler_tools.go)
```
