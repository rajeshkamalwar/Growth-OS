# PRODUCT-002: Durable Workspace Primary Goal

## Status and Authority

This is the reviewed pre-implementation specification for PRODUCT-002. The authoritative issue
contract is [GitHub issue #36](https://github.com/rajeshkamalwar/Growth-OS/issues/36). Issue #37
authorizes this specification and the corresponding current-task update; it does not authorize
runtime implementation. If implementation requires a design change, update and review this
specification before changing runtime code.

## Objective

Add one durable primary goal per workspace. A client can create, retrieve, and partially update a
required bounded objective, an optional bounded success definition, and an optional target date.
PostgreSQL remains the operational source of truth. Each successful mutation and its redacted
audit event commit atomically; reads and failures have no audit side effect.

Goal content records user/provider-supplied intent. It is neither measured evidence nor proof of
progress, attainment, attribution, or business performance. This focused vertical slice stores
and retrieves intent only; it does not execute work, collect measurements, invoke agents, produce
recommendations, connect integrations, or cause external behavior.

## Detected Stack and Versions

- Python: project requires `>=3.12`; local virtual environment is Python 3.12.13.
- API and validation: FastAPI `>=0.115,<1` and Pydantic Settings `>=2.6,<3` (Pydantic is supplied
  through FastAPI).
- Persistence: SQLAlchemy asyncio `>=2.0,<3`, asyncpg `>=0.29,<1`, Alembic `>=1.13,<2`; local
  Alembic is 1.19.1.
- Database: PostgreSQL 16 (`postgres:16-alpine` in `compose.yaml`); SQLite/aiosqlite supports
  isolated tests where PostgreSQL-specific behavior is not required.
- Quality tools: Ruff `>=0.8,<1` (local 0.16.3), strict mypy `>=1.13,<2` (local 1.20.2), pytest
  `>=9.0.3,<10` (local 9.1.1), pytest-asyncio `>=1.3,<2`, and pip-audit `>=2.7,<3` (local 2.10.1).
- Packaging/build: hatchling; the application package is `src/growth_os`.

Dependency ranges in `pyproject.toml` are authoritative. The detected exact versions document the
planning environment and do not authorize dependency changes.

## Complete Executable Commands

Run from the repository root.

```bash
# One-time environment and editable package build/install
make install

# Start PostgreSQL and apply migrations
docker compose up -d db
make migrate

# Run the development API
make dev

# Focused and full tests
.venv/bin/pytest tests/api/test_workspace_goals.py tests/db/test_workspace_goal_constraints.py
GROWTH_OS_TEST_DATABASE_URL='postgresql+asyncpg://<user>:<password>@<host>/<disposable-db>' \
  .venv/bin/pytest tests/db/test_workspace_goal_constraints.py -k postgresql
.venv/bin/pytest

# Lint, formatting verification, and strict typing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

# Dependency security audit
.venv/bin/pip-audit

# Render the PRODUCT-002 migration in both directions for review
.venv/bin/alembic upgrade 20260816_0003:head --sql > /tmp/product-002-upgrade.sql
.venv/bin/alembic downgrade head:20260816_0003 --sql > /tmp/product-002-downgrade.sql

# Apply, reverse, and reapply only the new revision in a disposable development database
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head

# Aggregate repository checks and final diff hygiene
make check
git diff --check
git status --short
```

Do not downgrade a database containing meaningful shared or production goal data without explicit
approval, a verified backup, and a tested recovery plan. The new migration must directly follow
`20260816_0003`, so the offline downgrade range is deterministic.

## Affected Project Structure

```text
docs/CURRENT-TASK.md                         active PRODUCT-002 authorization
plans/PRODUCT-002.md                         this reviewed implementation specification
README.md                                    goal endpoint and rollback guidance
migrations/versions/<revision>_workspace_goals.py
                                               additive goal-table migration
src/growth_os/db/models.py                   WorkspaceGoal model
src/growth_os/api/schemas.py                 strict create/patch/response schemas
src/growth_os/repositories.py                tenant/workspace-scoped goal query
src/growth_os/services.py                    lifecycle and atomic audit transaction
src/growth_os/api/foundation.py              tenant-scoped POST/GET/PATCH routes
tests/api/test_workspace_goals.py            API, validation, isolation, and audit behavior
tests/db/test_workspace_goal_constraints.py  database constraints and rollback behavior
```

Existing explicit modules and patterns are sufficient. Do not add a generic CRUD framework, a
new service layer, or a dependency for this single resource. Test cases may be consolidated into
nearby suites if all named behavior remains clear and deterministic.

## Data Contract

Create an additive `workspace_goals` table containing:

- mixin-provided UUID `id`, timezone-aware `created_at`, and timezone-aware `updated_at`;
- required UUID `tenant_id` and `workspace_id`;
- required `objective` as `String(2000)`;
- nullable `success_definition` as `String(4000)`;
- nullable `target_date` as SQL `Date`.

Use a composite foreign key from `(workspace_id, tenant_id)` to the same columns on `workspaces`,
with `ON DELETE RESTRICT`, and a unique constraint on `(tenant_id, workspace_id)`. These enforce
same-tenant ownership and at most one primary goal per workspace. The unique constraint may serve
the combined lookup; add no redundant index. The migration creates only the table, its constraints,
and any demonstrably necessary indexes. Its downgrade drops only `workspace_goals`.

`target_date` is a calendar date serialized as ISO `YYYY-MM-DD`, not a timestamp. Past, present,
and future dates are valid: the persistence API records supplied intent and must not silently
reinterpret or reject an existing business target based on the server clock.

## API Contract

```text
POST  /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/goal
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/goal
PATCH /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/goal
```

All methods require the existing `X-Tenant-ID` context to match the path tenant. All operations
validate the parent workspace by both tenant and workspace identity. Missing and cross-tenant
workspaces or goals return the same established structured `not_found`; no response reveals
cross-tenant existence. Duplicate and concurrent creation return the established structured
`conflict`. POST returns 201; GET and PATCH return 200. No DELETE or list endpoint is authorized.

Create accepts:

- required `objective`, stripped, non-blank, maximum 2,000 characters;
- optional `success_definition`, stripped, non-blank when non-null, maximum 4,000 characters;
- optional `target_date` as a strict ISO date;
- optional UUID `actor_id`, used only for audit attribution.

Patch accepts the same goal fields as optional plus optional `actor_id`, but must supply at least
one goal field. `actor_id` alone is not a change. Omitted fields remain unchanged. `objective`
cannot be null or blank. Explicit null clears `success_definition` or `target_date`. Unknown
fields, invalid dates/UUIDs, blank strings, and oversized strings are rejected through the
existing structured validation response. The response contains stable ID/timestamps,
tenant/workspace IDs, objective, success definition, and target date; it never includes actor ID.

## Atomic Audit and Repository/Service Behavior

The repository provides one tenant-scoped lookup by `(tenant_id, workspace_id)`. The service:

1. resolves the parent workspace through the existing tenant-safe ownership path;
2. creates or mutates the goal in memory;
3. adds exactly one corresponding append-only audit event;
4. commits both records in one transaction;
5. rolls back the session on integrity or other commit/flush failures; and
6. maps uniqueness violations to `conflict` without leaking database exception text.

Successful mutations emit:

```text
workspace_goal.created
workspace_goal.updated
```

The resource type is `workspace_goal`, resource ID is the goal UUID, and optional `actor_id` is
provider-neutral attribution. Audit `details` is exactly:

```python
details = {
    "workspace_id": str(workspace_id),
    "changed_fields": sorted(changes),
}
```

For create, `changed_fields` contains supplied goal fields only, including the required objective;
for patch, it contains only explicitly supplied goal fields. It excludes `actor_id`. Objective,
success-definition, and target-date values must never be copied into audit details or logs. GET,
validation failures, not-found operations, conflicts, and rolled-back mutations create no audit
event and leave goal state unchanged.

## Representative Code Style

Follow the current typed SQLAlchemy, strict Pydantic, repository/service, structured-error, and
tenant-context patterns. Ruff owns formatting at 100 characters. Keep UUID and date types intact
internally; validate request shape at the API boundary and enforce ownership/cardinality again in
PostgreSQL.

```python
class WorkspaceGoalUpdate(StrictInput):
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    success_definition: str | None = Field(default=None, min_length=1, max_length=4000)
    target_date: date | None = None
    actor_id: UUID | None = None

    @model_validator(mode="after")
    def includes_goal_change(self) -> "WorkspaceGoalUpdate":
        supplied = self.model_fields_set - {"actor_id"}
        if not supplied:
            raise ValueError("At least one goal field must be updated")
        if "objective" in supplied and self.objective is None:
            raise ValueError("Objective cannot be cleared")
        return self
```

Names may be aligned with nearby code while preserving the contract. Do not use a JSON goal blob,
generic CRUD abstraction, status enum, measurement fields, or new dependency.

## Testing Strategy

- Schema validation: create requires objective; patch requires a goal field; reject unknown,
  missing, blank, whitespace-only, oversized, invalid UUID/date, and invalid-null values. Verify
  optional fields can be incrementally set and explicitly cleared.
- API lifecycle: create returns 201 and stable response fields; GET returns the same goal; PATCH
  changes only supplied fields; duplicate and concurrent creation conflict; missing goal is
  `not_found`; unsupported DELETE/list routes do not exist.
- Tenant isolation: header/path mismatch, missing workspace, cross-tenant workspace, and
  cross-tenant goal access are indistinguishable as `not_found` for every authorized method.
- Database contract: uniqueness enforces one goal per tenant/workspace; the composite foreign key
  rejects cross-tenant references even when service checks are bypassed. Run PostgreSQL integration
  coverage for constraints SQLite cannot faithfully prove.
- Audit and transactions: successful create/update emits exactly one correctly typed/attributed
  event with sorted field names and workspace ID. Assert recursively that no goal value appears in
  audit details. GET and every failed mutation add none. Forced flush/commit failure leaves neither
  partial goal changes nor an audit row.
- Intent versus evidence: tests and documentation use supplied/unverified terminology and make no
  progress, attainment, measurement, or attribution claim based on goal fields.
- Migration: inspect upgrade/downgrade SQL; exercise upgrade, downgrade, and re-upgrade on
  disposable PostgreSQL. Upgrade adds only the intended table/constraints/indexes; downgrade
  removes only it.
- Regression: run full pytest coverage to preserve foundation, business-profile, execution,
  proposal, approval, history, audit, handoff, health, and configuration behavior.

No arbitrary coverage percentage is added. Issue #36's named contracts and failure modes require
deterministic assertions.

## Dependency-Ordered Implementation Tasks

### Task 1: Add the migration and model

Create the additive table, matching ORM model, composite ownership constraint, and uniqueness
constraint. It depends only on the existing workspace schema.

Acceptance: metadata and migration agree; upgrade/downgrade SQL is limited to `workspace_goals`;
direct database tests prove one-per-workspace and same-tenant constraints.

Verification: run focused database tests, render both SQL directions, and exercise the migration
round trip on disposable PostgreSQL.

### Task 2: Define strict schemas

Add create, patch, and response schemas with bounded strings, typed date, clearing semantics,
unknown-field rejection, and actor attribution excluded from responses.

Dependencies: Task 1 fixes the persisted field contract.

Acceptance: deterministic schema/API tests cover required, optional, clearable, invalid, and
oversized inputs; actor-only patch is rejected.

Verification: run focused schema/API validation tests plus Ruff and mypy.

### Task 3: Implement repository and service transactions

Add the tenant/workspace-scoped lookup and create/get/update orchestration. Mutations atomically
commit one goal change with one redacted audit event and roll back every failure.

Dependencies: Tasks 1 and 2 define persistence and accepted changes.

Acceptance: lifecycle, conflict/concurrency, rollback, audit count/type/attribution/redaction, and
read-only/failure behavior are proven; no goal value is present in audit details.

Verification: run focused service/API and PostgreSQL constraint tests.

### Task 4: Expose the three API routes

Wire singular POST/GET/PATCH routes through the existing tenant context, repository, service, and
structured error mapping. Add no DELETE or list route.

Dependencies: Task 3 supplies all business behavior.

Acceptance: status codes, response shape, validation, not-found non-disclosure, and duplicate
conflict match this contract for the full request-to-database path.

Verification: run the entire workspace-goal API suite.

### Checkpoint: Focused vertical slice

Run both focused test files together against the completed route-to-database flow. Confirm strict
schema behavior, tenant isolation, parent validation, cardinality, atomic audit redaction,
concurrency handling, and rollback as one coherent slice before documentation or broad gates.

### Task 5: Document usage and recovery

Update README with the endpoint, supplied-intent/evidence distinction, and rollback guidance.

Dependencies: Task 4 establishes the final public behavior.

Acceptance: examples do not imply measurement or execution; application rollback retaining the
table is preferred; downgrade is clearly identified as deleting all goal data.

Verification: inspect rendered Markdown and run documentation checks available in the repository.

### Task 6: Run full verification

Run Ruff lint/format, strict mypy, full pytest, pip-audit, bidirectional Alembic SQL inspection,
the disposable migration round trip, `make check`, `git diff --check`, and final status/diff review.

Dependencies: Tasks 1-5 are complete.

Acceptance: every applicable repository gate passes without bypass; only issue-authorized files
changed; tenant boundaries remain intact; migration rollback/recovery notes are complete.

### Task 7: Obtain independent read-only review

Give a fresh reviewer issue #36, this specification, the final diff, and verification results.
The reviewer must not edit files and must assess correctness, scope, tenant safety, audit privacy,
migration recovery, test sufficiency, and repository governance.

Dependencies: Task 6 provides a stable verified diff.

Acceptance: zero blocking findings. Fix any finding on the task branch, repeat all affected gates,
and request a fresh read-only review before opening/updating the draft PR.

## Three-Tier Boundaries

### Always

- Keep every parent lookup and goal query explicitly tenant/workspace scoped.
- Enforce same-tenant ownership and one-goal cardinality in PostgreSQL and service behavior.
- Use bounded structured columns, strict schemas, and a typed calendar date.
- Atomically commit each mutation with exactly one field-name-only audit event.
- Treat every goal field as supplied intent, not evidence, progress, or outcome.
- Run focused vertical-slice and full repository gates, then independent read-only review.

### Ask First

- Any change to authentication, authorization, permissions, or tenant-context architecture.
- Any destructive/data-rewriting migration or downgrade against meaningful data.
- Any new dependency, protected source-of-truth change, production/deployment change, secret
  handling, integration, network call, or customer-facing side effect.
- Any expansion of the fields, endpoints, cardinality, or semantics fixed by issue #36.

### Never

- Add delete/list, multiple or secondary goals, goal versions/history, status, progress, evidence,
  measurements, execution/job/action linkage, agents, recommendations, integrations, workers,
  frontend behavior, network calls, or external actions in PRODUCT-002.
- Store objective, success-definition, or target-date values in audit details or logs.
- Infer or claim measured success from supplied intent; reveal cross-tenant existence; weaken
  constraints; bypass failing gates; deploy; modify production; delete meaningful data; or commit
  secrets.

## Fixed Assumptions and Resolved Questions

- Cardinality: zero or one primary goal per workspace; create conflicts once one exists.
- Required field: create requires a non-blank objective bounded at 2,000 characters.
- Optional fields: success definition is bounded at 4,000 characters; target date is a date without
  server-clock validation. Explicit null clears either optional field.
- Patch: at least one goal field is supplied; omissions preserve stored values; objective cannot
  be null; actor attribution alone is not a mutation.
- Provenance: all goal content is user/provider-supplied intent, never measured evidence.
- Audit privacy: only workspace ID and alphabetically sorted changed field names are details; goal
  values are forbidden. Optional actor ID is attribution, not goal content.
- Isolation: composite ownership plus tenant-scoped service queries; missing and cross-tenant
  resources share `not_found` behavior.
- API: singular `/goal` has POST/GET/PATCH only. POST is 201; GET/PATCH are 200; duplicates are
  `conflict`.
- Architecture: extend current explicit model/schema/repository/service/router modules and the
  append-only audit ledger. No generic abstraction or dependency is justified.
- Scope: persistence and retrieval only. No delete, measurement, execution, agents, integration,
  recommendations, status/progress, history, or external behavior.

## Success Criteria

- A tenant-safe workspace can create at most one primary goal, then retrieve and partially update
  it through the three strict endpoints with stable typed response fields.
- Required/bounded inputs, optional-field clearing, conflict handling, missing/cross-tenant
  non-disclosure, and direct database constraints behave exactly as specified.
- Each successful mutation atomically emits one attributed, redacted audit event; values never
  enter audit details; GET and all failed operations are audit-read-only.
- Goal data is consistently described as supplied intent and never consumed or reported as
  measured evidence, execution input, recommendation output, or progress.
- The additive migration is limited to the goal table and its ownership/cardinality constraints;
  downgrade removes only the table.
- Deterministic tests cover schema, lifecycle, tenant isolation, concurrency, constraints,
  rollback, audit attribution/redaction, route absence, and existing behavior regressions.
- Every applicable repository gate and migration check passes, a separate read-only reviewer
  reports zero blocking findings, and a draft PR from the dedicated branch is ready for review.

## Risks

- Cross-tenant disclosure or association: mitigate with composite database ownership, scoped
  parent/goal queries, identical not-found responses, and direct bypass tests.
- Duplicate/concurrent creation: enforce uniqueness in PostgreSQL and map the integrity failure to
  the stable conflict response.
- Sensitive intent leaking through audits: construct a fixed details allowlist and assert that no
  supplied goal value appears recursively.
- Partial commit: add goal and audit to one session transaction and roll back all exceptions.
- Intent being mistaken for evidence: use explicit naming/documentation and forbid measurement or
  success claims in this slice.
- Destructive downgrade: prefer application rollback while retaining the additive table and data.

## Rollback and Recovery

Application rollback while retaining `workspace_goals` is preferred: revert or disable the
PRODUCT-002 application paths to stop new goal operations while preserving the additive table and
all stored goal data. This is the safe default for shared or production databases.

Only in a disposable development database, downgrade one revision to drop `workspace_goals`, then
re-upgrade after correction. Downgrade deletes all stored goal data. Before any approved downgrade
against meaningful shared or production data, obtain explicit approval, take and verify a backup,
and document and test recovery.

PLANNING-002 itself is documentation-only. Revert its planning commit to remove this unimplemented
specification and restore PRODUCT-001 as the recorded current task; it has no runtime, schema,
production, or external rollback.

## Open Questions

None. Issue #36 and this reviewed specification resolve the product, API, persistence, audit,
isolation, test, and rollback contracts. Any newly discovered question that would change these
contracts must pause implementation and be resolved here before runtime work continues.
