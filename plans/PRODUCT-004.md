# PRODUCT-004: Tenant-Safe Onboarding-Status Projection

## Status and Authority

This is the reviewed pre-implementation specification for PRODUCT-004. The authoritative runtime
contract is [GitHub issue #48](https://github.com/rajeshkamalwar/Growth-OS/issues/48). Issue #49
authorizes this specification and the corresponding current-task update; it does not itself
implement runtime behavior.

After this planning change merges, `docs/CURRENT-TASK.md` authorizes an implementation agent to
execute issue #48. That authorization is not controller queueing and does not authorize applying
`codex-ready`; the orchestrator owns that label only after it re-inspects the resulting `main`.
If implementation requires a design change, update and review this specification before changing
runtime code.

## Objective

Add one GET-only workspace endpoint that projects whether four existing foundational records exist:
a site, business profile, primary growth goal, and autonomy policy. Return the four existence flags,
whether all four exist, and the missing steps in a fixed canonical order. The projection is
calculated from PostgreSQL on every request and is never persisted.

The projection means foundational record completeness only. It is not connector authentication,
monitoring readiness, approval, permission, policy enforcement, execution eligibility, or
operational readiness. It makes no claim that a site is reachable, a connector works, profile or
goal content is sufficient, the policy permits anything, or the workspace can safely operate.

## Detected Stack and Versions

- Python: project requires `>=3.12`; local virtual environment is Python 3.12.13.
- API and validation: FastAPI `>=0.115,<1` and Pydantic Settings `>=2.6,<3` (Pydantic is supplied
  through FastAPI).
- Persistence: SQLAlchemy asyncio `>=2.0,<3`, asyncpg `>=0.29,<1`, and Alembic `>=1.13,<2`;
  local Alembic is 1.19.1. PRODUCT-004 requires no migration.
- Database: PostgreSQL 16 (`postgres:16-alpine` in `compose.yaml`); SQLite/aiosqlite supports
  deterministic isolated tests for this read-only projection.
- Quality tools: Ruff `>=0.8,<1` (local 0.16.3), strict mypy `>=1.13,<2` (local 1.20.2), pytest
  `>=9.0.3,<10` (local 9.1.1), pytest-asyncio `>=1.3,<2`, and pip-audit `>=2.7,<3` (local 2.10.1).
- Packaging/build: hatchling; the application package is `src/growth_os`.

Dependency ranges in `pyproject.toml` are authoritative. Exact versions describe the planning
environment and do not authorize dependency changes.

## Risk Classification

The future PRODUCT-004 implementation is medium risk under repository governance because it adds
an API endpoint. Issue #48 explicitly authorizes that endpoint. It remains read-only, reversible,
and free of migrations, deployment, production operations, and external customer side effects.
This issue #49 planning change is low-risk documentation and task authorization only.

## Complete Executable Commands

Run from the repository root.

```bash
# One-time environment and editable package build/install
make install

# Optional local PostgreSQL and migration setup; PRODUCT-004 adds no migration
docker compose up -d db
make migrate

# Run the development API
make dev

# Focused and full tests
.venv/bin/pytest tests/api/test_onboarding_status.py
.venv/bin/pytest

# Lint, formatting verification, and strict typing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

# Dependency security audit
.venv/bin/pip-audit

# Aggregate repository checks and final diff hygiene
make check
git diff --check
git status --short
```

If focused tests are placed in an existing foundation test module instead of the expected new file,
substitute its exact path in the focused command. No Alembic generation or migration round trip is
applicable because the projection uses existing tables and stores nothing.

## Affected Project Structure

The future issue #48 implementation is expected to affect only the focused vertical slice below;
this issue #49 planning change modifies only `docs/CURRENT-TASK.md` and this file.

```text
src/growth_os/api/schemas.py          OnboardingStep and OnboardingStatusResponse
src/growth_os/repositories.py         explicit scoped existence projection
src/growth_os/services.py             parent validation and deterministic derivation
src/growth_os/api/foundation.py       singular GET route
tests/api/test_onboarding_status.py   contract, isolation, query shape, and side effects
README.md                             endpoint usage and narrow completeness semantics
```

Existing explicit modules and patterns are sufficient. Test cases may instead be consolidated into
`tests/api/test_foundation.py` if every PRODUCT-004 behavior remains isolated and easy to run. Do
not add a model, table, migration, repository abstraction, dependency, cache, or persisted status.

## API Contract

Expose exactly:

```text
GET /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/onboarding-status
```

The existing `X-Tenant-ID` header is required and must match the path tenant. The service validates
the parent workspace through the established tenant-scoped ownership path before querying its
foundational records. A missing workspace and a workspace owned by another tenant return the same
established structured `not_found` response. Neither case returns flags, missing steps, or any
signal about cross-tenant record existence. An existing same-tenant workspace returns 200 even when
none of the four records exists.

No request body, query parameter, pagination, POST, PATCH, PUT, DELETE, or list form is authorized.
Unknown paths and unsupported methods retain FastAPI's established route behavior.

Define `OnboardingStep` with exactly these serialized values and canonical order:

```text
site
business_profile
primary_growth_goal
autonomy_policy
```

The 200 response contains exactly:

```json
{
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "workspace_id": "00000000-0000-0000-0000-000000000000",
  "has_site": false,
  "has_business_profile": false,
  "has_primary_growth_goal": false,
  "has_autonomy_policy": false,
  "is_foundation_complete": false,
  "missing_steps": [
    "site",
    "business_profile",
    "primary_growth_goal",
    "autonomy_policy"
  ]
}
```

Field semantics are fixed:

- `has_site` is true when at least one `Site` exists for the exact tenant/workspace. Site count,
  URL reachability, connector presence, and connector status do not affect it.
- `has_business_profile` is true when the tenant/workspace's existing zero-or-one
  `WorkspaceBusinessProfile` record exists. Its field values and quality do not affect it.
- `has_primary_growth_goal` is true when the tenant/workspace's existing zero-or-one
  `WorkspacePrimaryGrowthGoal` record exists. Its content and target date do not affect it.
- `has_autonomy_policy` is true when the tenant/workspace's existing zero-or-one
  `WorkspaceAutonomyPolicy` record exists. Its level and paused state do not affect it.
- `is_foundation_complete` is true if and only if all four `has_*` flags are true.
- `missing_steps` contains exactly the enum value corresponding to every false flag, always in the
  canonical order above. It is empty when complete and never follows database or creation order.

The response identifies the exact parent with `tenant_id` and `workspace_id`, but contains no
underlying resource ID, timestamps, counts, resource content, connector state, policy value,
actor attribution, approval state, or operational-readiness claim.

## Repository Contract

Add one explicit typed repository method for this projection. After the service has validated the
workspace, the method receives `TenantContext` and `workspace_id` and executes one SQL round trip
containing four named scalar `EXISTS` expressions. Each expression independently includes both
`tenant_id == context.tenant_id` and `workspace_id == workspace_id` predicates.

Representative shape:

```python
statement = select(
    exists()
    .where(
        Site.tenant_id == context.tenant_id,
        Site.workspace_id == workspace_id,
    )
    .label("has_site"),
    exists()
    .where(
        WorkspaceBusinessProfile.tenant_id == context.tenant_id,
        WorkspaceBusinessProfile.workspace_id == workspace_id,
    )
    .label("has_business_profile"),
    exists()
    .where(
        WorkspacePrimaryGrowthGoal.tenant_id == context.tenant_id,
        WorkspacePrimaryGrowthGoal.workspace_id == workspace_id,
    )
    .label("has_primary_growth_goal"),
    exists()
    .where(
        WorkspaceAutonomyPolicy.tenant_id == context.tenant_id,
        WorkspaceAutonomyPolicy.workspace_id == workspace_id,
    )
    .label("has_autonomy_policy"),
)
```

Return a small typed repository result, such as a frozen dataclass with the four booleans. Do not
return ORM resources, query resource columns, count complete result sets, use `SELECT *`, reuse the
unscoped generic list helper, or infer existence from loaded content. `EXISTS` lets the database
stop at the first match, handles the site's one-to-many cardinality, and avoids hydrating sensitive
underlying records. Explicit predicates on every subquery make tenant scope auditable.

Do not combine parent validation into a query that makes missing and cross-tenant behavior harder
to verify. The established `get_owned(Workspace, context, workspace_id)` path remains the single
source of parent non-disclosure; the projection query runs only after it succeeds.

## Service Contract

Add one read-only service method with this sequence:

1. Resolve the workspace with `get_owned(Workspace, context, workspace_id)`. This produces the
   established indistinguishable `not_found` behavior for missing and cross-tenant workspaces.
2. Request the four scoped existence booleans from the repository.
3. Pair the booleans with the fixed `OnboardingStep` order.
4. Set `is_foundation_complete = all(flags)`.
5. Set `missing_steps` to the step for each false flag in canonical order.
6. Return the typed response/projection without mutating any object or transaction state.

The method must not call repository `add`, `flush`, `refresh`, `commit`, or `rollback`; create an
`AuditEvent`; inspect or return foundation record content; or call execution, connector, worker,
agent, approval, integration, or external-service paths. A normal GET does not start a transaction
that requires an application commit, and failure leaves no state to recover.

## Representative Code Style

Follow current `StrEnum`, Pydantic response, `FoundationRepository`, `FoundationService`, tenant
context, structured error, and foundation-router conventions. Ruff owns formatting at 100
characters. Keep the fixed order in one authoritative tuple so derivation cannot drift from the
enum-to-flag mapping.

```python
class OnboardingStep(StrEnum):
    SITE = "site"
    BUSINESS_PROFILE = "business_profile"
    PRIMARY_GROWTH_GOAL = "primary_growth_goal"
    AUTONOMY_POLICY = "autonomy_policy"


class OnboardingStatusResponse(BaseModel):
    tenant_id: UUID
    workspace_id: UUID
    has_site: bool
    has_business_profile: bool
    has_primary_growth_goal: bool
    has_autonomy_policy: bool
    is_foundation_complete: bool
    missing_steps: list[OnboardingStep]
```

The enum may live in `api/schemas.py` because it is a response-only projection type and has no
database representation. If an existing project convention requires a domain module, pause and
update this plan rather than inventing a persisted enum or changing the serialized contract.

## Testing Strategy

- Response derivation: cover no records, each of the four individual records, representative mixed
  subsets, and all records. Assert exact flags, `is_foundation_complete`, and `missing_steps`.
- Canonical ordering: create records in non-canonical order and assert missing steps always follow
  `site`, `business_profile`, `primary_growth_goal`, `autonomy_policy`; complete returns `[]`.
- Site cardinality: zero sites is false and one or multiple same-tenant/workspace sites is true.
- Content independence: vary optional profile and goal content, all four autonomy levels, both
  paused values, site URLs, and connector rows/statuses as useful; existence flags remain based
  only on record presence.
- Stable schema: assert the response contains exactly the eight documented fields with parent UUIDs,
  boolean flags, and serialized enum strings. It never includes underlying resource content or IDs,
  timestamps, or counts.
- Tenant isolation: cover missing header, malformed UUIDs, header/path mismatch, missing workspace,
  cross-tenant workspace, and foundation records belonging only to another tenant/workspace. Missing
  and cross-tenant parents return the identical structured `not_found` body and no projection.
- Repository/query efficiency: use compiled SQL inspection, an instrumented session, or a focused
  repository test to prove one four-`EXISTS` projection query after parent validation, explicit
  tenant/workspace predicates on all subqueries, and no selected resource columns or ORM entities.
- Read-only boundary: instrument repository transaction methods and inspect audit counts to prove
  GET performs no add/flush/refresh/commit/rollback, audit event, or persisted mutation. Existing
  execution and foundation regression suites prove no connector, job, transition, external call,
  or enforcement behavior changes.
- Route boundary: GET returns 200 for an existing empty workspace; assert POST, PATCH, PUT, DELETE,
  and list-shaped variants are absent and do not mutate state.
- Regression: run the full suite to preserve foundation, profile, goal, autonomy policy, execution,
  proposal, approval, history, audit, handoff, health, and configuration behavior.

No arbitrary coverage percentage is added. Issue #48's exact response, derivation, query shape,
tenant non-disclosure, route boundary, and absence of side effects require deterministic assertions.

## Dependency-Ordered Implementation Tasks

### Task 1: Define the response contract

Add the exact four-value `OnboardingStep` and eight-field `OnboardingStatusResponse`. Keep the enum
order and serialized values fixed; add no request schema or persisted model.

Dependencies: existing strict response/type conventions only.

Acceptance: schema serialization produces exactly the documented parent UUIDs, fields, and enum
strings; typing rejects contract drift; no request, model, migration, or dependency is added.

Verification: run focused schema tests plus Ruff and mypy.

### Task 2: Add the explicit existence projection

Add the typed repository result and one method issuing four tenant/workspace-scoped `EXISTS`
expressions in one projection query without loading underlying resources.

Dependencies: Task 1 fixes the public flag names that the repository result supplies.

Acceptance: none, individual, mixed, multiple-site, and complete states yield correct booleans;
every subquery is tenant/workspace scoped; one projection round trip selects no resource content.

Verification: run focused repository/query-shape tests on SQLite and, if the harness makes it
available, PostgreSQL. Inspect compiled/executed SQL rather than assuming ORM intent.

### Checkpoint: Typed and scoped projection

- The enum, response, repository result, and labels use identical fixed names.
- All four existence checks include explicit tenant and workspace predicates.
- The query returns only booleans, performs one projection round trip, and hydrates no ORM resource.

### Task 3: Add deterministic read-only service derivation

Validate the parent through the established tenant-safe ownership path, call the projection, and
derive completeness and missing steps from one canonical enum-to-flag mapping.

Dependencies: Tasks 1 and 2 provide the response and source booleans.

Acceptance: missing and cross-tenant parents are indistinguishable; all subsets derive correctly;
no transaction writer, audit, execution, connector, integration, or external path is called.

Verification: run focused service tests including spies/fakes for repository read and write methods.

### Task 4: Expose the singular GET route

Wire the response-only service method at the exact tenant/workspace `/onboarding-status` route using
existing context and structured-error behavior. Add no other method or route form.

Dependencies: Task 3 supplies all behavior.

Acceptance: an existing empty or populated same-tenant workspace returns 200 with the exact schema;
tenant failures disclose nothing; unsupported methods/routes are absent and state stays unchanged.

Verification: run the complete PRODUCT-004 API suite and explicit route/method-absence assertions.

### Checkpoint: Focused vertical slice

- Focused schema, repository, service, and API tests pass together.
- Every record subset, canonical order, tenant non-disclosure, response-field boundary, and
  read-only/no-audit behavior is proven through the request-to-database path.
- Static and runtime checks confirm no connector, approval, execution, worker, agent, or external
  system participates in the projection.

### Task 5: Document narrow endpoint semantics

Update README endpoint usage with the exact route and response meaning. State that the result is
foundational record completeness only and is not connector authentication, monitoring readiness,
approval, permission, policy enforcement, execution eligibility, or operational readiness.

Dependencies: Task 4 completes the public API contract being documented.

Acceptance: README shows the GET-only usage and exact narrow meaning without implying that
foundation completion authorizes, starts, or proves any operation.

Verification: compare README terminology against issue #48, the response schema, and this plan;
run Ruff format check because fenced examples are included in repository formatting scope.

### Task 6: Run full verification

Run Ruff lint/format, strict mypy, full pytest, pip-audit, `make check`, `git diff --check`, and final
status/diff review. Confirm no migration operation is needed and no protected document changes.

Dependencies: Tasks 1-5 are complete.

Acceptance: every applicable repository gate passes without bypass; only issue-authorized runtime,
test, and README files changed; tenant boundaries remain intact; recovery notes are complete.

### Task 7: Obtain independent read-only review

Give a fresh reviewer issue #48, this specification, the final diff, and verification results. The
reviewer must not edit files and must assess exact API/enum/field/order semantics, tenant safety,
query efficiency/content non-disclosure, read-only boundaries, tests, rollback, and governance.

Dependencies: Task 6 provides a stable verified diff.

Acceptance: zero blocking findings. Fix any finding on the task branch, repeat affected gates, and
request a fresh read-only review before opening or updating the draft PR.

## Three-Tier Boundaries

### Always

- Validate the parent workspace with the established tenant-scoped ownership path.
- Scope every existence subquery by both tenant and workspace and return only booleans.
- Preserve the exact route, enum, eight fields, canonical missing-step order, and all-four completeness
  rule.
- Treat the projection as foundational record existence only and keep GET side-effect free.
- Run focused/full gates and independent read-only review; deliver a draft PR from a task branch.

### Ask First

- Any change to authentication, authorization, permissions, tenant-context architecture, connector
  semantics, policy enforcement, approvals, safety, risk, execution, or operational-readiness rules.
- Any new endpoint/method, response field, enum value, persisted state, table, migration, dependency,
  cache, audit behavior, integration, network call, frontend behavior, or external side effect.
- Any modification to protected source-of-truth documents, production/deployment behavior, secrets,
  infrastructure, or issue #48's fixed semantics.

### Never

- Reveal whether a cross-tenant workspace or foundational record exists.
- Load or return resource content when an existence check suffices, or omit tenant/workspace scope
  from any of the four checks.
- Interpret record existence as authentication, connector health, monitoring readiness, approval,
  permission, enforcement, execution eligibility, safety, or operational readiness.
- Add mutation/audit behavior, queue controller work, apply `codex-ready`, bypass failing gates,
  merge, deploy, modify production, delete data, or commit secrets.

## Fixed Assumptions and Resolved Questions

- Route: exactly one GET at
  `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/onboarding-status`; no body, pagination,
  list, or mutating method.
- Enum and order: exactly `site`, `business_profile`, `primary_growth_goal`, `autonomy_policy`, in
  that canonical order.
- Fields: exactly `tenant_id`, `workspace_id`, `has_site`, `has_business_profile`,
  `has_primary_growth_goal`, `has_autonomy_policy`, `is_foundation_complete`, and `missing_steps`.
- Completion: true only when all four existence flags are true.
- Missing steps: false flags mapped to their enum and emitted only in canonical order.
- Site meaning: at least one same-tenant/workspace site; multiple sites do not change the boolean.
- Other records: existence of the workspace's zero-or-one profile, goal, and policy; content and
  policy values do not affect flags.
- Isolation: validate the parent first and use explicit tenant/workspace predicates for every
  existence check; missing and cross-tenant parents share `not_found` behavior.
- Efficiency: one four-`EXISTS` repository projection query after parent validation, returning a
  typed boolean result and no resource content.
- Persistence and audit: none. The projection is calculated at request time and GET emits no audit.
- Meaning: foundational record completeness only, never operational readiness or authority.
- Architecture: extend current explicit schema/repository/service/router patterns; no generic
  abstraction, dependency, model, migration, or cache is justified.

## Success Criteria

- The exact GET route returns the exact eight-field projection for an existing same-tenant
  workspace.
- All sixteen possible four-flag combinations follow the all-four completeness rule and canonical
  missing-step order; representative API cases and exhaustive pure derivation tests may divide this
  proof efficiently.
- Every existence check is explicitly tenant/workspace scoped, returns no underlying content, and
  uses one efficient four-`EXISTS` projection round trip after tenant-safe parent validation.
- Missing and cross-tenant workspaces are indistinguishable and disclose no foundation state.
- GET produces no audit, mutation, flush, commit, job, execution change, network call, or external
  behavior, and unsupported methods/routes are absent.
- Documentation and tests prevent foundational completeness from being presented as connector,
  monitoring, approval, permission, policy, execution, or operational readiness.
- README documents the exact GET usage and the narrow foundational-record-completeness meaning.
- Every applicable repository gate passes, a separate read-only reviewer finds zero blocking
  issues, and a draft PR from the dedicated branch is ready for review.

## Risks

- Cross-tenant disclosure: mitigate with established parent validation, explicit tenant/workspace
  predicates in every `EXISTS`, identical `not_found` responses, and adversarial isolation tests.
- Readiness overclaim: mitigate with narrow field names, explicit semantic exclusions, and tests
  showing connector/policy/content variations do not change existence semantics.
- Hidden content loading: mitigate with explicit scalar `EXISTS` projections and query-shape tests.
- Ordering drift: keep one canonical step-to-flag mapping and test non-canonical creation order plus
  all flag combinations.
- Accidental write/audit: keep service and route GET-only and instrument transaction/audit paths.
- Stale projection: calculate directly from PostgreSQL on each request; add no cache or persisted
  duplicate state in this slice.

## Rollback and Recovery

Revert the PRODUCT-004 implementation commit to remove the route, response types,
repository/service projection, focused tests, and README update. PRODUCT-004 adds no schema,
migration, persisted state, mutation, audit, production operation, or external side effect, so no
data rollback or recovery is required.

For the planning-only issue #49, revert its documentation commit to restore PRODUCT-003 as the
recorded current task and remove this unimplemented specification. That rollback has no runtime,
schema, data, production, or external effect.

## Open Questions

None. Issue #48 and this reviewed specification resolve the route, enum, fields, ordering,
tenant-scope, repository/service behavior, read-only boundary, semantic limits, tests, and rollback.
Any newly discovered question that would change these contracts must pause implementation and be
resolved here before runtime work continues.
