# PRODUCT-001: Durable Workspace Business Profile

## Status and Authority

This is the implementation specification for PRODUCT-001. The authoritative detailed contract
is [GitHub issue #32](https://github.com/rajeshkamalwar/Growth-OS/issues/32). If implementation
requires a design change, update and review this specification before changing runtime code.

## Objective

Create the first durable customer business-memory capability: at most one tenant-safe business
profile per workspace. Once created, a client can retrieve and partially update bounded company,
products/services, audience, positioning, and brand context. PostgreSQL remains the operational
source of truth. Successful mutations are auditable and atomic; reads and failures have no audit
side effect.

The profile is user/provider-supplied operational context for future growth capabilities. It is
not measured performance evidence, and this milestone neither consumes it in agents nor causes
external actions.

## Detected Stack and Versions

- Python: project requires `>=3.12`; local virtual environment is Python 3.12.13.
- API and validation: FastAPI `>=0.115,<1` and Pydantic Settings `>=2.6,<3` (Pydantic is provided
  by FastAPI).
- Persistence: SQLAlchemy asyncio `>=2.0,<3`, asyncpg `>=0.29,<1`, Alembic `>=1.13,<2`; local
  Alembic is 1.19.1.
- Database: PostgreSQL 16 (`postgres:16-alpine` in `compose.yaml`); SQLite/aiosqlite supports
  isolated tests where PostgreSQL-specific behavior is not required.
- Quality tools: Ruff `>=0.8,<1` (local 0.16.3), strict mypy `>=1.13,<2` (local 1.20.2), pytest
  `>=9.0.3,<10` (local 9.1.1), pytest-asyncio `>=1.3,<2`, and pip-audit `>=2.7,<3` (local 2.10.1).
- Packaging/build: hatchling; application package is `src/growth_os`.

Dependency ranges in `pyproject.toml` are authoritative; local exact versions record the detected
planning environment and are not a request to pin or change dependencies.

## Repository Commands

Run from the repository root. These commands are complete and executable.

```bash
# One-time environment and editable package build/install
make install

# Start PostgreSQL and apply migrations
docker compose up -d db
make migrate

# Run the development API
make dev

# Focused and full tests
.venv/bin/pytest tests/api/test_business_profiles.py tests/db/test_business_profile_constraints.py
GROWTH_OS_TEST_DATABASE_URL='postgresql+asyncpg://<user>:<password>@<host>/<disposable-db>' \
  .venv/bin/pytest tests/db/test_business_profile_constraints.py -k postgresql
.venv/bin/pytest

# Lint, formatting verification, and strict typing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

# Dependency security audit
.venv/bin/pip-audit

# Render migration SQL in both directions for review
.venv/bin/alembic upgrade head --sql > /tmp/product-001-upgrade.sql
.venv/bin/alembic downgrade head:20260816_0002 --sql > /tmp/product-001-downgrade.sql

# Apply and reverse the new revision only in a disposable development database
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head

# Aggregate existing checks and final diff hygiene
make check
git diff --check
git status --short
```

Do not run the downgrade against meaningful shared or production data without explicit approval,
a verified backup, and a recovery plan. After the PRODUCT-001 migration exists, its revision must
directly follow `20260816_0002`, making the offline downgrade range above deterministic.

## Affected Project Structure

```text
docs/CURRENT-TASK.md                         current PRODUCT-001 authorization
plans/PRODUCT-001.md                         this pre-implementation specification
README.md                                    endpoint and migration/recovery usage
migrations/versions/<revision>_business_profile.py
                                               additive profile-table migration
src/growth_os/db/models.py                   WorkspaceBusinessProfile model
src/growth_os/api/schemas.py                 strict create/patch/response contracts
src/growth_os/repositories.py                tenant/workspace-scoped persistence queries
src/growth_os/services.py                    lifecycle and atomic audit orchestration
src/growth_os/api/foundation.py              tenant-scoped POST/GET/PATCH routes
tests/api/test_business_profiles.py          API lifecycle, validation, and audit behavior
tests/db/test_business_profile_constraints.py database constraints and transaction rollback
```

Existing modules remain explicit rather than introducing a new framework or abstraction for one
resource. Test filenames may be consolidated if the same coverage is clearer in existing suites.

## Data and API Contract

The additive `workspace_business_profiles` table contains:

- mixin-provided UUID `id`, `created_at`, and `updated_at`;
- required UUID `tenant_id` and `workspace_id`;
- required `company_name` as `String(200)`;
- nullable `business_description`, `products_services`, `target_audience`, `positioning`, and
  `brand_voice`, each as `String(4000)`.

Database constraints comprise a composite foreign key from `(workspace_id, tenant_id)` to the
same columns on `workspaces`, `ON DELETE RESTRICT`, plus uniqueness on
`(tenant_id, workspace_id)`. Add only indexes needed for tenant/workspace lookup; the unique
constraint may satisfy the combined lookup. The migration creates only this table, its
constraints, and necessary indexes. Downgrade drops only this table.

Endpoints:

```text
POST  /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile
PATCH /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/business-profile
```

All operations first validate the parent workspace using both tenant and workspace identity.
Missing and cross-tenant workspaces or profiles return the same structured `not_found`. Duplicate
create returns the existing structured `conflict`. The response has stable UUID/timestamp,
tenant/workspace, and profile fields.

Create accepts required `company_name`, the optional narrative fields, and optional `actor_id`.
Patch accepts optional profile fields and optional `actor_id`, but must include at least one
profile field; actor attribution alone is not an update. Unknown fields are forbidden. Supplied
strings are whitespace-stripped, non-blank, and bounded to 200 or 4,000 characters as applicable.
Omitted patch fields remain unchanged; explicit `null` may clear an optional narrative field but
cannot clear `company_name`.

Create and patch each add exactly one audit event in the same database transaction:

```text
workspace_business_profile.created
workspace_business_profile.updated
```

The event uses resource type `workspace_business_profile`, the profile ID as `resource_id`, and
optional `actor_id` for provider-neutral attribution. `details` is exactly the workspace identity
and alphabetically sorted supplied profile-field names:

```python
details = {
    "workspace_id": str(workspace_id),
    "changed_fields": sorted(changes),
}
```

No profile value is copied into audit details. GET creates no audit event. Any failed create or
patch rolls back both profile state and audit state.

## Representative Code Style

Follow existing typed SQLAlchemy, strict Pydantic, service/repository, and tenant-context patterns.
Ruff owns formatting at a 100-character line length. Public function signatures are fully typed,
UUIDs remain UUIDs internally, and validation belongs at the API boundary plus invariant-enforcing
database constraints.

```python
class BusinessProfilePatch(StrictInput):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    business_description: str | None = Field(default=None, min_length=1, max_length=4000)
    actor_id: UUID | None = None

    @model_validator(mode="after")
    def includes_profile_change(self) -> "BusinessProfilePatch":
        supplied = self.model_fields_set - {"actor_id"}
        if not supplied:
            raise ValueError("At least one profile field must be updated")
        if "company_name" in supplied and self.company_name is None:
            raise ValueError("Company name cannot be cleared")
        return self
```

The implementation may name schemas consistently with nearby resources, but must preserve this
behavior. Do not add generic CRUD machinery, a JSON profile blob, or a new dependency.

## Testing Strategy

- Schema/unit validation: create requires company name; patch requires a profile field; unknown,
  empty, whitespace-only, oversized, invalid UUID, and invalid-null inputs return the existing
  structured validation shape. Verify optional fields can be incrementally supplied and cleared.
- API lifecycle: create returns 201 and stable response fields; get returns the same profile;
  patch changes only supplied fields; duplicate and concurrent creation conflict; a missing
  profile is `not_found`.
- Tenant isolation: header/path mismatch, missing workspace, cross-tenant workspace, and
  cross-tenant profile access are indistinguishable as `not_found` for every method.
- Database contract: uniqueness enforces one profile per tenant/workspace, and the composite
  foreign key rejects a cross-tenant reference even when service checks are bypassed. PostgreSQL
  integration coverage is required for constraints SQLite cannot faithfully prove.
- Audit/transactions: successful create/update produces exactly one correctly typed and
  attributed event with sorted field names and workspace ID but no profile text. GET and failed
  mutations add none. Forced commit/flush failure leaves neither partial profile changes nor an
  audit row.
- Migration: inspect generated upgrade/downgrade SQL; exercise upgrade, downgrade, and re-upgrade
  on disposable PostgreSQL. Confirm upgrade adds only the intended table/constraints/indexes and
  downgrade removes only it.
- Regression: run the full pytest suite to preserve foundation, execution, retry, proposal,
  approval, history, audit, handoff, health, and configuration behavior.

No arbitrary coverage percentage is introduced; issue #32's named contracts and failure modes
must have deterministic assertions.

## Boundaries

### Always

- Keep every query and parent lookup explicitly tenant-scoped.
- Enforce same-tenant workspace ownership and one-profile uniqueness in PostgreSQL as well as the
  service layer.
- Use bounded structured columns and strict request schemas.
- Commit each mutation and its single redacted append-only audit event atomically.
- Map missing/cross-tenant resources and uniqueness failures to existing structured errors.
- Update this specification first if the design changes; run every completion gate before the
  draft PR; keep the change reversible and auditable.

### Ask First

- Any change to authentication/authorization, permissions, or the tenant-context architecture.
- Any destructive or data-rewriting migration, or downgrade against meaningful data.
- Any new dependency, protected source-of-truth document change, production/deployment change,
  secret handling, external integration, or customer-facing side effect.
- Any expansion beyond the profile fields and endpoints authorized by issue #32.

### Never

- Add deletion, history snapshots, embeddings/pgvector, LLM behavior, goals, competitors, sites,
  connectors, agents, crawling, analytics, reports, recommendations, frontend work, workers, or
  network calls in this milestone.
- Store profile content in audit details, logs, evidence claims, or actor identity fields.
- Reveal whether a cross-tenant resource exists, weaken database constraints, bypass failing
  gates, deploy, modify production, delete meaningful data, or commit secrets.

## Fixed Assumptions and Resolved Questions

- Cardinality: at most one profile per workspace, scoped by tenant.
- Provenance: profile text is supplied operational context, not verified performance evidence.
- Shape: bounded columns are preferred to an unvalidated JSON blob.
- Required data: create requires `company_name`; other context is incremental.
- Patch semantics: at least one profile field must be supplied; omitted fields are unchanged and
  optional narrative fields may be explicitly cleared with `null`.
- Audit privacy: record sorted changed field names and workspace identity, never values.
- Attribution: optional `actor_id` is provider-neutral audit attribution and is not profile data.
- Deletion and auth: neither is part of this milestone; the existing tenant boundary is unchanged.
- Architecture: use the existing explicit repository/service/API layers and append-only audit
  table. No new abstraction or contract document is needed beyond this specification and README.

## Success Criteria

- A workspace can create at most one durable profile and, once created, retrieve and partially
  update it through the three tenant-scoped endpoints with stable response fields.
- Strict validation, conflict handling, missing/cross-tenant non-disclosure, and direct database
  constraints behave exactly as issue #32 requires.
- Each successful mutation atomically emits one attributed, redacted audit event; GET and all
  failed operations are audit-read-only.
- The migration is additive and limited to the profile table, same-tenant constraint, uniqueness,
  and necessary indexes; downgrade removes only the new table.
- Tests cover schema constraints, isolation, lifecycle, concurrency, validation, rollback, audit
  attribution/redaction, and regressions.
- Ruff lint/format, strict mypy, pytest, pip-audit, bidirectional migration SQL validation,
  disposable-database migration exercise, and `git diff --check` pass.
- A separate read-only reviewer reports zero blocking findings, and a draft PR from the dedicated
  task branch is ready for review.

## Rollback and Recovery

Code rollback and database downgrade are deliberately separate:

1. Revert the PRODUCT-001 application commit or disable the routes to stop new profile operations
   while retaining the additive table and all profile data. This is the preferred rollback for a
   shared or production database.
2. Only in a disposable development database, downgrade one revision to drop
   `workspace_business_profiles`, then re-upgrade after correction.
3. A downgrade deletes all stored profile data. For any meaningful shared or production data,
   preserve the table or obtain explicit approval, take and verify a backup, and document/test the
   recovery procedure before an approved downgrade.

PLANNING-001 itself is documentation-only and can be rolled back by reverting its documentation
commit; it has no runtime or data rollback.

## Open Questions

None. Issue #32 fixes the milestone's product, API, persistence, audit, isolation, and rollback
boundaries. Any newly discovered question that changes those contracts must pause implementation
and be resolved in this specification first.
