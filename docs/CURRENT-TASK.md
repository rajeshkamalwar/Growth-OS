# Current Task

## Task ID

PRODUCT-007 ([GitHub issue #60](https://github.com/rajeshkamalwar/Growth-OS/issues/60))

## Authorization

Add a strictly typed, immutable, deterministic internal component that compares two
`OnPageEvidence` values for the same normalized source URL and reports exact observed field-level
changes in stable order. Follow the reviewed implementation specification in
[`plans/PRODUCT-007.md`](../plans/PRODUCT-007.md); issue #60 remains the authoritative runtime
contract. If implementation requires a contract or design change, update and review the
specification before changing runtime code.

This current-task update authorizes implementation only after this planning PR merges. This
planning task does not queue implementation, apply `codex-ready`, merge the implementation,
deploy, or cause any external or customer-facing effect. The orchestrator owns implementation
queueing and may apply `codex-ready` only after re-inspecting the resulting `main`.

## Public Internal Contract

Create `src/growth_os/evidence/diff.py` and export exactly these new names from
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

The dataclasses are equality-comparable and immutable, with exactly the listed fields in the
listed order. Add no timestamp, ID, count, severity, confidence, meaning, cause, action, or
inferred value.

## Exact Comparison Behavior

- Accept `OnPageEvidence` instances only. Reject either non-instance with `TypeError` and do not
  coerce it.
- Require exact equality of `previous.source_url` and `current.source_url`; otherwise raise
  `ValueError`. Do not re-normalize, parse, resolve, or fetch either URL.
- Compare only `title`, `meta_description`, `canonical_url`, `robots`, `html_lang`, and `h1_texts`
  with ordinary Python value equality.
- Emit exactly one `OnPageEvidenceChange` for each unequal field, retaining the exact value from
  `previous` as `before` and the exact value from `current` as `after`.
- Always order changes as `title`, `meta_description`, `canonical_url`, `robots`, `html_lang`, then
  `h1_texts`, regardless of input or construction order. Omit equal fields.
- Equal evidence returns
  `OnPageEvidenceDiff(source_url=previous.source_url, changes=())`.
- Treat absence-to-value, value-to-absence, value-to-different-value, and H1 tuple content, order,
  or length differences as ordinary observed changes. Do not collapse, normalize, reinterpret,
  redact, score, or judge them.
- Do not mutate either input or reuse a mutable container.

## Strict Boundaries

- Use only the Python standard library and the existing `OnPageEvidence`; add no dependency.
- Keep the component independent of FastAPI, Pydantic, SQLAlchemy/Alembic, repositories, services,
  tenant context, connectors, execution, jobs, workers, browsers, HTTP clients, and active
  application paths.
- Do not change extraction semantics or the existing seven-field `OnPageEvidence` contract.
- Add no persistence, audit event, API route, callback, logging of evidence values, collection,
  scheduling, monitoring claim, score, recommendation, credential, migration, database model,
  connector behavior, or external action.
- README changes, if made during implementation, are limited to internal offline comparison
  semantics and the explicit non-action boundary.
- Do not alter authentication, authorization, permissions, tenant isolation, billing, secrets,
  infrastructure, deployment, or protected product, architecture, goal, scope, or decision docs.

## Verification Gates

- Focused tests prove exact enum values; exact dataclass fields and order; equality, immutability,
  tuple-backed changes, and public exports; no-change behavior; every independent field change;
  all-field canonical ordering; exact `None` transitions and H1 tuple changes; strict type and
  same-source errors; no coercion or mutation; non-action behavior; and import/scope boundaries.
- Run `.venv/bin/pytest tests/evidence/test_diff.py`, full `.venv/bin/pytest`,
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy`,
  `.venv/bin/pip-audit`, `make check`, offline Alembic upgrade/downgrade SQL rendering, and
  `git diff --check` without bypassing failures.
- Confirm only issue-authorized diff component, focused test, package-export, and optional bounded
  README files change. Tenant boundaries remain intact, and no migration, route, dependency,
  persistence, execution, connector, job, worker, or active-path integration appears.
- Obtain a fresh separate read-only reviewer pass with zero blocking findings. Deliver on a
  dedicated task branch through a draft pull request. Do not merge or deploy.

## Risk and Rollback

PRODUCT-007 is low risk: it is a pure, deterministic, internal, standard-library-only comparison
with no external side effect, storage, schema, or customer-facing behavior. Revert the
implementation commit to remove the diff component, exports, tests, and optional README note; no
schema, durable data, production resource, or external system needs recovery.

For this planning-only issue #61 change, revert its documentation commit to restore PRODUCT-006 as
the recorded current task and remove the unimplemented PRODUCT-007 plan. That rollback has no
runtime, schema, data, production, or external effect.
