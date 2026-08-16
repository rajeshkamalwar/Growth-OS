# Current Task

## Task ID
FOUNDATION-008 (GitHub issue #20)

## Authorization
Add atomic, auditable execution lifecycle transitions to the existing control plane.

## Goal
Allow a tenant-scoped caller to transition an execution job and its latest run together using
the canonical state graph and compare-and-set status guards.

## Required Outcome
- A strict request supplies `expected_status`, `target_status`, and optional provider-neutral
  `actor_id`.
- The tenant-owned job and latest run must both match the expected status.
- Both records change atomically through compare-and-set updates.
- Exactly one append-only audit event records each successful transition, including the prior
  status, target status, latest-run identifier, and optional actor attribution.
- Invalid, stale, inconsistent, or already-consumed transitions fail closed with
  `invalid_state_transition` and no partial update or audit event.

## Constraints
- Do not add workers, scheduling, retry-attempt creation, Temporal, or external actions.
- Do not add or change database schema or migrations.
- Do not change proposal approval semantics, authentication, authorization, tenant isolation,
  billing, secrets, production infrastructure, or deployment behavior.
- Preserve existing job creation, idempotency, proposal, and approval behavior.

## Completion Gates
- Deterministic tests cover every allowed state edge, invalid and terminal transitions, stale and
  competing attempts, rollback, audit details and actor attribution, and tenant isolation.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and
  `git diff --check` pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
