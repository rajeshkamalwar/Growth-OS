# Current Task

## Task ID
PRODUCT-002 ([GitHub issue #36](https://github.com/rajeshkamalwar/Growth-OS/issues/36))

## Authorization
Add one durable primary goal per workspace, stored in PostgreSQL and exposed through strict,
tenant-scoped create, get, and patch APIs.

## Goal
Persist a required bounded objective plus an optional bounded success definition and target date
as user/provider-supplied intent for future control-plane capabilities. Goal content is not
measured evidence and this milestone does not execute, measure, recommend, or contact anything.

## Required Outcome
- Add one additive migration and `WorkspacePrimaryGrowthGoal` SQLAlchemy model for a bounded
  `workspace_primary_growth_goals` table with
  UUID/timestamps and exactly zero or one primary goal per tenant/workspace.
- Require a non-blank objective on create. Permit an optional success definition and target date;
  expose strict create, response, and partial-update schemas with no delete operation.
- Enforce the workspace's same-tenant ownership through service checks and a composite database
  foreign key. Missing and cross-tenant workspaces or primary growth goals both return `not_found`.
- Expose `POST`, `GET`, and `PATCH` at
  `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/primary-growth-goal`; duplicate creation
  returns the
  established structured conflict response.
- Commit create/update atomically with exactly one append-only
  `workspace_primary_growth_goal.created` or `workspace_primary_growth_goal.updated` audit event.
  Audit details contain only `workspace_id` and sorted
  `changed_fields`; optional provider-neutral `actor_id` is attribution. Goal values must never
  appear in audit details. GET and failed mutations add no audit event.
- Follow the reviewed specification in [`plans/PRODUCT-002.md`](../plans/PRODUCT-002.md) and
  update that specification before implementation if the design changes.

## Constraints
- Do not add deletion, goal history/versions, status/progress, execution linkage, measurements,
  evidence records, agents, recommendations, integrations, background work, network calls,
  frontend work, or other external/customer-facing behavior.
- Do not treat a supplied objective, success definition, or target date as observed or verified
  evidence. Do not copy goal values into audits or logs.
- Do not change authentication, authorization, tenant-context boundaries, billing, secrets,
  dependencies, production infrastructure, deployment behavior, or protected
  product, architecture, goal, or decision documents.
- Do not add destructive or data-rewriting migrations. Application rollback retaining the table
  is preferred. The authorized downgrade drops only the new table and deletes goal data, so it is
  limited to disposable development unless meaningful data has an approved backup and recovery
  plan.
- Treat issue #36 as the authoritative detailed implementation contract.

## Specification Correction

Issue #36 remains authoritative. PLANNING-003 corrects superseded names and the
`success_definition` bound before PRODUCT-002 is queued; no runtime implementation occurred under
the superseded names.

## Completion Gates
- Migration, database, schema, service, and API tests cover constraints, tenant isolation,
  lifecycle, partial updates, duplicate/concurrent creation, strict validation, transaction
  rollback, audit attribution/redaction, read-only GET/failed operations, and regressions.
- Ruff lint/format, strict mypy, pytest, pip-audit, Alembic upgrade/downgrade SQL validation,
  disposable PostgreSQL migration exercise where available, and `git diff --check` pass.
- Documentation clearly distinguishes supplied intent from measured evidence and records the
  data-preserving application rollback and data-deleting downgrade behavior.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
