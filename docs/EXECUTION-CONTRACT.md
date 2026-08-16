# Execution and Approval Contract

The execution contract defines control-plane state and atomic lifecycle changes only. It
deliberately has no executor and cannot perform an external action.

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
record proposal decisions; transition jobs; and list audit events. Collection responses use
FOUNDATION-003's bounded `limit`/`offset` pagination and errors retain its structured envelope.

`POST /api/v1/tenants/{tenant_id}/execution-jobs/{job_id}/transitions` accepts a strict body:

```json
{
  "expected_status": "queued",
  "target_status": "running",
  "actor_id": "optional-provider-neutral-uuid"
}
```

The service resolves the tenant-owned job and its highest-attempt run in one transaction. Both
must match `expected_status`, and the canonical execution graph must allow the requested edge.
Tenant-qualified compare-and-set updates apply the target to both records. A zero-row update,
stale expectation, inconsistent status, invalid edge, or consumed transition rolls back and
returns the structured `invalid_state_transition` conflict without an audit event. Missing or
cross-tenant jobs remain indistinguishable as `not_found`.

A successful transition appends one `execution_job.transitioned` audit event in the same
transaction. Its details contain `prior_status`, `target_status`, and `run_id`; `actor_id` is
recorded when supplied. The response is the existing execution-job contract with the updated
latest run.

The `decided_by` and transition `actor_id` identifiers are provider-neutral audit attribution,
not a new authorization system. The existing tenant-context boundary remains unchanged.

## Rollback

FOUNDATION-008 has no migration. Revert its implementation commit to remove the transition
endpoint and stop new transition audit events. Existing job, run, and audit rows remain valid;
successful transitions already committed are historical state and are not reversed by the code
rollback. The earlier additive migration rollback remains available, but dropping those tables
would delete control-plane history and requires a backup first.
