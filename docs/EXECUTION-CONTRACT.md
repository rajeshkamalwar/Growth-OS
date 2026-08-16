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

`GET /api/v1/tenants/{tenant_id}/execution-jobs/{job_id}/runs` exposes immutable attempt history
using the existing execution-run response and collection pagination contracts. The service first
requires the parent job to exist in the same tenant context, so missing and cross-tenant jobs both
return `not_found` without revealing run existence. The repository then filters runs by both tenant
and job identifiers, orders by `attempt_number` ascending with run identifier as a stable
tie-breaker, and calculates a job-specific total independent of `limit` and `offset`. Valid offsets
beyond the final attempt return an empty page with the unchanged total. The endpoint is strictly
read-only and creates no audit event.

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

## Manual Retry Reservation

`POST /api/v1/tenants/{tenant_id}/execution-jobs/{job_id}/retries` accepts a strict body:

```json
{
  "expected_attempt_number": 1,
  "actor_id": "optional-provider-neutral-uuid"
}
```

The tenant-owned job and its latest run are resolved in the request transaction. Both must be
`failed`, the latest run must match `expected_attempt_number`, and its `attempt_number` must be
less than `max_attempts`. The operation compare-and-sets the job from `failed` to `queued`, inserts
exactly one queued run at the next attempt, and commits both changes with one audit event. The new
run copies `max_attempts` and `retry_delay_seconds` from the prior run and has no
`last_error_code`. It reserves state only and never executes work or enforces retry timing.

The prior failed run is terminal and remains unchanged in execution history; retry reservation is
not an edge in the individual-run transition graph. Stale, repeated, exhausted, non-failed, or
inconsistent requests return `invalid_state_transition`. The compare-and-set job guard and the
existing unique job-attempt constraint prevent competing calls from both succeeding. Missing and
cross-tenant jobs retain `not_found` behavior. Any failed insert or commit rolls back the job
update, new run, and audit event.

A successful reservation returns the existing execution-job response with the new run as
`latest_run` and appends exactly one `execution_job.retry_reserved` event. Its details contain
`prior_run_id`, `new_run_id`, `prior_attempt_number`, and `new_attempt_number`; `actor_id` is stored
when provided.

The `decided_by`, transition `actor_id`, and retry `actor_id` identifiers are provider-neutral
audit attribution, not a new authorization system. The existing tenant-context boundary remains
unchanged.

## Rollback

FOUNDATION-008, FOUNDATION-009, and FOUNDATION-010 have no migrations. Revert their respective
implementation commits to remove the transition, retry, or run-history endpoint. Existing job,
run, and audit rows remain valid; successful transitions and retry reservations already committed
are historical state and are not reversed by the code rollback. Removing the run-history endpoint
has no data effect. The earlier additive migration rollback remains available, but dropping those
tables would delete control-plane history and requires a backup first.
