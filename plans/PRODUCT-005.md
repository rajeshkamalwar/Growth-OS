# PRODUCT-005: Durable Workspace Competitor Catalog

## Status and Authority

This is the reviewed pre-implementation specification for PRODUCT-005. The authoritative runtime
contract is [GitHub issue #52](https://github.com/rajeshkamalwar/Growth-OS/issues/52). Issue #53
authorizes this specification and the corresponding current-task update; it does not itself
implement runtime behavior.

After this planning change merges, `docs/CURRENT-TASK.md` authorizes an implementation agent to
execute issue #52. That authorization is not controller queueing and does not authorize applying
`codex-ready`; the orchestrator owns that label only after it re-inspects the resulting `main`.
If implementation requires a design change, update and review this specification before changing
runtime code.

## Objective

Add a durable, tenant-scoped catalog of competitor identities and optional customer-supplied notes.
Clients can create, list, retrieve, and partially update competitors belonging to one workspace.
PostgreSQL remains the operational source of truth, tenant/workspace ownership is enforced in both
queries and database constraints, lists are bounded and deterministic, and each successful mutation
commits atomically with one redacted audit event.

This catalog is inert product memory. It records only what the customer supplies. It performs no
collection, discovery, crawling, enrichment, inference, monitoring, recommendation, or action.

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

## Risk Classification

The future PRODUCT-005 implementation is medium risk because it adds a table and API endpoints;
issue #52 explicitly authorizes them. It is additive and reversible but its downgrade destroys
competitor rows, so destructive downgrade requires explicit approval and a verified backup. The
issue #53 planning change is low-risk documentation and task authorization only.

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
.venv/bin/pytest tests/api/test_workspace_competitors.py \
  tests/db/test_workspace_competitor_constraints.py
GROWTH_OS_TEST_DATABASE_URL='postgresql+asyncpg://<user>:<password>@<host>/<disposable-db>' \
  .venv/bin/pytest tests/db/test_workspace_competitor_constraints.py -k postgresql
.venv/bin/pytest

# Lint, formatting verification, and strict typing
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy

# Dependency security audit
.venv/bin/pip-audit

# Render the PRODUCT-005 migration in both directions for review
.venv/bin/alembic upgrade 20260816_0005:head --sql > /tmp/product-005-upgrade.sql
.venv/bin/alembic downgrade head:20260816_0005 --sql > /tmp/product-005-downgrade.sql

# Apply, reverse, and reapply only the new revision in a disposable development database
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1
.venv/bin/alembic upgrade head

# Aggregate repository checks and final diff hygiene
make check
git diff --check
git status --short
```

The new migration must directly follow `20260816_0005`; the implementation may choose the next
valid revision identifier while retaining the explicit offline range above. Never downgrade a
database containing meaningful shared or production competitor data without explicit approval, a
verified backup, and a tested recovery plan.

## Affected Project Structure

The future issue #52 implementation is expected to affect only this focused vertical slice; this
issue #53 planning change modifies only `docs/CURRENT-TASK.md` and this file.

```text
migrations/versions/<revision>_workspace_competitors.py
                                             additive competitor-table migration
src/growth_os/db/models.py                   WorkspaceCompetitor model
src/growth_os/api/schemas.py                 strict create/patch/response/list schemas
src/growth_os/repositories.py                explicit scoped competitor queries
src/growth_os/services.py                    lifecycle and atomic audit transaction
src/growth_os/api/foundation.py              nested POST/list/get/PATCH routes
tests/api/test_workspace_competitors.py      API, isolation, audit, and non-action behavior
tests/db/test_workspace_competitor_constraints.py
                                             database ownership and field constraints
README.md                                    endpoint examples, inert semantics, and recovery
```

Existing explicit modules and patterns are sufficient. Do not add a generic CRUD framework, new
service layer, dependency, worker, integration, or execution-path integration. Test cases may be
consolidated into nearby suites if every named behavior remains clear and independently executable.

## Migration and Data Contract

Create the additive `workspace_competitors` table containing exactly:

- mixin-provided UUID `id`, timezone-aware `created_at`, and timezone-aware `updated_at`;
- required UUID `tenant_id` and `workspace_id`;
- required string `name`, maximum 200 characters and nonblank after surrounding whitespace is
  removed by the API/service boundary;
- nullable string `website_url`, maximum 2048 characters; and
- nullable text `notes`, whitespace-trimmed and 1..4000 characters when non-null.

Define `WorkspaceCompetitor` in `src/growth_os/db/models.py`. Use a composite foreign key from
`(workspace_id, tenant_id)` to `(workspaces.id, workspaces.tenant_id)` with `ON DELETE RESTRICT`.
Add a unique constraint on `(tenant_id, workspace_id, name)`. This enforces exact persisted-name
uniqueness inside one tenant/workspace while allowing the same exact name in a different workspace
or tenant. PostgreSQL's ordinary case-sensitive equality applies: `Acme` and `acme` are distinct;
do not case-fold, use `lower`, add `citext`, or normalize Unicode in this slice.

Add named database check constraints for `char_length(name) BETWEEN 1 AND 200`,
`name = btrim(name)`, `website_url IS NULL OR char_length(website_url) <= 2048`,
`notes IS NULL OR char_length(notes) BETWEEN 1 AND 4000`, and
`notes IS NULL OR notes = btrim(notes)`. The API independently enforces and normalizes HTTP(S) URL
shape; the database stores the validated URL string and enforces its nullability/length, not URL
parsing.
The unique constraint supports exact-name conflict detection. Add no redundant index.

The migration creates only this table and required constraints. It performs no backfill, rewrite,
collection, or inference. Its downgrade drops only `workspace_competitors` and therefore deletes
all catalog rows; the rollback procedure below is mandatory before any meaningful-data downgrade.

## API Contract

Expose exactly:

```text
POST  /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors
GET   /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors/{competitor_id}
PATCH /api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/competitors/{competitor_id}
```

All methods require the existing `X-Tenant-ID` context to match the path tenant. Every method first
validates the parent workspace through the established tenant-safe ownership path. Item reads and
updates then resolve by all three of `tenant_id`, `workspace_id`, and `competitor_id`. Missing and
cross-tenant workspaces or competitors return the same established structured `not_found`; no
response reveals cross-tenant existence. POST returns 201; list, item GET, and PATCH return 200.
No PUT, DELETE, bulk, search, discovery, or unscoped route is authorized.

### Fields and strict validation

POST accepts exactly:

- `name`: required string, whitespace-trimmed before validation and persistence, length 1..200 after
  trimming, and never null;
- `website_url`: optional nullable string, maximum 2048 characters, default null, and when non-null
  a normalized absolute `http://` or `https://` URL containing a host;
- `notes`: optional nullable string, whitespace-trimmed and length 1..4000 when non-null, default
  null; empty and whitespace-only strings are invalid; and
- `actor_id`: optional nullable UUID used only for audit attribution.

PATCH accepts the same four names but must explicitly supply at least one competitor field:
`name`, `website_url`, or `notes`. `actor_id` alone is not a change. Omitted competitor fields remain
unchanged. Explicit null clears `website_url` or `notes`; explicit null is invalid for `name`.
PATCH `name` is trimmed and then must contain 1..200 characters. Empty or whitespace-only names are
invalid. Reject unknown fields, invalid/coerced non-string field types, invalid URL schemes or
hosts, over-length values, invalid UUIDs, an empty patch, and actor-only patch through the
established structured validation response.

URL validation must produce one stable normalized stored/serialized string representation. Follow
the existing `AnyHttpUrl` validation pattern and explicitly persist its string form after schema
validation. Do not fetch, resolve DNS, probe, or otherwise contact the URL. Fragments, userinfo, and
query strings follow `AnyHttpUrl` validation semantics within the length bound. No domain inference
or deduplication by URL is authorized.

The item response contains exactly:

```text
id
tenant_id
workspace_id
name
website_url
notes
created_at
updated_at
```

It never contains `actor_id`. POST omission stores and returns null for both nullable fields.
PATCH omission leaves stored values unchanged; explicit null is returned as null after clearing.

### Bounded list contract

The collection GET accepts only:

- `limit`: integer, default 50, minimum 1, maximum 100; and
- `offset`: integer, default 0, minimum 0.

Return the established `Page[WorkspaceCompetitorResponse]` shape with exactly `items` and
`pagination`; nested `pagination` contains exactly `limit`, `offset`, and `total`. `items` contains
the response objects for the requested page; `total` is the count for the exact tenant/workspace
before limit/offset. Always order ascending by `(created_at, id)` before applying pagination so ties
are deterministic. An offset beyond the result set returns `items: []` with the unchanged scoped
total. Invalid or out-of-range pagination values use established structured validation behavior.
Listing an existing empty workspace returns 200 with an empty page and total zero.

## Explicit Repository Contract

Extend `FoundationRepository` with competitor-specific methods; do not route this feature through
the existing generic `get_owned`, `list_owned`, or a new generic CRUD abstraction.

- `get_competitor(context, workspace_id, competitor_id)` selects a `WorkspaceCompetitor` only when
  all three identity predicates match. It returns null otherwise.
- `list_competitors(context, workspace_id, *, limit, offset)` selects only rows matching both tenant
  and workspace, orders by `WorkspaceCompetitor.created_at` then `WorkspaceCompetitor.id`, and
  applies limit/offset. Its count query uses the identical tenant/workspace predicate and ignores
  pagination. It returns the page and total.
- Creation uses the existing explicit `add`; persistence uses explicit flush, commit, refresh, and
  rollback primitives. No method may omit tenant scope, accept an arbitrary model, perform an
  unbounded list, or query by competitor ID or name alone.

The repository does not translate exceptions or decide response semantics. Query-shape tests must
make tenant/workspace/competitor predicates and deterministic ordering directly auditable.

## Service and Conflict Contract

Add explicit competitor service methods with these sequences:

1. Create: validate the parent with `get_owned(Workspace, context, workspace_id)`; construct the
   competitor from validated values; add competitor; flush so its UUID exists; add one create audit;
   commit once; refresh; return.
2. List: validate the parent first; call the scoped bounded repository list/count; return its page
   and metadata without mutation or audit.
3. Get: validate the parent first; call the three-identity repository lookup; raise the established
   `NotFoundError` when absent; return without mutation or audit.
4. Patch: use the same parent and item resolution as get; apply only explicitly supplied competitor
   changes in memory; add one update audit; flush; commit once; refresh; return.

On every `IntegrityError` from flush or commit, call rollback before translating a uniqueness
violation to the established `ConflictError`. Do not expose exception text, constraint names,
existing names, IDs, or tenant information. Because the only expected user-reachable integrity
conflict after parent validation and strict input validation is exact-name uniqueness, map that
failure to `conflict`; unexpected non-integrity failures are rolled back and re-raised for the
established internal-error handling. Every flush or commit exception must roll back. A failed
create leaves neither competitor nor audit; a failed patch leaves the original competitor state
and no audit. Reads do not flush, commit, refresh, roll back, or audit.

Concurrent same-name creation or rename relies on the database unique constraint and produces one
winner; every loser returns the same structured conflict. Preflight name queries are unnecessary
and must not become the correctness mechanism.

## Atomic Redacted Audit Contract

Successful mutations emit exactly:

```text
workspace_competitor.created
workspace_competitor.updated
```

For both, `resource_type` is exactly `workspace_competitor`, `resource_id` is the competitor UUID,
and `actor_id` is the optional provider-neutral request attribution. Audit `details` is exactly:

```python
details = {
    "workspace_id": str(workspace_id),
    "changed_fields": sorted(explicitly_supplied_competitor_fields),
}
```

For POST, `changed_fields` always includes `name` and includes `website_url` and `notes` only when
the client explicitly supplies them, including when explicitly null. Defaults must not create false
field changes. For PATCH, it contains only explicitly supplied competitor fields, including
nullable fields explicitly cleared. It always excludes `actor_id`.

Never put competitor names, URLs, notes, old/new values, request bodies, database exception text,
or other customer content in audit details or logs. Successful POST/PATCH emit exactly one event in
the same transaction as the mutation. GET/list, validation failures, missing/cross-tenant paths,
conflicts, and rolled-back mutations emit none.

## Non-Action Boundary and Existing Semantics

`WorkspaceCompetitor` is inert customer-supplied product memory. Its existence and contents grant
no authentication, authorization, permission, approval, safety evidence, risk decision, execution
eligibility, monitoring authority, connector scope, or outreach authority.

Creating, reading, listing, or updating a competitor must trigger no connector, job, proposal,
monitoring, recommendation, discovery, crawling, inference, enrichment, outreach, backlink
activity, network call, execution activity, worker, agent, schedule, notification, or external
behavior. The implementation must not add reads of this table to existing execution, proposal,
approval, audit retrieval, connector, worker, or agent paths. A stored website URL is data only and
must never be fetched, resolved, probed, or verified in this slice.

## Representative Code Style

Follow the current typed SQLAlchemy, strict Pydantic, repository/service, structured-error,
tenant-context, nested foundation-router, and append-only audit patterns. Ruff owns formatting at
100 characters. Keep UUID and datetime types intact internally; validate strictly at the boundary
and enforce tenant/workspace ownership, required name, lengths, and exact-name uniqueness in
PostgreSQL.

```python
class WorkspaceCompetitor(UUIDTimestampMixin, Base):
    __tablename__ = "workspace_competitors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "tenant_id"],
            ["workspaces.id", "workspaces.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "workspace_id", "name", name="uq_workspace_competitors_name"),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200", name="workspace_competitor_name_length"
        ),
        CheckConstraint("name = btrim(name)", name="workspace_competitor_name_trimmed"),
        CheckConstraint(
            "notes IS NULL OR char_length(notes) BETWEEN 1 AND 4000",
            name="workspace_competitor_notes_length",
        ),
        CheckConstraint(
            "notes IS NULL OR notes = btrim(notes)", name="workspace_competitor_notes_trimmed"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)


class WorkspaceCompetitorCreate(StrictInput):
    name: str = Field(min_length=1, max_length=200)
    website_url: AnyHttpUrl | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, min_length=1, max_length=4000)
    actor_id: UUID | None = None


class WorkspaceCompetitorUpdate(StrictInput):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    website_url: AnyHttpUrl | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, min_length=1, max_length=4000)
    actor_id: UUID | None = None
```

Use before/after field validators or equivalent explicit validators to trim `name` and non-null
`notes`, normalize an absolute HTTP(S) URL through the established URL type, reject null name, and
distinguish omitted nullable fields from explicit null through `model_fields_set`. Add an
after-model validator requiring at least one competitor field on PATCH. Do not globally alter the
shared strict-input base because that would change unrelated APIs.

Implementation names for schemas may follow nearby conventions while the fixed table, model,
fields, routes, event names, resource type, bounds, null/patch semantics, ordering, and audit shape
remain exact.

## Testing Strategy

- Schema validation: POST requires a non-null string name; trim surrounding whitespace; reject
  empty/whitespace-only and over-200 names, wrong/coerced types, unknown fields, empty/whitespace or
  over-length notes, malformed/relative/non-HTTP(S) URLs, invalid actor UUIDs, empty PATCH,
  actor-only PATCH, and null PATCH name. Accept explicit null notes and URL; distinguish omission.
- API lifecycle: POST returns 201 and stable fields; get returns the same item; PATCH changes only
  supplied fields; explicit null clears nullable fields; list returns exact page metadata; the same
  exact name conflicts only within one tenant/workspace; unsupported PUT/DELETE/bulk/unscoped
  routes are absent and do not mutate state.
- Pagination/order: defaults are 50/0; accept limits 1 and 100 and offset zero/beyond-total; reject
  zero, 101, negative offset, and invalid integer inputs under established FastAPI query parsing.
  Assert the established nested `Page.pagination` metadata. Freeze/control timestamps or insert
  tied rows to prove ascending `(created_at, id)` ordering and stable page boundaries.
- Tenant isolation: cover missing header, invalid UUIDs, header/path mismatch, missing/cross-tenant
  workspace, missing/cross-workspace/cross-tenant competitor, and same competitor names in other
  scopes. All item methods use three identities and disclose no cross-scope existence or content.
- Database contract: PostgreSQL direct operations prove non-null/nonblank/trimmed/max-200 name,
  nullable URL/notes length bounds, exact-name unique constraint, same-name allowance across
  scopes, and composite foreign-key ownership. Do not claim SQLite alone proves PostgreSQL checks,
  collation, or foreign keys.
- Repository/query shape: assert list and count share exact tenant/workspace predicates, item lookup
  adds competitor ID, list order is exactly `(created_at, id)`, and pagination is always bounded.
- Audit and transactions: assert exact create/update event/resource/attribution/details; explicit
  fields include null clears while omitted defaults do not; recursively prove details contain no
  field values. Forced flush, commit, and integrity failures roll back competitor and audit state;
  reads and all failures emit no audit.
- Non-action regression: instrument or isolate boundaries to prove no connector, job, proposal,
  monitoring, recommendation, discovery, crawler, inference, outreach, backlink, network,
  execution, worker, or agent call occurs. Existing proposal/approval/execution suites remain
  unchanged and pass.
- Migration: inspect upgrade/downgrade SQL; exercise upgrade, downgrade, and re-upgrade on disposable
  PostgreSQL. Upgrade adds only the intended table/constraints; downgrade drops only it.
- Regression: run the full suite to preserve foundation, profile, goal, autonomy, onboarding,
  execution, proposal, approval, history, audit, handoff, health, and configuration behavior.

No arbitrary coverage percentage is added. Issue #52's exact fields, bounds, null/patch behavior,
ordering, ownership, conflict, audit, route, and non-action contracts require deterministic tests.

## Dependency-Ordered Implementation Tasks

### Task 1: Add the migration and model

Create `workspace_competitors` and `WorkspaceCompetitor` with the exact fields, bounds, named checks,
composite ownership, exact-name uniqueness, and no redundant index or unrelated data operation.

Dependencies: existing workspace composite key and migration head `20260816_0005`.

Acceptance: model metadata and migration agree; only the competitor table and constraints are added;
direct PostgreSQL tests prove field, uniqueness, and same-tenant ownership invariants.

Verification: run focused database tests, render both migration directions, and exercise the
migration round trip on disposable PostgreSQL.

### Task 2: Define strict schemas and supplied-field semantics

Add create, PATCH, item response, and list response schemas. Implement exact trimming, URL, length,
null, omission, actor, unknown-field, and PATCH-at-least-one-change behavior.

Dependencies: Task 1 fixes persisted names, types, nullability, and bounds.

Acceptance: schema tests cover every boundary and response fields exactly; URL validation performs
only deterministic `AnyHttpUrl` normalization and no network activity; `model_fields_set` preserves
explicit nullable clears.

Verification: run focused schema/API validation tests plus Ruff and mypy.

### Checkpoint: Persistence and input contract

- Model, migration, and schemas agree on every name, type, bound, null rule, and ownership key.
- PostgreSQL—not SQLite alone—has proved database invariants and case-sensitive exact-name behavior.
- Strict schema tests prove trim, HTTP(S)-only URL, omission/null distinctions, and patch rules.

### Task 3: Add explicit scoped repository behavior

Add competitor-specific get and bounded list/count methods with all required tenant/workspace/item
predicates and deterministic order. Use no generic CRUD abstraction or unbounded query.

Dependencies: Task 1 supplies the model; Task 2 fixes response and pagination semantics.

Acceptance: repository/query-shape tests prove exact scoping, ordering, bounds, count parity, and
empty/beyond-page behavior without cross-scope leakage.

Verification: run focused repository tests and inspect compiled/executed SQL.

### Task 4: Implement service lifecycle and atomic audits

Add explicit create/list/get/PATCH orchestration, parent-first ownership checks, exact integrity
conflict mapping, redacted audits, and rollback on every mutation persistence failure.

Dependencies: Tasks 1-3 define storage, validation, and query behavior.

Acceptance: successful mutations commit exactly one event; reads emit none; every failure leaves no
partial audit or mutation; concurrent uniqueness has one winner; not-found paths disclose nothing.

Verification: run focused service/API tests including forced flush, commit, and integrity failures.

### Checkpoint: Scoped atomic lifecycle

- Tenant/workspace/item lookup and list/count scoping are explicit and adversarially tested.
- Exact-name conflicts are database-backed, safely mapped, and concurrency-safe.
- Mutations and redacted audits commit or roll back together; reads are side-effect free.

### Task 5: Expose exactly four nested routes

Wire nested POST/list/get/PATCH through the existing tenant context, repository, service, and
structured error patterns. Add no DELETE, PUT, search, bulk, discovery, or unscoped route.

Dependencies: Task 4 supplies complete behavior.

Acceptance: exact status codes, item/list shapes, strict pagination, isolation, null/PATCH behavior,
and unsupported-route absence hold through the request-to-database path.

Verification: run the complete workspace-competitor API suite and route/method-absence assertions.

### Task 6: Prove the non-action boundary

Add only focused regression assertions necessary to demonstrate that stored competitor data is
inert and no existing operational path reads or reacts to it.

Dependencies: Task 5 completes the persistence API.

Acceptance: no connector, job, proposal, monitoring, recommendation, discovery, crawl, inference,
outreach, backlink, network, execution, worker, agent, schedule, or external behavior is triggered;
existing safety and execution semantics remain unchanged.

Verification: run focused non-action assertions, existing execution suites, and a static reference
search for `WorkspaceCompetitor` outside the authorized vertical slice.

### Checkpoint: Complete vertical slice

- Focused API and database suites pass together with exact lifecycle, pagination, isolation, audit,
  rollback, and non-action behavior.
- Migration round trip is proven on disposable PostgreSQL with explicit data-loss recovery notes.
- Static/runtime evidence confirms the model is absent from operational and external-action paths.

### Task 7: Document usage, semantics, and recovery

Update README with the exact four routes, request/response examples, bounded pagination, inert
customer-memory meaning, prohibited behaviors, and application-first rollback guidance. State that
downgrade deletes rows and is restricted to disposable development absent explicit approval,
verified backup, and tested recovery.

Dependencies: Task 6 completes the public behavior being documented.

Acceptance: README matches issue #52 and the implemented contract without implying monitoring,
permission, recommendation, or action; recovery preserves the additive table by default.

Verification: compare README names, examples, bounds, and recovery text against issue #52, this
plan, schemas/routes, and migration behavior.

### Task 8: Run full verification

Run Ruff lint/format, strict mypy, full pytest, pip-audit, `make check`, migration validation,
`git diff --check`, and final status/diff review. Confirm no protected-document or unrelated change.

Dependencies: Tasks 1-7 are complete.

Acceptance: every applicable gate passes without bypass; only issue-authorized files changed;
tenant boundaries remain intact; risks and rollback are documented.

Verification: preserve command output for the draft PR and compare the final implementation against
issue #52, this specification, and `docs/CURRENT-TASK.md` field by field.

### Task 9: Obtain independent read-only review

Give a fresh reviewer issue #52, this specification, the final diff, and verification results. The
reviewer must not edit files and must assess exact naming, bounds, null/PATCH semantics, database
constraints, tenant isolation, pagination/order, conflicts, audits/rollback, non-action boundaries,
tests, and rollback.

Dependencies: Task 8 provides a stable verified diff.

Acceptance: zero blocking findings. Fix any finding on the task branch, repeat affected gates, and
request a fresh read-only review before opening or updating the draft PR.

## Three-Tier Boundaries

### Always

- Validate the parent first and scope every competitor operation by tenant and workspace; scope item
  operations by competitor ID as well.
- Preserve exact table/model/field/route/event names, validation bounds, null/PATCH semantics,
  deterministic order, and database ownership/uniqueness constraints.
- Keep pagination bounded, reads side-effect free, mutations/audits atomic, errors redacted, and
  every persistence failure rolled back.
- Treat every competitor value as inert customer data and run focused/full gates plus independent
  review before a draft PR.

### Ask First

- Any authentication, authorization, permission, tenant-context, safety, risk, approval, execution,
  connector, worker, agent, monitoring, or external-action integration.
- Any different field, bound, null rule, route, method, order, event, audit detail, database
  constraint, conflict behavior, migration operation, dependency, generic abstraction, or frontend.
- Any protected-document, production/deployment, secret, infrastructure, destructive-data, or issue
  #52 contract change.

### Never

- Reveal a cross-tenant or cross-workspace resource, or query a competitor without tenant/workspace
  scope.
- Store competitor field values in audits/logs or expose database exception details.
- Treat a competitor name, URL, note, or record as permission or as a trigger for any connector,
  job, proposal, monitoring, recommendation, discovery, crawl, inference, outreach, backlink,
  network, execution, worker, agent, schedule, or external behavior.
- Add DELETE, queue controller work, apply `codex-ready`, bypass failing gates, merge, deploy, modify
  production, delete meaningful data, or commit secrets.

## Fixed Assumptions and Resolved Questions

- Storage/model: `workspace_competitors` / `WorkspaceCompetitor`, with UUID/timestamp mixins and
  exact fields `id`, `tenant_id`, `workspace_id`, `name`, `website_url`, `notes`, `created_at`, and
  `updated_at`.
- Name: trim surrounding whitespace, require 1..200 characters, persist trimmed value, prohibit
  null, and enforce case-sensitive exact-name uniqueness per tenant/workspace.
- URL: nullable, maximum 2048, normalized absolute HTTP(S) with host, and never contacted. Notes:
  nullable, whitespace-trimmed, and 1..4000 characters when non-null; empty/whitespace-only notes
  are invalid.
- PATCH: omission preserves; explicit null clears URL/notes; name cannot be null; actor alone and
  empty patch are invalid.
- Ownership: composite `(workspace_id, tenant_id)` foreign key with `ON DELETE RESTRICT`; parent is
  validated first and item lookup includes tenant, workspace, and competitor.
- Routes: nested plural collection POST/list and item get/PATCH only; no DELETE, PUT, search, bulk,
  discovery, or unscoped form.
- Pagination/order: limit 50 by default and 1..100, offset 0 by default and nonnegative, total before
  pagination, order ascending `(created_at, id)`.
- Conflicts: database unique constraint is authoritative; duplicate create and conflicting rename
  map to the same structured `conflict` after rollback, without database details.
- Audit: exact create/update event names, singular resource type, sorted explicit changed-field
  names and workspace ID only; values never appear; mutations and audit are one transaction.
- Non-action: inert customer memory grants no permission and initiates no internal or external work.
- Architecture: extend explicit existing modules and patterns; no generic CRUD abstraction,
  dependency, operational integration, or external behavior is justified.

## Success Criteria

- The additive table independently enforces required trimmed name bounds, nullable field lengths,
  exact-name uniqueness per tenant/workspace, and same-tenant workspace ownership.
- Exact nested POST/list/get/PATCH behavior, response fields, null/PATCH rules, bounded pagination,
  deterministic order, isolation, non-disclosing errors, and conflict mapping are proven.
- Every successful mutation atomically emits exactly one correctly attributed, value-redacted audit;
  reads and every failed/rolled-back operation emit none.
- Stored competitor data grants no permission and triggers no connector, job, proposal, monitoring,
  recommendation, discovery, crawl, inference, outreach, backlink, network, execution, or external
  behavior; no DELETE exists.
- Focused and full checks, PostgreSQL migration/constraint tests, and `git diff --check` pass; a
  separate read-only reviewer finds zero blocking issues; a dedicated-branch draft PR is ready.
- README documents the exact endpoint/pagination contract, inert meaning, and application-first
  rollback that retains the additive table.

## Risks

- Cross-tenant disclosure: mitigate with parent-first validation, three-identity item lookup,
  tenant/workspace list/count predicates, composite ownership, and adversarial isolation tests.
- Duplicate races: rely on the database unique constraint, map integrity conflicts only after
  rollback, and test concurrent create/rename behavior.
- Sensitive-content leakage: allow only field names and workspace ID in audits; recursively inspect
  details and logs for names, URLs, notes, and database error content.
- Pagination drift: use the same scoped predicate for rows/count and stable `(created_at, id)` order;
  test timestamp ties and adjacent pages.
- Accidental external behavior: keep the model in the persistence vertical slice only and test/static
  search all operational boundaries.
- Destructive downgrade: stop writes, back up/export rows, test recovery on a disposable database,
  and require explicit approval before touching meaningful shared or production data.

## Rollback and Recovery

Application rollback is to revert the PRODUCT-005 implementation commit, removing routes, schemas,
repository/service behavior, model, focused tests, and migration file. Before database downgrade,
stop competitor writes and export/back up every `workspace_competitors` row that must be retained,
including IDs, tenant/workspace IDs, values, and timestamps. Validate that the backup is readable.

On a disposable database—or only with explicit approval for meaningful shared/production data—run
the single PRODUCT-005 downgrade. It drops only `workspace_competitors` and deletes all rows. To
recover, reapply the migration, restore rows from the verified backup, and validate composite
tenant/workspace ownership, exact-name uniqueness, row counts, timestamps, and API reads before
resuming writes. Never silently discard production/customer data.

For planning issue #53 only, revert its documentation commit to restore PRODUCT-004 as the recorded
current task and remove this unimplemented specification. No runtime, schema, data, production, or
external recovery is needed for the planning revert.

## Open Questions

None. Issue #52 and this reviewed specification resolve the names, fields, validation bounds,
null/PATCH semantics, routes, pagination, ordering, ownership, uniqueness, repository/service
behavior, conflict mapping, audit semantics, rollback, non-action boundary, and verification. Any
new question that would change those contracts must pause implementation and be resolved here before
runtime work continues.
