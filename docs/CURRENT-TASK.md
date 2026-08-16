# Current Task

## Task ID
FOUNDATION-009 (GitHub issue #22)

## Authorization
Add a bounded, auditable manual retry reservation to the existing execution control plane.

## Goal
Allow a tenant-scoped caller to atomically re-queue a failed execution job and reserve exactly
one next queued run without executing work.

## Required Outcome
- A strict request supplies `expected_attempt_number` and optional provider-neutral `actor_id`.
- The tenant-owned job and latest run must both be failed, the attempt expectation must be current,
  and another bounded attempt must remain.
- A compare-and-set update re-queues the job and one new run increments the attempt by exactly one.
- The new run copies `max_attempts` and `retry_delay_seconds`, and clears `last_error_code`.
- The failed prior run remains immutable execution history.
- Exactly one append-only `execution_job.retry_reserved` audit event records the prior and new run
  identifiers and attempt numbers, with optional actor attribution.
- Invalid, stale, duplicate, exhausted, inconsistent, missing, or cross-tenant requests fail closed
  with no partial state or audit event.

## Constraints
- Do not execute work or add automatic scheduling, retry-delay enforcement, workers, or Temporal.
- Do not add or change database schema or migrations.
- Do not change the run transition graph, proposal approvals, authentication, authorization, tenant
  isolation, billing, secrets, production infrastructure, or deployment behavior.

## Completion Gates
- Deterministic tests cover success, preserved history, bounds, stale and competing calls, rollback,
  audit details and attribution, strict validation, and tenant isolation.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and `git diff --check` pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
