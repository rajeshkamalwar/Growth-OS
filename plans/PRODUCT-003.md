# PRODUCT-003: Durable Workspace Autonomy Preferences

## Status and Authority

This is the reviewed pre-implementation specification for PRODUCT-003. The authoritative runtime
contract is [GitHub issue #44](https://github.com/rajeshkamalwar/Growth-OS/issues/44). Issue #45
authorizes this specification and the corresponding current-task update; it does not itself
implement runtime behavior.

After this planning change merges, `docs/CURRENT-TASK.md` authorizes an implementation agent to
execute issue #44. That authorization is not controller queueing and does not authorize applying
`codex-ready`; the orchestrator owns that label only after it re-inspects the resulting `main`.
If implementation requires a design change, update and review this specification before changing
runtime code.

## Objective

Add one durable autonomy preference per workspace. A client can create, retrieve, and partially
update a required `AutonomyLevel` and a strict `is_paused` boolean. New policies are paused by
default. PostgreSQL remains the operational source of truth, and every successful mutation commits
atomically with one redacted audit event.

The policy is stored customer preference only. It is not authentication, authorization, a
permission grant, safety evidence, risk approval, or runtime enforcement. Neither selecting
`low_risk_auto` nor setting `is_paused` to `false` starts a job, approves a proposal, bypasses a
gate, enables an integration, or causes an external action. Existing proposal, approval, risk,
execution, and external-action semantics remain unchanged.

## Detected Stack and Versions

- Python: project requires `>=3.12`; local virtual environment is Python 3.12.13.
- API and validation: FastAPI `>=0.115,<1` and Pydantic Settings `>=2.6,<3` (Pydantic is supplied
  through FastAPI).
- Persistence: SQLAlchemy asyncio `>=2.0,<3`, asyncpg `>=0.29,<1`, and Alembic `>=1.13,<2`;
  local Alembic is 1.19.1.
- Database: PostgreSQL 16 (`postgres:16-alpine` in `compose.yaml`); SQLite/aiosqlite supports
  isolated tests where PostgreSQL-specific constraint behavior is not under test.
- Quality tools: Ruff `>=0.8,<1` (local 0.16.3), strict mypy `>=1.13,<2` (local 1.20.2), pytest
  `>=9.0.3,<10` (local 9.1.1), pytest-asyncio `>=1.3,<2`, and pip-audit `>=2.7,<3` (local 2.10.1).
- Packaging/build: hatchling; the application package is `src/growth_os`.

Dependency ranges in `pyproject.toml` are authoritative. Exact versions describe the planning
environment and do not authorize dependency changes.

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
.venv/bin/pytest tests/api/test_workspace_autonomy_policies.py \
  tests/db/test_workspace_autonomy_policy_constraints.py
GROWTH_OS_TEST_DATABASE_URL='postgresql+asyncpg://<user>:<password>@<host>/<disposable-db>' \
  .venv/bin/pytest tests/db/test_workspace_autonomy_policy_constraints.py -k postgresql
.venv/bin/pytest

# Lint, formatting verification, and strict typing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

# Dependency security audit
.venv/bin/pip-audit

# Render the PRODUCT-003 migration in both directions for review
.venv/bin/alembic upgrade 20260816_0004:head --sql > /tmp/product-003-upgrade.sql
.venv/bin/alembic downgrade head:20260816_0004 --sql > /tmp/product-003-downgrade.sql

# Apply, reverse, and reapply only the new revision in a disposable development database
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head

# Aggregate repository checks and final diff hygiene
make check
git diff --check
git status --short
```

The new migration must directly follow `20260816_0004`; the implementation may choose the next
valid revision identifier while retaining the explicit offline range above. Never downgrade a
database containing meaningful shared or production policy data without explicit approval, a
verified backup, and a tested recovery plan.

## Affected Project Structure

The future issue #44 implementation is expected to affect only the focused vertical slice below;
this issue #45 planning change modifies only `docs/CURRENT-TASK.md` and this file.

```text
migrations/versions/<revision>_workspace_autonomy_policies.py
                                               additive autonomy-policy-table migration
src/growth_os/db/models.py                   AutonomyLevel and WorkspaceAutonomyPolicy
src/growth_os/api/schemas.py                 strict create/patch/response schemas
src/growth_os/repositories.py                tenant/workspace-scoped policy query
src/growth_os/services.py                    lifecycle and atomic audit transaction
src/growth_os/api/foundation.py              tenant-scoped POST/GET/PATCH routes
tests/api/test_workspace_autonomy_policies.py
                                               API, validation, isolation, audit, non-enforcement
tests/db/test_workspace_autonomy_policy_constraints.py
                                               database defaults and constraints
```

Existing explicit modules and patterns are sufficient. Do not add a generic CRUD framework, a new
service layer, a dependency, enforcement middleware, or an execution-path integration. Test cases
may be consolidated into nearby suites if every named behavior remains clear and deterministic.

## Migration and Data Contract

Create an additive `workspace_autonomy_policies` table containing:

- mixin-provided UUID `id`, timezone-aware `created_at`, and timezone-aware `updated_at`;
- required UUID `tenant_id` and `workspace_id`;
- required `level`, represented by `AutonomyLevel` with exactly these serialized values:
  `observe_only`, `recommend_only`, `approval_required`, and `low_risk_auto`;
- required strict boolean `is_paused`, defaulting to `true`.

Use a composite foreign key from `(workspace_id, tenant_id)` to the same columns on `workspaces`,
with `ON DELETE RESTRICT`, and a unique constraint on `(tenant_id, workspace_id)`. These enforce
same-tenant ownership and at most one policy per workspace. The unique constraint serves the
combined lookup; add no redundant index.

The database must independently reject any `level` outside the four serialized values. Use the
existing SQLAlchemy `Enum(..., native_enum=False)` style with an explicitly enabled and named
database check constraint (or an equivalent explicit named `CheckConstraint`) so generated
PostgreSQL DDL and direct-SQL tests prove the bound. `level` is non-null and has no implicit
default: POST must supply it.

`is_paused` is non-null with a database `server_default=true`; the ORM column also uses
`default=True`; and the create schema/application default is `True`. These three layers are
deliberate, testable safe defaults. The persisted response after an omitted create value must be
`is_paused: true` regardless of whether creation uses the API, the ORM default, or a direct insert
that relies on the database default.

The migration creates only this table and its required constraints. Its downgrade drops only
`workspace_autonomy_policies`. It does not backfill, rewrite, or consume existing data.

## API Contract

```text
POST  /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy
PATCH /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/autonomy-policy
```

All methods require the existing `X-Tenant-ID` context to match the path tenant. Every operation
validates the parent workspace by tenant and workspace identity. Missing and cross-tenant
workspaces or policies return the same established structured `not_found`; no response reveals
cross-tenant existence. Duplicate and concurrent creation return the established structured
`conflict`. POST returns 201; GET and PATCH return 200. No DELETE or list endpoint is authorized.

POST accepts:

- required `level` as one of the four exact `AutonomyLevel` values;
- optional strict boolean `is_paused`, defaulting to `true` when omitted;
- optional UUID `actor_id`, used only for audit attribution.

PATCH accepts optional `level`, optional strict boolean `is_paused`, and optional UUID `actor_id`,
but must include at least one policy field. `actor_id` alone is not a change. Omitted policy fields
remain unchanged. Explicit null is invalid for both `level` and `is_paused`. Reject unknown fields,
invalid enum strings, integers or strings supplied as booleans, invalid UUIDs, and invalid nulls
through the established structured validation response.

The response contains stable `id`, `created_at`, `updated_at`, `tenant_id`, `workspace_id`, `level`,
and `is_paused` fields. It never contains `actor_id`. Create omission is represented in the stored
resource as `is_paused: true`, but omission remains distinguishable when constructing audit field
names.

## Atomic Audit and Repository/Service Contract

The repository provides one explicitly tenant-scoped lookup by `(tenant_id, workspace_id)`. The
service:

1. resolves the parent workspace through the existing tenant-safe ownership path;
2. captures explicitly supplied policy field names before applying schema/model defaults;
3. creates or mutates the policy in memory;
4. adds exactly one corresponding append-only audit event;
5. commits policy and audit in one transaction;
6. rolls back the session on every flush or commit failure; and
7. maps uniqueness failures to `conflict` without exposing database exception text.

Successful mutations emit exactly:

```text
workspace_autonomy_policy.created
workspace_autonomy_policy.updated
```

The resource type is `workspace_autonomy_policy`, resource ID is the policy UUID, and optional
`actor_id` is provider-neutral attribution. Audit `details` is exactly:

```python
details = {
    "workspace_id": str(workspace_id),
    "changed_fields": sorted(explicitly_supplied_policy_fields),
}
```

For POST, `changed_fields` includes required `level` and includes `is_paused` only when the client
explicitly supplied it. It must not add `is_paused` merely because the schema, ORM, or database
stored the default `true`. For PATCH, it contains only explicitly supplied policy fields. It always
excludes `actor_id`. Never copy enum or boolean values into audit details or logs. GET, validation
failures, not-found operations, conflicts, and rolled-back mutations create no audit event and
leave policy state unchanged.

## Non-Enforcement and Existing Semantics

`WorkspaceAutonomyPolicy` is a preference record, not a control-plane decision. PRODUCT-003 must
not add a read of this table to execution services, proposal creation, approval decisions,
transition logic, agent routing, middleware, or connectors. It must not infer authorization from a
level or from the paused flag.

In particular:

- `observe_only` does not start observation or data collection;
- `recommend_only` does not create recommendations;
- `approval_required` does not create or modify an approval requirement;
- `low_risk_auto` does not grant permission or automatically execute low-risk work;
- `is_paused=false` does not unpause a worker, schedule, job, or external action; and
- `is_paused=true` is stored preference, not evidence that every runtime component is stopped.

Existing action proposals keep their existing `requires_approval`, risk-level constraints,
statuses, and transitions. Existing approval decisions remain final under their current contract.
No high-risk gate is weakened, and no existing or future runtime may cite this record alone as
authentication, authorization, permission, safety evidence, or approval.

## Representative Code Style

Follow the current typed SQLAlchemy, strict Pydantic, repository/service, structured-error,
tenant-context, and append-only audit patterns. Ruff owns formatting at 100 characters. Keep UUID,
enum, and boolean types intact internally; validate strict request shape at the API boundary and
enforce ownership, cardinality, enum bounds, nullability, and the paused default in PostgreSQL.

```python
class AutonomyLevel(StrEnum):
    OBSERVE_ONLY = "observe_only"
    RECOMMEND_ONLY = "recommend_only"
    APPROVAL_REQUIRED = "approval_required"
    LOW_RISK_AUTO = "low_risk_auto"


class AutonomyPolicyCreate(StrictInput):
    level: AutonomyLevel
    is_paused: StrictBool = True
    actor_id: UUID | None = None


class AutonomyPolicyUpdate(StrictInput):
    level: AutonomyLevel | None = None
    is_paused: StrictBool | None = None
    actor_id: UUID | None = None

    @model_validator(mode="after")
    def includes_policy_change(self) -> "AutonomyPolicyUpdate":
        supplied = self.model_fields_set - {"actor_id"}
        if not supplied:
            raise ValueError("At least one autonomy policy field must be updated")
        if any(getattr(self, field) is None for field in supplied):
            raise ValueError("Autonomy policy fields cannot be cleared")
        return self
```

Use Pydantic's `StrictBool` (or an equivalent field-local strict boolean annotation) for
`is_paused` rather than relying on the existing input base class, which permits normal Pydantic
coercion. Do not make the shared base globally strict in PRODUCT-003 because that would change
validation for unrelated existing APIs. Reject `0`, `1`, and strings. Implementation names for
request/response schemas may align with nearby schema naming while preserving the fixed table,
model, enum, route, resource, and event names.

## Testing Strategy

- Schema validation: POST requires `level`; PATCH requires a policy field; reject unknown
  fields, absent required level, invalid enum strings, invalid/null enum, coerced/non-boolean and
  null `is_paused`, and invalid actor UUID. Verify `actor_id` alone is rejected on PATCH.
- Safe defaults: API creation without `is_paused` stores/returns `true`; direct ORM construction
  exercises the model default; direct PostgreSQL insert omitting the column exercises the database
  default. Metadata/DDL asserts non-null and server default. Explicit `false` remains `false`.
- API lifecycle: POST returns 201 and stable fields; GET returns the same policy; PATCH changes only
  supplied fields; pause and unpause work as persistence only; duplicate and concurrent creation
  conflict; missing policy is `not_found`; unsupported DELETE/list routes do not exist.
- Tenant isolation: header/path mismatch, missing workspace, cross-tenant workspace, and
  cross-tenant policy access are indistinguishable as `not_found` for every authorized method.
- Database contract: direct PostgreSQL operations prove invalid enum values and null paused flags
  fail, omitted paused flag becomes true, uniqueness enforces one policy per tenant/workspace, and
  the composite foreign key rejects cross-tenant association. Do not claim SQLite proves these
  PostgreSQL constraints.
- Audit and transactions: successful create/update emits exactly one correctly typed/attributed
  event with sorted explicitly supplied field names and workspace ID. Create omission must produce
  `changed_fields == ["level"]`; explicit create pause must include both names alphabetically.
  Assert recursively that no policy value appears in details. GET and every failed mutation add no
  event. Forced flush/commit failures leave neither partial policy state nor an audit row.
- Non-enforcement regression: existing proposal, approval, risk, and execution tests remain
  unchanged and pass for all four stored levels and both paused values. Tests must prove the API
  causes no job, proposal, decision, execution transition, integration call, or external action.
- Migration: inspect upgrade/downgrade SQL; exercise upgrade, downgrade, and re-upgrade on
  disposable PostgreSQL. Upgrade adds only the intended table/constraints and no redundant index;
  downgrade removes only it.
- Regression: run the full suite to preserve foundation, business-profile, primary-goal,
  execution, proposal, approval, history, audit, handoff, health, and configuration behavior.

No arbitrary coverage percentage is added. Issue #44's named contracts, safe defaults, isolation,
non-enforcement boundary, and failure modes require deterministic assertions.

## Dependency-Ordered Implementation Tasks

### Task 1: Add the enum, migration, and model

Define `AutonomyLevel`, create the additive `workspace_autonomy_policies` migration, and add
`WorkspaceAutonomyPolicy` with composite ownership, one-per-workspace uniqueness, database enum
constraint, non-null fields, and all three safe-default layers for `is_paused`.

Dependencies: existing workspace schema and migration head `20260816_0004`.

Acceptance: model metadata and migration agree; only the policy table and required constraints are
added; no redundant index exists; direct PostgreSQL tests prove enum bounds, null rejection,
database default true, cardinality, and same-tenant ownership.

Verification: run focused database tests, render both migration directions, and exercise the
migration round trip on disposable PostgreSQL.

### Task 2: Define strict schemas and supplied-field behavior

Add create, patch, and response schemas. Preserve strict enum/boolean types, create default true,
patch non-null semantics, actor attribution exclusion, and explicitly supplied field tracking.

Dependencies: Task 1 fixes the persisted types and defaults.

Acceptance: deterministic schema tests cover all four levels, strict booleans, create omission,
explicit false, invalid/null values, unknown fields, and actor-only patch rejection; the response
never contains `actor_id`.

Verification: run focused schema/API validation tests plus Ruff and mypy.

### Checkpoint: Persistence and input contract

- Model and migration agree on names, enum values, nullability, ownership, cardinality, and default.
- PostgreSQL—not SQLite alone—has proved direct constraint and server-default behavior.
- Schema tests prove strict inputs and retain create-field omission information for audit use.

### Task 3: Implement repository and atomic service transactions

Add the tenant/workspace-scoped lookup and create/get/update orchestration. Each mutation atomically
commits one policy change with one redacted audit; every persistence failure rolls back.

Dependencies: Tasks 1 and 2 define storage and supplied changes.

Acceptance: lifecycle, duplicate/concurrent conflict, rollback, event count/type/attribution,
value redaction, and read/failure behavior are proven. Omitted create `is_paused` stores true but
does not appear in audit `changed_fields`.

Verification: run focused service/API and PostgreSQL tests, including forced flush and commit
failures.

### Task 4: Expose exactly three API routes

Wire singular POST/GET/PATCH routes through existing tenant context, repository, service, and
structured error mapping. Add no DELETE or list route.

Dependencies: Task 3 supplies all persistence behavior.

Acceptance: status codes, stable response, strict validation, not-found non-disclosure, and
duplicate conflict match the contract across the request-to-database path.

Verification: run the entire workspace-autonomy-policy API suite and route-absence assertions.

### Checkpoint: Focused vertical slice

- Focused API and database suites pass together.
- Tenant isolation, parent validation, cardinality, enum bounds, all three paused defaults,
  atomic redacted audits, concurrency, and rollback work as one coherent slice.
- A static/runtime search confirms no execution, proposal, approval, worker, connector, or external
  action path reads `WorkspaceAutonomyPolicy`.

### Task 5: Prove the non-enforcement boundary

Add only the regression assertions necessary to show every level and paused value are inert stored
preferences and existing proposal/approval semantics remain unchanged.

Dependencies: Task 4 completes the public persistence path.

Acceptance: policy mutations create no proposal, decision, job, run, transition, integration call,
or external effect; existing high-risk and approval requirements are unchanged.

Verification: run focused PRODUCT-003 tests plus existing execution/proposal/approval suites.

### Task 6: Run full verification

Run Ruff lint/format, strict mypy, full pytest, pip-audit, bidirectional Alembic SQL inspection,
the disposable migration round trip, `make check`, `git diff --check`, and final status/diff review.

Dependencies: Tasks 1-5 are complete.

Acceptance: every applicable repository gate passes without bypass; only issue-authorized files
changed; tenant boundaries and proposal/approval behavior remain intact; recovery notes are
complete.

### Task 7: Obtain independent read-only review

Give a fresh reviewer issue #44, this specification, the final diff, and verification results. The
reviewer must not edit files and must assess correctness, scope, tenant safety, database defaults
and constraints, audit privacy, non-enforcement, rollback, tests, and repository governance.

Dependencies: Task 6 provides a stable verified diff.

Acceptance: zero blocking findings. Fix any finding on the task branch, repeat affected gates, and
request a fresh read-only review before opening or updating the draft PR.

## Three-Tier Boundaries

### Always

- Keep every parent and autonomy-policy lookup explicitly tenant/workspace scoped.
- Enforce same-tenant ownership, one-policy cardinality, enum bounds, non-null fields, and the
  paused default in PostgreSQL as specified.
- Preserve strict request validation and omission-aware, value-redacted atomic audits.
- Treat every stored level and paused value as customer preference only.
- Preserve all proposal, approval, risk, execution, and external-action behavior.
- Run focused/full gates and independent read-only review; deliver a draft PR from a task branch.

### Ask First

- Any change to authentication, authorization, permissions, tenant-context architecture, safety
  enforcement, risk or approval semantics, or execution behavior.
- Any destructive/data-rewriting migration or downgrade against meaningful data.
- Any new dependency, protected source-of-truth change, production/deployment change, secret
  handling, integration, network call, or customer-facing external side effect.
- Any expansion of fields, enum values, endpoints, cardinality, audit shape, or semantics fixed by
  issue #44.

### Never

- Use the stored policy as authentication, authorization, permission, approval, safety evidence,
  risk clearance, or runtime enforcement in PRODUCT-003.
- Make `low_risk_auto` execute work or make `is_paused=false` start or resume anything.
- Change existing proposal/approval semantics, weaken high-risk gates, or bypass tenant scoping.
- Add list/delete, enforcement middleware, agents, jobs, workers, integrations, frontend behavior,
  network calls, or external actions.
- Store policy values in audit details/logs; synthesize omitted `is_paused` as a supplied audit
  field; bypass failing gates; deploy; modify production; delete meaningful data; or commit secrets.

## Fixed Assumptions and Resolved Questions

- Cardinality: zero or one `WorkspaceAutonomyPolicy` per tenant/workspace; duplicate creation is a
  conflict.
- Levels: `AutonomyLevel` has exactly `observe_only`, `recommend_only`, `approval_required`, and
  `low_risk_auto`; no aliases or default level exist.
- Required input: POST requires `level`; neither policy field accepts null.
- Paused default: `is_paused` defaults to true in create schema/application, ORM model, and
  database server default, and is non-null.
- Patch: at least one policy field is explicitly supplied; omissions preserve stored values;
  `actor_id` alone is not a mutation.
- Audit: resource type is `workspace_autonomy_policy`; events are
  `workspace_autonomy_policy.created` and `workspace_autonomy_policy.updated`; details contain
  only workspace ID and sorted explicitly supplied field names. Omitted create `is_paused` is not
  listed. Optional actor ID is attribution; values are forbidden.
- Isolation: composite database ownership plus tenant-scoped parent/policy queries; missing and
  cross-tenant resources share `not_found` behavior.
- API: singular `/autonomy-policy` has POST/GET/PATCH only. POST is 201; GET/PATCH are 200;
  duplicates are `conflict`.
- Semantics: stored preference only. It is not authn, authz, permission, safety evidence,
  enforcement, or execution input. Existing proposal and approval semantics do not change.
- Architecture: extend current explicit model/schema/repository/service/router and append-only
  audit patterns. No generic abstraction, redundant index, or dependency is justified.

## Success Criteria

- A tenant-safe workspace can create at most one autonomy policy, then retrieve and partially
  update it through exactly three strict endpoints with stable typed response fields.
- The four enum values, required level, strict/non-null boolean, and schema/model/database default
  true are independently and deterministically proven, including direct PostgreSQL behavior.
- Same-tenant ownership and cardinality hold under service use, direct database bypass, and
  concurrent creation; missing/cross-tenant responses disclose nothing.
- Each successful mutation atomically emits exactly one attributed, value-redacted audit event;
  omitted `is_paused` stores true without appearing in supplied-field audit details.
- Every stored value remains inert preference data: no authentication, authorization, permission,
  safety, proposal, approval, execution, integration, or external-action behavior changes.
- Migration upgrade is limited to the table and required constraints with no redundant indexes;
  downgrade removes only the policy table.
- Deterministic tests cover schema, defaults, lifecycle, tenant isolation, concurrency,
  constraints, rollback, audits, non-enforcement, route absence, and existing behavior regressions.
- Every applicable repository gate and migration check passes, a separate read-only reviewer finds
  zero blocking issues, and a draft PR from the dedicated branch is ready for review.

## Risks

- Preference mistaken for authority: mitigate with explicit documentation, no reads from runtime
  decision paths, and non-enforcement regression tests.
- Unsafe implicit activation: require all three `is_paused=true` defaults and prove omission at API,
  ORM, and direct-database layers while keeping omission out of audit supplied fields.
- Cross-tenant disclosure or association: use composite database ownership, scoped queries,
  identical not-found responses, and direct bypass tests.
- Invalid or drifting levels: enforce the exact enum in schemas, typed code, and PostgreSQL DDL.
- Duplicate/concurrent creation: enforce database uniqueness and map integrity failure to the stable
  conflict response.
- Policy values leaking through audits: use a fixed details allowlist and recursively assert no
  supplied enum/boolean value is present.
- Partial commit: add policy and audit to one transaction and roll back all flush/commit failures.
- Destructive downgrade: prefer application rollback while retaining the additive table and data.

## Rollback and Recovery

Application rollback while retaining `workspace_autonomy_policies` is preferred: revert or disable
the PRODUCT-003 API/repository/service paths to stop new preference operations while preserving the
additive table and stored customer preferences. Since PRODUCT-003 adds no enforcement consumer,
retaining the table cannot authorize, start, resume, or otherwise trigger an action.

Only in a disposable development database may the PRODUCT-003 revision be downgraded to drop
`workspace_autonomy_policies`, then re-upgraded after correction. Downgrade deletes all stored
autonomy preferences. Before any approved downgrade against meaningful shared or production data,
obtain explicit approval, take and verify a backup, and document and test recovery.

For the planning-only issue #45, revert its documentation commit to restore PRODUCT-002 as the
recorded current task and remove this unimplemented specification. That rollback has no runtime,
schema, data, production, or external effect.

## Open Questions

None. Issue #44 and this reviewed specification resolve the product, API, persistence, default,
audit, isolation, non-enforcement, test, and rollback contracts. Any newly discovered question that
would change these contracts must pause implementation and be resolved here before runtime work
continues.
