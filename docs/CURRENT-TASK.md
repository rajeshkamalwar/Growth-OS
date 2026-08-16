# Current Task

## Task ID
FOUNDATION-012 (GitHub issue #28)

## Authorization
Add bounded, tenant-safe filters to audit-ledger retrieval.

## Goal
Allow operators and future agents to trace specific audit events without scanning an entire
tenant ledger or introducing any write behavior.

## Required Outcome
- `GET /api/v1/tenants/{tenant_id}/audit-events` accepts optional `event_type`, `resource_type`,
  `resource_id`, and `actor_id` filters while preserving the unfiltered response and pagination
  contract.
- Supplied filters compose with logical AND and never replace the tenant predicate.
- Event and resource types use bounded, non-empty lowercase identifiers matching stored dotted and
  underscored conventions; resource and actor identifiers use UUID validation.
- Page items and the independent total use identical filters and retain deterministic ordering,
  bounded `limit`, and non-negative `offset`.
- The operation performs no write or audit side effect.

## Constraints
- Do not add or change database schema or migrations.
- Do not resolve referenced resources or create, update, delete, aggregate, or report audit events.
- Do not change authentication, authorization, tenant isolation, billing, secrets, production
  infrastructure, or deployment behavior.

## Completion Gates
- Deterministic API and repository tests cover individual filters, composition, ordering,
  pagination, totals, tenant isolation, identifier collisions, empty pages, validation, backward
  compatibility, and read-only behavior.
- Existing execution, retry, proposal, approval, run-history, and audit behavior remains unchanged.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and `git diff --check`
  pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
