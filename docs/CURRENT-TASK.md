# Current Task

## Task ID
PRODUCT-003 ([GitHub issue #44](https://github.com/rajeshkamalwar/Growth-OS/issues/44))

## Authorization
Add one durable, paused-by-default autonomy preference per workspace, stored in PostgreSQL and
exposed through strict tenant-scoped create, get, and patch APIs. Follow the reviewed
implementation specification in [`plans/PRODUCT-003.md`](../plans/PRODUCT-003.md); issue #44
remains the authoritative contract. If implementation requires a design change, update and review
the specification before changing runtime code.

This current-task update authorizes implementation of PRODUCT-003 after this planning change is
merged. It does not queue controller work, authorize deployment, or authorize applying the
`codex-ready` label to issue #44. The orchestrator owns that label after merge and re-inspection of
the resulting `main`.

## Goal
Persist a customer's workspace-level autonomy preference as a required `AutonomyLevel` and a
strict boolean `is_paused` that defaults to `true`. This data is configuration intent only. It is
not authentication, authorization, a permission grant, safety evidence, policy enforcement, or an
instruction to execute. PRODUCT-003 does not change existing proposal, approval, risk, execution,
or external-action semantics.

## Required Outcome
- Add one additive migration and SQLAlchemy model for `workspace_autonomy_policies` and
  `WorkspaceAutonomyPolicy`.
- Define `AutonomyLevel` with exactly `observe_only`, `recommend_only`, `approval_required`, and
  `low_risk_auto`. `level` is required on create and non-null in the database.
- Store a strict boolean `is_paused`, non-null and defaulting to `true` at the application/schema,
  model, and database layers. Omission on create stores and returns `true`.
- Enforce zero or one policy per tenant/workspace with a unique `(tenant_id, workspace_id)`
  constraint and same-tenant ownership with a composite foreign key from
  `(workspace_id, tenant_id)` to `workspaces`, using `ON DELETE RESTRICT`.
- Enforce the four enum values at the database level. The uniqueness constraint serves the
  tenant/workspace lookup; add no redundant index.
- Expose only strict `POST`, `GET`, and `PATCH` at
  `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy`. POST returns 201; GET
  and PATCH return 200. No list or DELETE endpoint is authorized.
- Require the existing `X-Tenant-ID` context to match the path tenant and scope every parent and
  policy lookup by tenant and workspace. Missing and cross-tenant resources return the same
  established structured `not_found` response without revealing cross-tenant existence.
- POST requires `level`; `is_paused` may be omitted and then defaults to `true`. PATCH must supply
  at least one policy field; `actor_id` alone is not a change. Omitted fields remain unchanged.
  Reject unknown fields, invalid enum values, non-boolean `is_paused`, invalid UUIDs, and null for
  either policy field through the established structured validation response. Never return
  `actor_id` in the resource response.
- Commit each successful mutation atomically with exactly one append-only
  `workspace_autonomy_policy.created` or `workspace_autonomy_policy.updated` audit event. Use the
  policy UUID as resource ID and `workspace_autonomy_policy` as resource type. Audit details
  contain exactly `workspace_id` and alphabetically sorted explicitly supplied policy
  `changed_fields`, excluding `actor_id`.
- Do not add `is_paused` implicitly to create audit `changed_fields` when the client omits it,
  despite the stored default. Never copy policy values into audits or logs. Reads, validation
  failures, not-found operations, conflicts, and rolled-back mutations create no audit event.

## Implementation Constraints
- Extend the existing explicit typed SQLAlchemy model, strict Pydantic schema,
  repository/service, structured-error, tenant-context, router, and append-only audit patterns.
  Do not add a generic CRUD framework, JSON policy blob, redundant index, or dependency.
- Keep `AutonomyLevel` typed internally and use a database-level enum/check constraint. Preserve
  the strict boolean type and enforce the safe paused default in the schema/application, model,
  and database.
- Treat the stored policy as customer preference only. It must not be read by execution paths or
  used as authentication, authorization, permission, safety evidence, risk clearance, or runtime
  enforcement. In particular, `low_risk_auto` grants no ability to act and `is_paused=false`
  starts nothing.
- Leave all existing action-proposal and approval-decision requirements unchanged. Do not alter
  `requires_approval`, high-risk approval rules, proposal status, approval decisions, execution
  transitions, or external behavior.
- Do not add list/delete behavior, enforcement middleware, agents, workers, jobs, recommendations,
  integrations, frontend behavior, network calls, or external actions.
- Do not change authentication, authorization, permissions, tenant-context architecture, billing,
  secrets, production infrastructure, deployment behavior, or protected product, architecture,
  goal, or decision documents.

## Verification Gates
- Deterministic tests must cover strict enum and boolean validation, create/get/patch lifecycle,
  default-paused behavior at application/model/database layers, explicit pause/unpause, duplicate
  and concurrent creation, unsupported route absence, stable response fields, and structured
  validation/conflict/not-found behavior.
- Tenant-isolation tests must cover header/path mismatch, missing and cross-tenant workspaces and
  policies, indistinguishable not-found responses, tenant-scoped queries, and direct database
  bypass of the composite ownership constraint.
- PostgreSQL tests must prove the enum constraint, non-null `is_paused`, database default `true`,
  one-policy cardinality, and same-tenant ownership where SQLite cannot provide equivalent proof.
- Transaction/audit tests must prove exactly one typed, attributed, value-redacted audit per
  successful mutation; explicitly supplied field names only; no implicit `is_paused` audit field
  on create omission; no audit for reads/failures; and no partial state after flush/commit failure.
- Regression tests must prove proposal, approval, risk, and execution behavior remains unchanged
  and that no autonomy preference is consumed for enforcement or causes external behavior.
- Inspect Alembic upgrade/downgrade SQL and exercise upgrade, downgrade, and re-upgrade in a
  disposable PostgreSQL database. Upgrade adds only the policy table and required constraints;
  downgrade removes only `workspace_autonomy_policies`.
- Run focused PRODUCT-003 tests, the full pytest suite, Ruff lint and format checks, strict mypy,
  pip-audit, `make check`, and `git diff --check` without bypassing failures.
- Confirm only issue-authorized implementation files change, tenant boundaries and existing
  approval semantics remain intact, rollback/recovery guidance is complete, and a separate
  read-only reviewer reports zero blocking findings.
- Deliver implementation from a dedicated task branch through a draft pull request. Do not merge
  or deploy.

## Rollback and Recovery
Application rollback while retaining `workspace_autonomy_policies` is preferred: revert or
disable the PRODUCT-003 API paths so no new preference writes occur while preserving the additive
table and stored customer preferences. Because PRODUCT-003 has no enforcement behavior, retaining
the table cannot authorize or trigger actions.

Only in a disposable development database may the PRODUCT-003 revision be downgraded to drop
`workspace_autonomy_policies`, then re-upgraded after correction. Downgrade deletes all stored
autonomy preferences. Before any approved downgrade against meaningful shared or production data,
obtain explicit approval, take and verify a backup, and document and test recovery.
