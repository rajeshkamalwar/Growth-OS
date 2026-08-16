# Current Task

## Task ID
FOUNDATION-003 (GitHub issue #5)

## Authorization
Build the tenant-safe CRUD and control-plane API foundation on FOUNDATION-002.

## Goal
Add tenant-safe repository/service boundaries and minimal validated APIs for tenant,
workspace, membership, site, and connector-status foundation resources.

## Required Outcome
- Tenant-owned lookups and mutations require explicit tenant context.
- Cross-tenant reads and writes fail safely and are covered by tests.
- API input/output schemas, bounded pagination, structured errors, identifiers, and
  audit timestamps form a stable first control-plane contract.
- Health and readiness behavior from FOUNDATION-002 remains intact.
- Connector status remains a placeholder only.

## Constraints
- Keep tenant context provider-neutral; do not invent or redesign authentication.
- Do not change tenant-isolation architecture, billing, production infrastructure,
  secrets, or destructive migrations.
- Do not add external connectors, autonomous side effects, product agents, a frontend,
  deployment workflows, OpenAI/LLM integrations, n8n, or Temporal.
- Follow `AGENTS.md` and the repository source-of-truth documents.

## Completion Gates
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and
  `git diff --check` pass where available.
- Database constraints from FOUNDATION-002 remain intact.
- Work is delivered from a task branch through a draft pull request.
