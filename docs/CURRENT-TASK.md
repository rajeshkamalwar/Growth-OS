# Current Task

## Task ID
FOUNDATION-013 (GitHub issue #30)

## Authorization
Add bounded, tenant-safe filters to action-proposal discovery.

## Goal
Allow operators and future approval workflows to discover pending or risk-scoped proposals
without scanning every proposal or introducing any write behavior.

## Required Outcome
- `GET /api/v1/tenants/{tenant_id}/action-proposals` accepts optional `job_id`, `status`,
  `risk_level`, and `requires_approval` filters while preserving the unfiltered response and
  pagination contract.
- Supplied filters compose with logical AND and never replace the tenant predicate.
- A supplied job identifier must resolve through the same-tenant execution boundary; missing and
  cross-tenant jobs both return `not_found`.
- Status and risk use the canonical proposal enums, while job identifiers and approval flags use
  FastAPI/Pydantic UUID and boolean parsing.
- Page items and the independent total use identical filters and retain deterministic ordering,
  bounded `limit`, and non-negative `offset`.
- Listing routes through the execution service/repository boundary and performs no write or audit
  side effect.

## Constraints
- Do not add or change database schema or migrations.
- Do not create, decide, transition, execute, or delete proposals or jobs.
- Do not change authentication, authorization, tenant isolation, billing, secrets, production
  infrastructure, or deployment behavior.

## Completion Gates
- Deterministic API, repository, and service-routing tests cover individual filters, composition,
  ordering, pagination, totals, tenant isolation, empty pages, validation, backward compatibility,
  parent-job ownership, and read-only behavior.
- Existing execution, retry, proposal, approval, run-history, and audit behavior remains unchanged.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and `git diff --check`
  pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
