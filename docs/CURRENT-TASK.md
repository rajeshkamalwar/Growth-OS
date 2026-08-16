# Current Task

## Task ID
PRODUCT-001 ([GitHub issue #32](https://github.com/rajeshkamalwar/Growth-OS/issues/32))

## Authorization
Add the first durable customer business-memory capability: one business profile per workspace,
stored in PostgreSQL and exposed through strict tenant-scoped create, get, and patch APIs.

## Goal
Persist user/provider-supplied company, products/services, audience, positioning, and brand
context for future growth capabilities without adding external side effects or treating profile
claims as measured evidence.

## Required Outcome
- Add one additive migration and SQLAlchemy model for a bounded, structured
  `workspace_business_profiles` table with UUID/timestamps and at most one profile per
  tenant/workspace.
- Enforce the workspace's same-tenant ownership in both service checks and a composite database
  foreign key. Missing and cross-tenant workspaces/profiles both return `not_found`.
- Provide strict create, response, and partial-update schemas. Creation requires a non-blank
  company name; patch requires at least one profile-field change; unknown, blank, and oversized
  values are rejected.
- Expose `POST`, `GET`, and `PATCH` at
  `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile`; duplicate creation
  returns the established structured conflict response.
- Commit create/update atomically with exactly one append-only
  `workspace_business_profile.created` or `workspace_business_profile.updated` audit event.
  Audit details contain only `workspace_id` and sorted `changed_fields`; optional
  provider-neutral `actor_id` is attribution, never profile data. GET and failed mutations add no
  audit event.
- Follow the committed feature specification in [`plans/PRODUCT-001.md`](../plans/PRODUCT-001.md)
  and update that specification before implementation if the design changes.

## Constraints
- Do not add authentication, authorization, deletion, profile versions, embeddings, goals,
  competitors, sites, connectors, agents, crawling, analytics, reports, recommendations,
  frontend work, background workers, network calls, or other external/customer-facing effects.
- Do not change the existing tenant-context boundary, billing, secrets, production
  infrastructure, deployment behavior, or protected product/architecture/goal documents.
- Do not add destructive or data-rewriting migrations. The authorized downgrade drops only the
  new table and is limited to disposable development unless meaningful profile data has an
  approved backup and recovery plan.
- Treat issue #32 as the authoritative detailed implementation contract.

## Completion Gates
- Migration, database, service, and API tests cover constraints, tenant isolation, lifecycle,
  partial updates, duplicate/concurrent creation, strict validation, transaction rollback, audit
  attribution/redaction, read-only GET/failed operations, and existing behavior regression.
- Ruff lint/format, strict mypy, pytest, pip-audit, Alembic upgrade/downgrade SQL validation, and
  `git diff --check` pass.
- Migration/recovery notes distinguish reverting application code while retaining data from a
  downgrade that deletes profile data and requires backup/approval outside disposable
  development.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a draft pull request.
