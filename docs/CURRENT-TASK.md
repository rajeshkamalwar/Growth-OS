# Current Task

## Task ID
PRODUCT-002 ([GitHub issue #36](https://github.com/rajeshkamalwar/Growth-OS/issues/36))

## Authorization
Add one durable primary growth goal per workspace, stored in PostgreSQL and exposed through strict
tenant-scoped create, get, and patch APIs. Follow the reviewed implementation specification in
[`plans/PRODUCT-002.md`](../plans/PRODUCT-002.md); issue #36 remains the authoritative contract.
If implementation requires a design change, update and review the specification before changing
runtime code.

## Goal
Persist a required objective, an optional success definition, and an optional target date as
user/provider-supplied intent. These fields are not measured evidence or proof of progress,
attainment, attribution, or business performance. PRODUCT-002 stores and retrieves intent only;
it does not execute work, collect measurements, invoke agents, produce recommendations, connect
integrations, or cause external behavior.

## Required Outcome
- Add one additive migration and SQLAlchemy model/resource for the bounded, structured
  `workspace_primary_growth_goals` table and
  `WorkspacePrimaryGrowthGoal` / `workspace_primary_growth_goal`.
- Store mixin-provided UUID/timestamps, required tenant/workspace UUIDs, a required stripped,
  non-blank objective bounded to 2,000 characters, an optional stripped, non-blank-when-present
  success definition bounded to 2,000 characters, and an optional ISO calendar `target_date`.
  Past, present, and future target dates are valid.
- Enforce zero or one goal per tenant/workspace with a unique `(tenant_id, workspace_id)`
  constraint and enforce same-tenant workspace ownership with a composite foreign key from
  `(workspace_id, tenant_id)` to `workspaces`, using `ON DELETE RESTRICT`.
- Expose only strict `POST`, `GET`, and `PATCH` at
  `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/primary-growth-goal`. POST returns 201;
  GET and PATCH return 200; duplicate or concurrent creation returns the established structured
  `conflict` response. No DELETE or list endpoint is authorized.
- Require the existing `X-Tenant-ID` context to match the path tenant and scope every parent and
  goal lookup by tenant and workspace. Missing and cross-tenant resources must return the same
  established structured `not_found` response without revealing cross-tenant existence.
- Creation requires `objective`. Patch must supply at least one goal field; `actor_id` alone is
  not a change. Omitted fields remain unchanged, objective cannot be cleared, and explicit null
  clears `success_definition` or `target_date`. Reject unknown fields, invalid dates/UUIDs, blank
  strings, invalid nulls, and oversized strings through the existing structured validation
  response. Never return `actor_id` in the resource response.
- Commit each successful mutation atomically with exactly one append-only
  `workspace_primary_growth_goal.created` or `workspace_primary_growth_goal.updated` audit event.
  Use the goal UUID as resource ID and `workspace_primary_growth_goal` as resource type. Audit
  details contain exactly `workspace_id` and alphabetically sorted supplied `changed_fields`,
  excluding `actor_id`; optional `actor_id` is provider-neutral attribution.
- Never copy objective, success-definition, or target-date values into audits or logs. GET,
  validation failures, not-found operations, conflicts, and rolled-back mutations create no
  audit event and leave goal state unchanged. Roll back the session on every flush/commit failure
  and map uniqueness failures without leaking database exception text.

## Implementation Constraints
- Extend the existing explicit typed SQLAlchemy model, strict Pydantic schema,
  repository/service, router, structured-error, tenant-context, and append-only audit patterns.
  Do not add a generic CRUD framework, JSON goal blob, status enum, new service layer, redundant
  index, or dependency.
- Keep UUID and date types intact internally. Use bounded structured columns, strict schemas, and
  a typed calendar date; enforce ownership and cardinality in both service behavior and
  PostgreSQL.
- Treat all goal content as supplied and unverified intent. Do not describe or consume it as
  evidence, progress, measurement, attribution, recommendation output, or proof of success.
- Do not add delete/list behavior, multiple or secondary goals, versions/history, status,
  progress, evidence, measurements, execution/job/action linkage, agents, recommendations,
  integrations, workers, frontend behavior, network calls, or external actions.
- Do not change authentication, authorization, permissions, tenant-context architecture,
  billing, secrets, production infrastructure, deployment behavior, protected product,
  architecture, goal, or decision documents, or any contract fixed by issue #36 without prior
  approval and specification review.
- Do not perform destructive/data-rewriting migrations, deploy, modify production, delete
  meaningful data, weaken constraints or safety gates, or expose secrets.

## Verification Gates
- Deterministic tests must cover strict schema validation, create/get/patch lifecycle, optional
  field setting and clearing, duplicate/concurrent creation, unsupported route absence, stable
  response fields, and structured validation/conflict/not-found behavior.
- Tenant-isolation tests must cover header/path mismatch, missing and cross-tenant workspaces and
  goals, indistinguishable not-found responses, tenant-scoped queries, and direct database bypass
  of the composite ownership constraint.
- PostgreSQL tests must prove one-goal cardinality and same-tenant ownership where SQLite cannot.
  Transaction/audit tests must prove exactly one typed, attributed, field-name-only redacted audit
  per successful mutation, no audit for reads/failures, and no partial state after forced
  flush/commit failures.
- Tests and documentation must preserve the intent-versus-evidence distinction and make no
  progress, attainment, measurement, performance, or attribution claims from goal fields.
- Inspect Alembic upgrade/downgrade SQL and exercise upgrade, downgrade, and re-upgrade in a
  disposable PostgreSQL database. Upgrade may add only the goal table and required constraints or
  demonstrably necessary indexes; downgrade removes only `workspace_primary_growth_goals`.
- Run focused PRODUCT-002 tests, the full pytest regression suite, Ruff lint and format checks,
  strict mypy, pip-audit, `make check`, and `git diff --check` without bypassing failures.
- Confirm only issue-authorized files changed, tenant boundaries remain intact, rollback/recovery
  guidance is complete, and a separate read-only reviewer reports zero blocking findings.
- Deliver the implementation from a dedicated task branch through a draft pull request.

## Rollback and Recovery
Application rollback while retaining `workspace_primary_growth_goals` is preferred: revert or
disable the PRODUCT-002 application paths to stop new goal operations while preserving the table
and all stored goal data. This is the safe default for shared or production databases.

Only in a disposable development database may the PRODUCT-002 revision be downgraded to drop
`workspace_primary_growth_goals`, then re-upgraded after correction. Downgrade deletes all stored
goal data. Before any approved downgrade against meaningful shared or production data, obtain
explicit approval, take and verify a backup, and document and test recovery.
