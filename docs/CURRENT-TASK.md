# Current Task

## Task ID
FOUNDATION-011 (GitHub issue #26)

## Authorization
Add bounded, tenant-safe filters to execution-job discovery.

## Goal
Allow future workers and operators to narrow queued-work discovery without scanning every
tenant-owned execution job or introducing execution behavior.

## Required Outcome
- `GET /api/v1/tenants/{tenant_id}/execution-jobs` accepts optional `workspace_id`, `status`, and
  `kind` query filters while preserving the existing unfiltered response and pagination contract.
- Supplied filters compose with logical AND and never replace the tenant predicate.
- A supplied workspace must exist in the same tenant; missing and cross-tenant workspaces remain
  indistinguishable as `not_found`.
- Status uses the canonical execution enum and kind uses the existing bounded lowercase job-kind
  identifier contract.
- Page items and the independent total use identical filters and retain deterministic ordering,
  bounded `limit`, and non-negative `offset`.
- The operation performs no write or audit side effect.

## Constraints
- Do not add or change database schema or migrations.
- Do not claim, lock, create, update, transition, retry, delete, schedule, or execute jobs or runs.
- Do not change authentication, authorization, tenant isolation, billing, secrets, production
  infrastructure, or deployment behavior.

## Completion Gates
- Deterministic API and repository tests cover individual filters, composition, ordering,
  pagination, totals, tenant/workspace isolation, empty pages, validation, backward compatibility,
  and read-only behavior.
- Existing execution, retry, proposal, approval, run-history, and audit behavior remains unchanged.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and `git diff --check`
  pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
