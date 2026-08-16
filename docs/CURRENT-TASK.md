# Current Task

## Task ID

PRODUCT-005 ([GitHub issue #52](https://github.com/rajeshkamalwar/Growth-OS/issues/52))

## Authorization

Add a durable, tenant-scoped catalog of customer-supplied competitor identities and notes. Follow
the reviewed implementation specification in [`plans/PRODUCT-005.md`](../plans/PRODUCT-005.md);
issue #52 remains the authoritative runtime contract. If implementation requires a design change,
update and review the specification before changing runtime code.

This current-task update authorizes implementation of PRODUCT-005 after this planning change is
merged. It does not queue controller work, authorize deployment, or authorize applying the
`codex-ready` label to issue #52. The orchestrator owns that label only after it re-inspects the
resulting `main`.

## Goal

Add the `workspace_competitors` table and `WorkspaceCompetitor` model with required trimmed `name`,
nullable HTTP(S) `website_url`, nullable `notes`, exact-name uniqueness within each tenant/workspace,
and a same-tenant composite foreign key to the owning workspace. Expose only:

```text
POST  /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors/{competitor_id}
PATCH /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors/{competitor_id}
```

The list uses `limit` default 50, minimum 1, maximum 100, and `offset` default 0, minimum 0. Order is
always ascending `(created_at, id)`. POST returns 201; list/get/PATCH return 200. There is no delete.

## Fixed Data and Validation Contract

- `name`: required string, whitespace-trimmed before validation and persistence, length 1..200
  after trimming, never nullable. Uniqueness is exact persisted-name equality on
  `(tenant_id, workspace_id, name)`; it is case-sensitive and performs no case folding.
- `website_url`: optional nullable string, maximum 2048 characters, and when non-null must be a
  normalized absolute `http://` or `https://` URL with a host. Omission on POST stores null;
  omission on PATCH preserves the value; explicit PATCH null clears it.
- `notes`: optional nullable string, whitespace-trimmed and length 1..4000 when non-null. Omission
  on POST stores null; omission on PATCH preserves the value; explicit PATCH null clears it.
  Empty or whitespace-only notes are invalid.
- `actor_id`: optional UUID request-only audit attribution. It is never returned or persisted on
  the competitor and does not count as a PATCH change.
- POST accepts `name`, `website_url`, `notes`, and `actor_id`. PATCH accepts those fields but must
  explicitly supply at least one of `name`, `website_url`, or `notes`; explicit null is invalid only
  for `name`. Unknown fields and invalid/coerced types use the established structured validation
  response.
- Responses contain exactly `id`, `tenant_id`, `workspace_id`, `name`, `website_url`, `notes`,
  `created_at`, and `updated_at`. Lists use the established `Page` shape with `items` and nested
  `pagination` containing `limit`, `offset`, and `total`.

## Ownership, Persistence, and Error Contract

Every operation requires the existing `X-Tenant-ID` context to match the path tenant, validates the
workspace through the existing tenant-scoped ownership path, and scopes competitor reads by
tenant, workspace, and competitor ID. Missing and cross-tenant resources use the same established
structured `not_found` response. Duplicate create and name-conflicting PATCH map to the established
structured `conflict` response without database details.

Successful POST and PATCH each atomically persist the competitor mutation and exactly one redacted
audit event. Events are `workspace_competitor.created` and `workspace_competitor.updated`, resource
type is `workspace_competitor`, resource ID is the competitor ID, and details are exactly:

```python
{
    "workspace_id": str(workspace_id),
    "changed_fields": sorted(explicitly_supplied_competitor_fields),
}
```

Audit details never contain names, URLs, notes, or other field values. `actor_id` is attribution
only and is excluded from `changed_fields`. Reads, validation failures, not-found operations,
conflicts, and rolled-back mutations emit no audit. Every flush or commit failure rolls back so
competitor and audit state remain atomic.

## Non-Action Boundary

This is inert customer-supplied product memory. Stored competitor data grants no permission and
triggers no connector, job, proposal, monitoring, recommendation, discovery, crawl, inference,
outreach, backlink activity, network call, execution activity, or other external behavior. Do not
read this table from any existing execution, approval, connector, worker, or agent path.

## Implementation Constraints

- Extend the existing explicit SQLAlchemy model, Alembic migration, strict Pydantic schema,
  `FoundationRepository`, `FoundationService`, structured-error, tenant-context, foundation-router,
  and append-only audit patterns. Do not introduce a generic CRUD abstraction or dependency.
- Add an additive table only. Use a composite foreign key from `(workspace_id, tenant_id)` to
  `workspaces(id, tenant_id)` with `ON DELETE RESTRICT`; unique
  `(tenant_id, workspace_id, name)`; non-null name; nullable URL/notes; and database length/nonblank
  checks matching the API bounds. Add no redundant index.
- Repository behavior is explicit: scoped get by all three identities and scoped bounded list/count
  by tenant/workspace in `(created_at, id)` order. Service behavior validates the parent first,
  maps integrity conflicts safely, and rolls back every persistence failure.
- Add no DELETE, discovery, crawling, inference, connector, job, proposal, monitoring,
  recommendation, outreach, backlink, network, execution, frontend, or external behavior.
- Update README with only the authorized endpoint examples, inert catalog semantics, and safe
  application-first recovery guidance.
- Do not change authentication, authorization, permissions, tenant-context architecture, billing,
  secrets, production infrastructure, deployment behavior, or protected product, architecture,
  goal, or decision documents.

## Verification Gates

- Test strict create/PATCH validation, trim and length bounds, HTTP(S)-only URL behavior, null and
  omission semantics, exact-name conflict behavior, exact response fields, pagination bounds and
  metadata, and deterministic `(created_at, id)` ordering.
- Test header/path mismatch, missing/cross-tenant workspace and competitor access, same IDs/names
  in other scopes, composite ownership, direct database constraints, and non-disclosing errors.
- Test exact redacted audit types/details/attribution and atomic rollback on flush, commit, and
  integrity failures. Prove reads and every failure create no audit.
- Prove route boundaries and absence of DELETE, plus the full non-action boundary.
- Inspect migration SQL and exercise upgrade/downgrade/re-upgrade on disposable PostgreSQL. Run
  focused tests, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, and
  `git diff --check` without bypassing failures.
- Confirm only issue-authorized implementation files change, tenant boundaries remain intact,
  rollback guidance is complete, and a separate read-only reviewer reports zero blocking findings.
- Deliver implementation from a dedicated task branch through a draft pull request. Do not merge
  or deploy.

## Rollback and Recovery

Before downgrade, stop writes and back up/export any `workspace_competitors` rows that must be
retained. Prefer reverting the PRODUCT-005 application code and README while retaining the additive
table and its data. Downgrade only on a disposable or explicitly approved database; the downgrade
drops `workspace_competitors` and therefore deletes its rows. Restore data only after reapplying the
migration and validating tenant/workspace ownership and exact-name uniqueness. Never downgrade
production or meaningful shared data without explicit approval and a verified backup.

For this planning-only authorization change, revert its documentation commit to restore PRODUCT-004
as the recorded current task and remove the unimplemented PRODUCT-005 plan. That rollback has no
runtime, schema, data, production, or external effect.
