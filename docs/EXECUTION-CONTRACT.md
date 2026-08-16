# Execution and Approval Contract

FOUNDATION-004 defines control-plane state only. It deliberately has no executor and cannot
perform an external action.

## Entities

- An execution job is a tenant/workspace-scoped request identified by a tenant-scoped
  idempotency key.
- A run records one bounded attempt. FOUNDATION-004 creates attempt 1 atomically with its job;
  no scheduler or retry worker exists yet. `max_attempts` is limited to 1–10 and retry delay to
  0–86,400 seconds.
- An action proposal describes a possible future action, its risk level, and whether human
  approval is required. High-risk proposals must require approval. Proposals not requiring
  approval begin approved, but remain inert.
- An approval decision is an append-only record. A proposal accepts at most one decision and
  cannot be decided again.
- An audit event is append-only and records meaningful job, proposal, and decision changes.

## State Model

Execution work uses `queued`, `running`, `awaiting_approval`, `approved`, `rejected`,
`succeeded`, `failed`, and `cancelled`. The allowed transition graph is defined in
`growth_os.execution`; rejected, succeeded, failed, and cancelled are terminal.

Proposal state is narrower: `awaiting_approval` becomes exactly one of `approved` or
`rejected`. High-risk work cannot be represented as approval-free.

## Tenant and Idempotency Guarantees

Composite foreign keys bind jobs to workspaces, runs and proposals to jobs, and decisions to
proposals within the same tenant. API and repository reads always include tenant context and
cross-tenant access fails as not found.

Repeating the same tenant idempotency key with the same request returns the original job and
run. Reusing it for a materially different request returns a conflict. Different tenants may
use the same key safely.

## API Surface

Tenant-scoped `/api/v1` endpoints create, list, and read execution jobs and action proposals;
record proposal decisions; and list audit events. Collection responses use FOUNDATION-003's
bounded `limit`/`offset` pagination and errors retain its structured envelope.

The `decided_by` identifier is provider-neutral audit attribution, not a new authorization
system. The existing tenant-context boundary remains unchanged.

## Rollback

The migration is additive. Downgrading one revision drops only the execution, proposal,
decision, and audit tables in dependency order. Back up any control-plane history before a
downgrade because those newly introduced records will be lost.
