# Current Task

## Task ID
FOUNDATION-010 (GitHub issue #24)

## Authorization
Add a bounded, tenant-scoped read-only API for immutable execution-run history.

## Goal
Allow callers to inspect every attempt for a tenant-owned execution job without direct database
access.

## Required Outcome
- `GET /api/v1/tenants/{tenant_id}/execution-jobs/{job_id}/runs` returns the existing execution-run
  response shape in the existing paginated collection contract.
- The tenant-owned parent job is validated before its runs are queried.
- Both items and total include only runs matching the tenant and job identifiers.
- Results are ordered by attempt number ascending, then identifier, with bounded `limit` and
  non-negative `offset` validation.
- Missing and cross-tenant parent jobs remain indistinguishable as `not_found`.
- The operation performs no write or audit side effect.

## Constraints
- Do not add or change database schema or migrations.
- Do not create, update, transition, retry, delete, schedule, or execute jobs or runs.
- Do not change authentication, authorization, tenant isolation, billing, secrets, production
  infrastructure, or deployment behavior.

## Completion Gates
- Deterministic API and repository tests cover ordering, pagination, totals, isolation, missing
  parents, empty pages, validation, and read-only behavior.
- Existing execution, proposal, approval, and audit behavior remains unchanged.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and `git diff --check`
  pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
