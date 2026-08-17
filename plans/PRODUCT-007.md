# PRODUCT-007: Deterministic On-Page Evidence Change Detection

## Status and Authority

This is the reviewed pre-implementation specification for PRODUCT-007. The authoritative runtime
contract is [GitHub issue #60](https://github.com/rajeshkamalwar/Growth-OS/issues/60). Issue #61
authorizes this specification and the corresponding current-task update; it does not implement or
queue runtime work.

After this planning change merges, `docs/CURRENT-TASK.md` authorizes an implementation agent to
execute issue #60. The orchestrator owns implementation queueing and may apply `codex-ready` only
after re-inspecting the resulting `main`. This planning task does not apply that label, merge the
implementation, deploy, or cause an external or customer-facing effect. If implementation requires
a contract or design change, update and review this specification before changing runtime code.

## Objective

Add a strictly typed, immutable, deterministic comparison component for two existing
`OnPageEvidence` values representing exactly the same normalized source URL. It reports exact
observed field-level changes in stable order. It does not judge significance, score quality, infer
causes, recommend work, persist data, audit, execute, or act.

## Existing Foundation and Detected Stack

- Python: the project requires `>=3.12`; `StrEnum`, frozen slotted dataclasses, and `TypeAlias` are
  available from the standard library.
- Existing evidence value: `src/growth_os/evidence/on_page.py` defines the frozen, slotted,
  seven-field `OnPageEvidence` and the pure `extract_on_page_evidence` function.
- Existing public exports: `src/growth_os/evidence/__init__.py` exports `OnPageEvidence` and
  `extract_on_page_evidence`; PRODUCT-007 extends this package surface only with the exact names in
  issue #60.
- Tests: pytest `>=9.0.3,<10` and pytest-asyncio `>=1.3,<2`; PRODUCT-006 tests are in
  `tests/evidence/test_on_page.py`, and focused PRODUCT-007 tests belong in
  `tests/evidence/test_diff.py`.
- Quality: Ruff `>=0.8,<1`, strict mypy `>=1.13,<2`, and pip-audit `>=2.7,<3`.
- Migrations: Alembic is already configured, but PRODUCT-007 creates no migration. Offline
  upgrade/downgrade rendering remains a regression gate proving the migration graph is unchanged.

Dependency ranges in `pyproject.toml` are authoritative. PRODUCT-007 adds no dependency and needs
no FastAPI server, database, Docker service, network access, or external account.

## Risk Classification

PRODUCT-007 is low risk. It is a pure, internal, reversible, standard-library comparison over
already-created immutable values, with no API, schema, persistence, network, file, connector,
execution, infrastructure, deployment, or customer-facing effect. The issue #61 planning change is
also low-risk documentation and task authorization only.

The authoritative auto-merge assessment is:

```json
{
  "risk": "low",
  "roadmap_authorized": true,
  "reversible": true,
  "production_deployment": false,
  "external_customer_side_effect": false,
  "stop_categories": []
}
```

This assessment does not merge or deploy anything and does not authorize any external action.

## Complete Executable Commands

Run from the repository root. `make install` is needed only if the existing `.venv` is absent or
out of date. No PostgreSQL service is needed for the focused comparison tests or offline migration
rendering.

```bash
# One-time environment and editable package install
make install

# Focused PRODUCT-006 regression and PRODUCT-007 tests
.venv/bin/pytest tests/evidence/test_on_page.py tests/evidence/test_diff.py

# Focused PRODUCT-007 test
.venv/bin/pytest tests/evidence/test_diff.py

# Full regression, lint, formatting, typing, and dependency audit
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pip-audit

# Migration-graph regression without touching a database
.venv/bin/alembic upgrade head --sql > /tmp/product-007-upgrade.sql
.venv/bin/alembic downgrade head:base --sql > /tmp/product-007-downgrade.sql

# Aggregate repository checks and final diff hygiene
make check
git diff --check
git status --short
```

`make check` repeats Ruff lint, strict mypy, full pytest, and pip-audit. It does not include Ruff
format verification, offline Alembic rendering, or `git diff --check`, so run those commands
explicitly. Do not bypass a failure. The `/tmp` SQL files are disposable validation artifacts and
must not be committed.

## Affected Project Structure

The future issue #60 implementation is restricted to this internal slice. This issue #61 planning
change modifies exactly `docs/CURRENT-TASK.md` and this new plan.

```text
src/growth_os/evidence/diff.py           exact enum, alias, immutable values, and pure comparison
src/growth_os/evidence/__init__.py       exact new public package exports
tests/evidence/test_diff.py              comparison, errors, non-action, and boundary tests
README.md                                optional bounded offline/non-action description only
```

No change to `src/growth_os/evidence/on_page.py` is authorized. No API/router, repository, service,
model, migration, dependency, worker, job, connector, execution, infrastructure, or deployment file
is authorized. Package exports must be limited to the exact public internal contract.

## Exact Public Internal Contract

Create `src/growth_os/evidence/diff.py` and export all five new public names from
`growth_os.evidence`:

```python
class OnPageEvidenceField(StrEnum):
    TITLE = "title"
    META_DESCRIPTION = "meta_description"
    CANONICAL_URL = "canonical_url"
    ROBOTS = "robots"
    HTML_LANG = "html_lang"
    H1_TEXTS = "h1_texts"


EvidenceValue: TypeAlias = str | tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class OnPageEvidenceChange:
    field: OnPageEvidenceField
    before: EvidenceValue
    after: EvidenceValue


@dataclass(frozen=True, slots=True)
class OnPageEvidenceDiff:
    source_url: str
    changes: tuple[OnPageEvidenceChange, ...]


def diff_on_page_evidence(
    *, previous: OnPageEvidence, current: OnPageEvidence
) -> OnPageEvidenceDiff: ...
```

Use standard-library `enum.StrEnum`, `typing.TypeAlias`, and `dataclasses.dataclass` as shown by the
contract. The dataclasses are equality-comparable and immutable via `frozen=True, slots=True`. They
contain exactly the listed fields, types, and order. `changes` is always an immutable tuple.

Do not add timestamps, IDs, counts, severity, confidence, meaning, causes, actions, inferred
values, convenience properties, alternate constructors, serialization models, framework models,
or additional aliases. Do not broaden or rename the function, parameters, types, enum members, or
exports.

## Input and Same-Source Contract

- Accept `OnPageEvidence` instances only for both `previous` and `current`.
- Reject a non-instance in either position with `TypeError`, without coercion, duck typing,
  reparsing, or constructing a replacement value.
- Require exact ordinary Python equality of `previous.source_url` and `current.source_url`.
- Raise `ValueError` when source URLs differ. Do not compare other fields first for a partial
  result, and do not return a cross-source diff.
- The source URL values already carry PRODUCT-006 normalization. Do not re-normalize, parse,
  resolve, case-fold, strip, redact, fetch, or otherwise reinterpret them.
- Preserve the exactly equal `previous.source_url` as `OnPageEvidenceDiff.source_url`.

## Six-Field Comparison and Canonical Order

Compare only these six non-source fields using ordinary Python value equality, in this exact
canonical order:

1. `title`
2. `meta_description`
3. `canonical_url`
4. `robots`
5. `html_lang`
6. `h1_texts`

For each unequal field, append exactly one `OnPageEvidenceChange` whose:

- `field` is the matching `OnPageEvidenceField` member;
- `before` is the exact value on `previous`; and
- `after` is the exact value on `current`.

Do not compare `source_url` as a reportable field; it is the exact-equality precondition and the
diff identity. Do not derive ordering from a set, dict supplied by a caller, dataclass reflection,
input construction order, or changed-value shape. The returned change tuple always follows the
six-field canonical order and includes each unequal field once.

## Exact Value and No-Change Semantics

- Retain scalar strings exactly as stored in `OnPageEvidence`; perform no normalization,
  whitespace folding, URL parsing, fragment handling, case folding, redaction, or copying through
  another representation.
- Retain `None` exactly. Absence-to-value, value-to-absence, and value-to-different-value are each
  ordinary changes with exact `before` and `after` values.
- Retain H1 tuples exactly. Any tuple content, order, or length inequality is one `H1_TEXTS` change,
  not one change per H1 and not an added/removed set.
- Equal fields are omitted.
- Fully equal evidence returns exactly
  `OnPageEvidenceDiff(source_url=previous.source_url, changes=())`.
- Do not manufacture defaults, collapse empty tuples with `None`, interpret robots directives,
  judge canonical URLs, infer language, score significance, infer causes, or recommend action.
- Do not mutate either input. Build the result with an immutable tuple and do not expose or reuse a
  mutable accumulation container.

## Implementation, Import, and Non-Action Boundaries

- Use only Python standard-library modules and the existing `OnPageEvidence` from the evidence
  package. Add no dependency.
- Keep `growth_os.evidence.diff` independent of FastAPI, Pydantic, SQLAlchemy, Alembic,
  repositories, services, tenant context, database models/sessions, connectors, execution, jobs,
  workers, browsers, HTTP clients, and application startup.
- Do not change the extraction behavior, fields, types, order, or exports already implemented for
  PRODUCT-006, except extending the package export list with the exact PRODUCT-007 names.
- Do not import or call the comparison from `growth_os.main`, API routers, repositories, services,
  models, connectors, execution, workers, jobs, or any other active application path.
- Add no API route, callback, migration, database model, persistence, audit event, scheduling,
  collection, monitoring integration, credential, connector behavior, job, worker, network/DNS/
  HTTP/file/database access, browser automation, or external side effect.
- Do not log evidence values. Do not add counts, metrics, scores, classifications, significance,
  confidence, meaning, cause inference, recommendations, or actions.
- README documentation is optional and, if changed, limited to the internal offline comparison
  semantics and explicit non-action boundary. It must not claim that a crawler, monitor,
  persistence layer, recommendation system, or execution capability exists.
- Do not alter authentication, authorization, permissions, tenant isolation, billing, secrets,
  infrastructure, deployment, or protected product, goal, architecture, scope, or decision docs.

## Acceptance Test Matrix

### Public shape, exports, equality, and immutability

- Assert the six enum members have exactly the specified names, values, definition order, and no
  extras.
- Assert `OnPageEvidenceChange` fields are exactly `field`, `before`, `after` in that order, and
  `OnPageEvidenceDiff` fields are exactly `source_url`, `changes` in that order.
- Assert both values use frozen slotted dataclasses, compare by exact value, reject mutation, and
  carry tuple-backed `changes`.
- Import `OnPageEvidenceField`, `EvidenceValue`, `OnPageEvidenceChange`, `OnPageEvidenceDiff`, and
  `diff_on_page_evidence` from `growth_os.evidence`; assert the package export list contains the
  existing PRODUCT-006 names plus exactly these new names.

### No-change and independent field changes

- Compare identical evidence and assert the exact empty-diff value using the previous source URL.
- Change each of `title`, `meta_description`, `canonical_url`, `robots`, `html_lang`, and
  `h1_texts` independently and assert one exact enum/before/after change.
- Cover value-to-different-value, `None` to value, value to `None`, and H1 tuple content, order, and
  length differences without normalization or reinterpretation.

### Canonical all-field ordering and exact values

- Change all six fields together and assert each appears exactly once in the fixed order: title,
  meta description, canonical URL, robots, HTML language, H1 texts.
- Include `None` transitions and a changed H1 tuple in the all-field case.
- Assert exact prior/current strings, `None`, and tuples are preserved as `before` and `after`.
- Construct values in ways that prove output ordering is the contract order, not an incidental set,
  mapping, comparison, or input order.

### Error, coercion, mutation, and non-action behavior

- Pass a non-`OnPageEvidence` value in each parameter and assert `TypeError` without coercion or
  attribute-based acceptance.
- Use different source URL strings and assert `ValueError`; include values that might look
  equivalent after normalization to prove exact equality and no re-normalization.
- Snapshot both frozen inputs before the call and assert they remain equal and unchanged after
  successful and failing comparisons.
- Instrument filesystem opening, socket/DNS, standard-library HTTP/URL opening, database/session,
  connector, audit, execution, parsing, and URL-normalization seams so comparison fails the test if
  any external or forbidden behavior is invoked.

### Standard-library, package, and repository boundaries

- Parse `src/growth_os/evidence/diff.py` imports and assert they are limited to standard-library
  enum/dataclass/typing support and the existing evidence value.
- Assert no reference imports the diff component into active application paths.
- Inspect the final changed-file list and dependency/migration/API/job/worker paths to prove there
  is no route, migration, dependency, persistence, connector, execution, worker, job, or active-path
  integration.
- Run PRODUCT-006 focused tests and the full repository suite to prove extraction, tenant,
  foundation, execution, audit, handoff, health, configuration, and migration behavior remains
  unchanged.

Tests must verify observable contract behavior rather than mandate a private helper layout. No
arbitrary coverage percentage or new testing dependency is authorized.

## Dependency-Ordered Implementation Tasks

### Task 1: Define the exact immutable public values

Create `growth_os.evidence.diff` with the exact six-member `OnPageEvidenceField`, `EvidenceValue`
alias, frozen slotted `OnPageEvidenceChange`, and frozen slotted `OnPageEvidenceDiff`. Extend the
evidence package exports with exactly the five new public names.

Dependencies: the merged PRODUCT-006 `OnPageEvidence` and evidence package.

Acceptance: names, enum values/order, alias, dataclass fields/order, equality, immutability, tuple
shape, and package exports exactly match issue #60, with no extra public contract.

Verification: run focused public-shape/export/immutability tests, Ruff, and strict mypy.

### Task 2: Implement strict deterministic comparison

Implement the keyword-only `diff_on_page_evidence` function with strict instance checks, exact
same-source validation, six-field ordinary equality, exact before/after preservation, omission of
equal fields, and canonical tuple ordering.

Dependencies: Task 1 fixes the returned values and enum.

Acceptance: identical evidence, each independent change, all changes, `None` transitions, H1 tuple
differences, invalid types, and different sources match issue #60 exactly; inputs remain unchanged.

Verification: run the complete focused PRODUCT-007 test and PRODUCT-006 regression test, then Ruff
and strict mypy.

### Checkpoint: Exact pure comparison contract

- The five exported names and function signature exactly match issue #60.
- The same-source precondition and six-field canonical order are explicit and tested.
- Exact values are retained, equal fields are absent, and no-change returns an empty tuple.
- Both inputs and both output dataclasses remain immutable.

### Task 3: Prove non-action and import boundaries

Add focused dynamic and static assertions showing comparison does not parse, normalize, fetch,
persist, audit, schedule, execute, or enter active application paths.

Dependencies: Task 2 completes the component under test.

Acceptance: socket, DNS, HTTP, filesystem, database, connector, audit, execution, parser, and URL
normalization seams are untouched; no API, job, worker, migration, dependency, persistence, or
operational import exists.

Verification: run focused boundary tests and inspect repository references and the final file list.

### Task 4: Add only bounded optional documentation

If a README update is useful, describe only the internal offline exact-diff semantics and explicit
non-action boundary. Do not claim monitoring, crawling, scoring, recommendations, persistence, or
execution.

Dependencies: Tasks 1-3 establish the behavior that may be documented.

Acceptance: omitting README is valid; if changed, wording matches issue #60 without broadening
product capability.

Verification: compare any README wording with issue #60, this plan, and package exports.

### Task 5: Run full verification and scope review

Run focused PRODUCT-006/PRODUCT-007 tests, full pytest, Ruff lint and format check, strict mypy,
pip-audit, offline Alembic upgrade/downgrade rendering, `make check`, and `git diff --check`. Inspect
the final diff and status against the authorized file set.

Dependencies: Tasks 1-4 are complete.

Acceptance: every gate passes without bypass; only the diff component, focused test, package
export, and optional bounded README change; protected documents, tenant boundaries, dependencies,
migrations, API, persistence, active paths, and external behavior remain untouched.

Verification: preserve exact command results for the draft PR and compare the implementation field
by field with issue #60, this specification, and `docs/CURRENT-TASK.md`.

### Task 6: Obtain independent read-only review

Give a fresh reviewer issue #60, this specification, the stable final diff, and verification
results. The reviewer must not edit files and must assess the exact names/signature/types, enum and
dataclass fields/order/immutability, strict types, same-source requirement, six-field equality and
canonical order, exact values, no-change/errors, tests, import/non-action boundaries, scope, risk,
delivery, and rollback.

Dependencies: Task 5 provides a stable verified diff.

Acceptance: zero blocking findings. Fix any finding on the implementation branch, rerun affected
and full gates, and obtain a fresh read-only review before opening or updating the draft PR.

## Three-Tier Boundaries

### Always

- Preserve the exact public names, enum values/order, type alias, dataclass fields/order,
  immutability, equality, keyword-only signature, strict input types, same-source rule, six-field
  comparison, canonical change order, exact values, and empty-diff behavior.
- Use the standard library and existing `OnPageEvidence` only; keep the component pure, offline,
  deterministic, immutable, and isolated from active application paths.
- Run every required gate, confirm exact authorized scope, preserve tenant boundaries, obtain a
  separate zero-blocking read-only review, and deliver through a draft PR.

### Ask First

- Any change to the issue #60 public contract, comparison fields/order, error behavior, extraction
  semantics, or existing `OnPageEvidence` shape.
- Any new dependency, API, migration, persistence, audit integration, connector, job, worker,
  active-path wiring, framework abstraction, or protected product/architecture/goal/scope/decision
  document.
- Any auth, authorization, permissions, tenant-isolation, billing, secrets, infrastructure,
  deployment, production, external-account, or customer-facing change.

### Never

- Never compare different source URLs, silently coerce inputs, re-normalize values, hide changes,
  invent values, scores, causes, significance, confidence, recommendations, actions, or metrics.
- Never fetch, resolve DNS, read files, query a database, persist or log evidence, call a connector,
  schedule work, execute an action, deploy, or create an external/customer-facing effect.
- Never bypass tests or safety checks, modify unrelated files, force-push, commit to `main`, merge
  the implementation, or broaden this milestone beyond issue #60.

## Acceptance Criteria

- The exact five new public exports, six enum values, type alias, two immutable dataclasses, and
  keyword-only function match issue #60.
- Strict instance and exact same-source validation occurs without coercion or re-normalization.
- Only the six specified fields are compared with ordinary equality, each unequal field appears
  once in canonical order, and exact before/after values are retained.
- Equal evidence returns the exact empty immutable diff; all `None` and H1 tuple transitions obey
  ordinary equality; inputs remain unchanged.
- No parsing, persistence, API, migration, dependency, network, connector, job, worker, audit,
  execution, active-path wiring, production, or customer-facing behavior is added.
- Focused/full tests, Ruff lint/format, strict mypy, pip-audit, offline Alembic rendering,
  `make check`, and diff hygiene pass; only issue-authorized files change; tenant boundaries remain
  intact.
- A fresh separate read-only review reports zero blocking findings, and delivery is a dedicated
  branch with a draft PR. Nothing is merged or deployed by the implementation task.

## Delivery

Implement only after this planning PR merges and the orchestrator re-inspects `main` and queues
issue #60 by applying `codex-ready`. Work on a dedicated task branch, make an atomic implementation
commit, push it, and open a draft PR containing the exact scope, command evidence, risk assessment,
known limitations, and rollback. Do not merge or deploy.

This planning task itself changes exactly `docs/CURRENT-TASK.md` and `plans/PRODUCT-007.md`, is
delivered from its dedicated branch through a draft PR, and does not queue implementation, apply
`codex-ready`, merge implementation, deploy, or cause any external/customer-facing effect.

## Rollback

For PRODUCT-007 implementation, revert the implementation commit to remove
`src/growth_os/evidence/diff.py`, its package exports, `tests/evidence/test_diff.py`, and any bounded
README note. No schema, migration, durable data, production resource, credential, external system,
or customer-facing state needs recovery.

For planning issue #61, revert the documentation commit, restore PRODUCT-006 as the current task,
and remove this unimplemented PRODUCT-007 plan. No runtime, schema, data, production, external, or
customer-facing recovery is needed.
