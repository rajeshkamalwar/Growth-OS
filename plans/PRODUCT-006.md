# PRODUCT-006: Deterministic Offline On-Page Evidence Extraction

## Status and Authority

This is the reviewed pre-implementation specification for PRODUCT-006. The authoritative runtime
contract is [GitHub issue #56](https://github.com/rajeshkamalwar/Growth-OS/issues/56). Issue #57
authorizes this specification and the corresponding current-task update; it does not implement or
queue runtime work.

After this planning change merges, `docs/CURRENT-TASK.md` authorizes an implementation agent to
execute issue #56. The orchestrator owns implementation queueing and may apply `codex-ready` only
after re-inspecting the resulting `main`. This planning task does not apply that label, merge the
implementation, deploy, fetch any URL, or cause an external or customer-facing effect. If
implementation requires a contract or design change, update and review this specification before
changing runtime code.

## Objective

Add a small, strictly typed internal component that deterministically extracts a bounded set of
observed on-page SEO evidence from caller-supplied HTML and its source URL. It is the offline
parsing substrate for a later website crawler. It does not fetch, store, score, infer, recommend,
audit, execute, or act.

## Detected Stack and Versions

- Python: project requires `>=3.12`; the planning environment uses Python 3.12.
- Parser and URL handling: Python standard-library `html.parser.HTMLParser` and `urllib.parse`.
- Application package: `src/growth_os`, built with hatchling.
- Tests: pytest `>=9.0.3,<10` and pytest-asyncio `>=1.3,<2`; focused pure-component tests belong in
  `tests/evidence/test_on_page.py`.
- Quality: Ruff `>=0.8,<1`, strict mypy `>=1.13,<2`, and pip-audit `>=2.7,<3`.

Dependency ranges in `pyproject.toml` are authoritative. PRODUCT-006 adds no dependency and does
not require FastAPI, Pydantic, SQLAlchemy, Alembic, asyncpg, a database, Docker, or a running API.

## Risk Classification

PRODUCT-006 is low risk. It adds a pure, internal, reversible standard-library parser with no API,
schema, persistence, network, file, connector, execution, infrastructure, deployment, or
customer-facing effect. The issue #57 planning change is also low-risk documentation and task
authorization only.

## Complete Executable Commands

Run from the repository root. `make install` is needed only when the existing `.venv` is absent or
out of date; PostgreSQL is not needed for the focused pure-parser test.

```bash
# One-time environment and editable package install
make install

# Focused PRODUCT-006 test
.venv/bin/pytest tests/evidence/test_on_page.py

# Full regression, lint, formatting, typing, and dependency audit
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pip-audit

# Aggregate repository checks and final diff hygiene
make check
git diff --check
git status --short
```

`make check` repeats Ruff lint, strict mypy, full pytest, and pip-audit. It does not include Ruff
format verification or `git diff --check`, so run those explicit commands as well. Do not bypass a
failure.

## Affected Project Structure

The future issue #56 implementation is expected to remain within this focused internal slice. This
issue #57 planning change modifies exactly `docs/CURRENT-TASK.md` and this new plan.

```text
src/growth_os/evidence/__init__.py       package exports as needed
src/growth_os/evidence/on_page.py        immutable result and pure extraction function
tests/evidence/test_on_page.py           exact parsing, bounds, and non-action contract
README.md                                internal offline semantics and non-fetch boundary only
```

No API/router, repository, service, model, migration, dependency, worker, connector, execution, or
infrastructure file is authorized. Package exports may be limited to what is necessary to expose
the public internal contract; do not broaden the package surface.

## Public Internal Contract

Expose exactly this keyword-only function:

```python
extract_on_page_evidence(*, html: str, source_url: str) -> OnPageEvidence
```

`OnPageEvidence` is an immutable, equality-comparable typed value with exactly these fields, names,
types, and order:

```python
source_url: str
title: str | None
meta_description: str | None
canonical_url: str | None
robots: str | None
html_lang: str | None
h1_texts: tuple[str, ...]
```

Use a standard-library immutable typed value implementation. Do not add fields, mutable containers,
aliases, persistence metadata, scoring, issue classifications, inferred values, timestamps, IDs,
or framework models. Equality is value equality across exactly those fields, and mutation attempts
must fail.

The function accepts strings only. The implementation issue expressly requires `ValueError` for an
invalid source URL and for HTML above the size bound. Do not replace those failures with framework
validation or parser-specific exceptions. The type signature and focused tests must keep non-string
inputs outside the accepted contract without adding coercion.

## Source URL and HTML Input Contract

### HTML bound

- Measure the caller-supplied Python string with `len(html)`, which counts Unicode code points for
  ordinary Python strings.
- Accept lengths from zero through exactly 1,000,000 code points.
- Reject 1,000,001 or more code points with `ValueError` before parsing.
- Do not read HTML from a path, file, stream, URL, response, database, or connector.

### Source URL validation and normalization

Parse `source_url` with the standard library. It is valid only when all are true:

- it is absolute;
- its scheme equals `http` or `https` case-insensitively;
- it has a hostname; and
- it contains neither a username nor a password.

Reject invalid, relative, hostless, non-HTTP(S), or credentialed source URLs with `ValueError`.
Remove the fragment in returned `OnPageEvidence.source_url`. Otherwise retain the standard-library
parsed URL representation: do not fetch, resolve, probe, canonicalize hosts, infer ports, remove
queries, normalize paths, or apply third-party URL behavior. The fragment-free normalized source
is also the base used for canonical resolution.

## Shared Text and Attribute Normalization

Use `html.parser.HTMLParser` with HTML character-reference conversion enabled. For every extracted
text or content value:

1. decode HTML character references through standard-library HTML parsing;
2. collapse each consecutive run of Unicode whitespace to one ASCII space;
3. trim leading and trailing whitespace; and
4. treat the resulting empty string as absent.

This normalization applies to title text, meta `content`, HTML `lang`, H1 text, and canonical
`href`. It does not authorize interpretation, quality scoring, case folding of returned content,
Unicode normalization, or manufactured defaults. Tag and attribute names follow HTML
case-insensitive behavior.

## Exact Extraction Semantics

### Title

- Return the first non-empty `<title>` text in document order.
- Include descendant text, including text split by nested inline markup.
- Ignore a title whose normalized collected text is empty and continue to the next title.
- Ignore text nested in `script`, `style`, `template`, and `noscript` while collecting title text.
- Return `None` when no non-empty title exists.

### Meta description

- Inspect `<meta>` elements in document order.
- Match when `name`, after trimming, equals `description` case-insensitively.
- Return the normalized `content` from the first matching element whose normalized content is
  non-empty.
- Skip matching elements with missing or empty normalized content and continue in document order.
- Return `None` when no non-empty matching content exists.

### Robots

- Inspect `<meta>` elements in document order.
- Match when `name`, after trimming, equals `robots` case-insensitively.
- Return the normalized `content` from the first matching element whose normalized content is
  non-empty.
- Skip matching elements with missing or empty normalized content and continue in document order.
- Preserve directive spelling, order, punctuation, and content after shared whitespace
  normalization. Do not parse or interpret directives.
- Return `None` when no non-empty matching content exists.

### HTML language

- Use normalized non-empty `lang` from the first `<html>` start tag.
- If that first tag lacks a non-empty normalized `lang`, return `None`; do not infer language and
  do not fall through to a later `<html>` start tag.

### H1 text

- Collect every non-empty `<h1>` text in document order.
- Include descendant text and text split by nested inline markup.
- Ignore text nested in `script`, `style`, `template`, and `noscript` while collecting H1 text.
- Skip H1 elements whose normalized collected text is empty.
- Return all remaining values in an immutable tuple; return `()` when none exist.

### Canonical URL

- Inspect `<link>` elements in document order.
- Split each `rel` value on whitespace. A link matches when any token equals `canonical`
  case-insensitively.
- The candidate is the first matching link whose normalized `href` is non-empty. A matching link
  with missing or empty normalized `href` is skipped while finding that first candidate.
- Resolve an absolute, relative, or scheme-relative candidate against normalized `source_url` with
  `urllib.parse.urljoin`.
- Remove the resolved URL's fragment.
- Return it only when the resolved result is absolute HTTP(S), has a hostname, and contains no
  username or password, using the same validation rules as the source URL.
- If that first non-empty candidate is invalid, return `None` and do not fall through to any later
  canonical candidate.
- Return `None` when there is no candidate. Never fetch, resolve DNS, probe, or verify it.

## Duplicate, Malformed, and Ignored-Content Behavior

- Title, meta description, and robots use their explicit first-non-empty rules; canonical uses its
  distinct first-candidate rule and fails closed without later fallback when that candidate is
  invalid.
- H1 preserves every non-empty occurrence and document order. HTML language is tied only to the
  first HTML start tag.
- Mixed-case tags, attribute names, and matching tokens behave case-insensitively as described,
  while extracted content retains its spelling and meaningful order.
- Standard HTML void-element handling must not corrupt later text collection.
- Malformed but `HTMLParser`-parseable input returns deterministic best-effort evidence rather than
  raising parser-specific errors. Do not add a repairing DOM, browser, or alternate parser.
- Track ignored `script`, `style`, `template`, and `noscript` nesting so their text never contributes
  to title or H1 values, including when such elements appear inside those collectors.
- Absent and normalized-empty scalar values return `None`; absent/non-empty H1 values follow the
  immutable-tuple contract.

## Implementation and Import Boundaries

- Use only `html.parser.HTMLParser`, `urllib.parse`, and other Python standard-library utilities
  required for the immutable typed value and normalization.
- Keep `growth_os.evidence.on_page` independent of FastAPI, Pydantic, SQLAlchemy, Alembic,
  repositories, services, tenant context, database sessions/models, connectors, execution, jobs,
  workers, and browser or HTTP clients.
- Do not add a generalized DOM, crawler, plugin, provider, scoring, issue-classification, storage,
  service, repository, or persistence abstraction.
- Do not import the evidence component into `growth_os.main`, API routers, services, repositories,
  models, connectors, execution, workers, or other active application paths in this milestone.
- Add no API endpoint, migration, database model, dependency, credential, connector behavior, job,
  browser automation, network/DNS/file/database access, or external side effect.
- Do not log, audit, persist, or otherwise expose caller-supplied HTML or extracted content.
- README documentation is limited to internal offline semantics and the explicit non-fetch
  boundary. It must not imply that a crawler, monitoring, scoring, recommendation, persistence, or
  execution capability now exists.
- Do not alter authentication, authorization, tenant isolation, permissions, billing, secrets,
  infrastructure, deployment, or protected product, goal, architecture, scope, or decision docs.

## Test Matrix

### Result shape and ordinary extraction

- Assert exact field names/order/types, immutable `h1_texts`, value equality, and failed mutation.
- Cover a normal document containing every field, multiple H1s, entity decoding, Unicode
  whitespace normalization, leading/trailing trimming, nested inline markup, and document order.
- Assert all absent values are `None` except `h1_texts == ()`.

### Duplicate, blank, mixed-case, void, and malformed input

- Prove blank titles are skipped before the first non-empty title.
- Prove blank matching description and robots contents are skipped before the first non-empty
  match, then later duplicates do not replace it.
- Prove only the first HTML start tag controls `html_lang`, including a blank/missing first `lang`.
- Prove all non-empty H1s are retained in order and blank H1s are omitted.
- Cover mixed-case tag names, attribute names, description/robots names, and canonical rel tokens;
  multi-token rel values; standard void elements; and deterministic malformed-but-parseable HTML.
- Cover ignored `script`, `style`, `template`, and `noscript` content nested inside title and H1,
  including nested ignored regions where useful to prove state restoration.

### Canonical behavior

- Cover valid absolute, relative, and scheme-relative hrefs resolved against the fragment-free
  source, with query/path preservation and fragment removal.
- Cover blank/missing href before a later valid first candidate.
- Cover invalid, hostless, non-HTTP(S), and credentialed first non-empty candidates.
- For every invalid first candidate, prove the result is `None` even when a later valid canonical
  link exists.
- Cover duplicate rel tokens, mixed case, whitespace-separated token matching, and non-matching
  substring values.

### Source URL and size boundaries

- Prove source fragment removal and preservation of the remaining standard-library parsed URL.
- Reject relative, hostless, non-HTTP(S), username-bearing, and password-bearing source URLs with
  `ValueError`; cover case-insensitive HTTP(S) acceptance.
- Accept exactly 1,000,000 Unicode code points and reject 1,000,001 with `ValueError`, using input
  that demonstrates code-point rather than encoded-byte measurement.
- Prove inputs are not coerced from non-string objects.

### Non-action and architecture boundaries

- Instrument socket/DNS, standard-library HTTP/URL opening, filesystem opening, database/session,
  connector, audit, execution, and other external-call seams so ordinary extraction fails the test
  if any is invoked.
- Import the component in isolation and assert its module dependency boundary excludes FastAPI,
  Pydantic, SQLAlchemy, repository/service/database, connector, execution, worker, browser, and
  HTTP-client modules.
- Statically inspect the diff/package references to prove there is no API route, job, migration,
  dependency, persistence change, or import into an active application path.
- Run the full repository suite to prove existing tenant, foundation, execution, audit, handoff,
  health, and configuration behavior is unchanged.

Tests must verify observable contract behavior rather than a particular private parser-helper
layout. No arbitrary coverage percentage is added.

## Dependency-Ordered Implementation Tasks

### Task 1: Define the immutable value and validate bounded inputs

Create the evidence package and `OnPageEvidence` with exactly the specified fields. Add explicit
source URL parsing/validation/fragment removal and the exact HTML code-point bound.

Dependencies: existing `src/growth_os` package only.

Acceptance: imports are standard-library-only; the result is strictly typed, immutable, and
equality-comparable; source URL and 1,000,000/1,000,001 boundaries match issue #56.

Verification: run focused result-shape, source validation, input-type, and size-boundary tests plus
Ruff and strict mypy.

### Task 2: Implement deterministic standard-library extraction

Build the focused `HTMLParser` state machine and shared normalization needed for exact title,
description, robots, language, H1, canonical, duplicate, malformed, and ignored-content behavior.

Dependencies: Task 1 fixes the returned type and normalized source base.

Acceptance: every extraction rule and order/fallback distinction matches issue #56; malformed but
parseable input is best-effort and deterministic; no external or framework behavior appears.

Verification: run the complete focused parser suite, Ruff, and strict mypy.

### Checkpoint: Pure parsing contract

- Exact returned fields, immutability, equality, normalization, and absence semantics are proven.
- Source and canonical validation share the fixed HTTP(S)/host/no-credentials rule while preserving
  their distinct error/fallback behavior.
- Duplicate, malformed, void, mixed-case, document-order, and ignored-content cases are proven.

### Task 3: Prove non-action and import boundaries

Add focused dynamic and static assertions showing extraction cannot fetch or access external state
and is not wired into active application paths.

Dependencies: Task 2 completes the component under test.

Acceptance: socket, DNS, HTTP, filesystem, database, connector, audit, execution, and other external
seams are untouched; no API, job, migration, dependency, persistence, or operational import exists.

Verification: run focused boundary tests and inspect `rg` references and the final file list.

### Task 4: Document only the offline internal behavior

Update README with the internal function/result purpose and explicit caller-supplied/no-fetch
boundary. Do not claim crawler, monitoring, scoring, recommendation, persistence, or action support.

Dependencies: Tasks 1-3 establish the behavior being documented.

Acceptance: README matches issue #56 without broadening product capability or implying an external
side effect.

Verification: compare README wording against issue #56, this plan, and public package exports.

### Task 5: Run full verification and scope review

Run the focused test, full pytest, Ruff lint/format check, strict mypy, pip-audit, `make check`, and
`git diff --check`. Inspect the final diff and status against the allowed file set.

Dependencies: Tasks 1-4 are complete.

Acceptance: every applicable gate passes without bypass; only authorized component, test, export,
and README files change; protected documents, tenant boundaries, dependencies, migrations, API,
persistence, and external behavior remain untouched.

Verification: preserve exact command results for the draft PR and compare the final implementation
field by field with issue #56, this specification, and `docs/CURRENT-TASK.md`.

### Task 6: Obtain independent read-only review

Give a fresh reviewer issue #56, this specification, the stable final diff, and verification
results. The reviewer must not edit files and must assess exact shape/signature, URL/bound rules,
all extraction and duplicate/fallback semantics, ignored/malformed behavior, import/non-action
boundaries, tests, scope, risk, and rollback.

Dependencies: Task 5 provides a stable verified diff.

Acceptance: zero blocking findings. Fix any finding on the task branch, rerun affected and full
gates, and obtain a fresh read-only review before opening or updating the draft PR.

## Three-Tier Boundaries

### Always

- Preserve the exact keyword-only signature, immutable seven-field result, URL rules, HTML bound,
  normalization, document-order, duplicate, ignored-content, malformed, and canonical semantics.
- Use the standard library only and keep the component pure, offline, isolated, deterministic, and
  free of logging/auditing of supplied HTML.
- Prove focused behavior and non-action/import boundaries, run all repository gates, and obtain an
  independent blocking-issue-free review before a draft PR.

### Ask First

- Any contract change to fields, signature, exception behavior fixed by issue #56, normalization,
  first/non-empty/fallback rules, URL validation, maximum size, or ignored elements.
- Any API, persistence, migration, dependency, crawler, connector, worker, job, execution, scoring,
  recommendation, inference, provider, plugin, browser, network, file, database, audit, or active
  application-path integration.
- Any authentication, authorization, tenant, permission, billing, secret, infrastructure,
  deployment, protected-document, production, or external/customer-facing change.

### Never

- Fetch, resolve DNS, probe, verify, open, persist, score, infer from, recommend about, log, or audit
  caller-supplied HTML or URLs in this component.
- Fall through to a later canonical after the first non-empty candidate is invalid, infer language,
  interpret robots, manufacture metadata, or silently broaden parser behavior.
- Add a third-party parser or general-purpose crawler/DOM abstraction, queue implementation from
  this planning task, apply `codex-ready`, bypass failing gates, merge, deploy, or modify production.

## Fixed Assumptions and Resolved Questions

- Authority: issue #56 is the runtime contract; issue #57 and this document authorize planning.
- Location: implementation lives in `src/growth_os/evidence/on_page.py`, with package exports only
  as needed and focused tests in `tests/evidence/test_on_page.py`.
- Result: exactly seven fields in the specified order; immutable, equality-comparable, strictly
  typed, and with H1s stored as a tuple.
- Inputs: caller-supplied strings only; source URL invalidity and HTML over 1,000,000 code points
  raise `ValueError`; no coercion or external acquisition.
- Parsing: `HTMLParser` with entity decoding, shared Unicode-whitespace normalization, standard
  case-insensitive HTML names, and deterministic best effort for parseable malformed input.
- Selection: title/description/robots are first-non-empty, HTML language is from the first HTML
  start tag only, H1 includes every non-empty value, and canonical rejects an invalid first
  candidate without later fallback.
- Canonical: resolve with `urljoin` against fragment-free source, then remove its fragment and apply
  absolute HTTP(S)/hostname/no-credentials validation without contacting it.
- Ignored content: script/style/template/noscript text never contributes to title or H1.
- Architecture: a pure standard-library internal module with no API, database, persistence,
  connector, worker, execution, crawler, or external-action integration.
- Delivery: dedicated implementation branch, complete gates, independent read-only review, and
  draft PR only; no merge or deployment.

## Success Criteria

- The exact signature and immutable result shape are importable and strict typing passes.
- Focused tests prove every input, normalization, extraction, duplicate, malformed, ignored-content,
  source/canonical validation, invalid-first-canonical, and 1,000,000-code-point rule from issue #56.
- Dynamic and static evidence proves extraction has no socket, DNS, HTTP, filesystem, database,
  connector, audit, execution, persistence, API, job, worker, or other external/operational effect.
- No dependency, migration, schema, route, tenant/auth/billing/permission, infrastructure,
  deployment, or protected-document change occurs.
- Focused/full tests, Ruff lint/format, strict mypy, pip-audit, `make check`, and diff hygiene pass;
  a separate read-only reviewer reports zero blocking findings; a draft PR is ready.

## Risks and Mitigations

- Parser-state leakage from malformed or ignored nested content could contaminate later title/H1
  text. Use explicit state, document-order fixtures, and malformed/nested ignored-content tests.
- Duplicate selection could accidentally use last-match or inconsistent fallback. Test blank-first,
  first-non-empty, later duplicates, and canonical's distinct invalid-first no-fallback rule.
- URL parsing could accidentally allow credentials/non-HTTP schemes or mutate more than fragments.
  Centralize the exact standard-library validation rule and test source/canonical absolute,
  relative, scheme-relative, hostless, credentialed, query, path, and fragment cases.
- Large input could be measured as bytes or parsed before rejection. Check `len(html)` before parser
  work and test exactly 1,000,000 versus 1,000,001 Unicode code points.
- Scope creep toward a crawler or active monitoring path could introduce external effects. Enforce
  import/reference tests, inspect changed files, and keep README claims explicitly offline.

## Rollback and Recovery

Revert the PRODUCT-006 implementation commit to remove the evidence module, package exports,
focused tests, and README note. There is no schema, migration, durable data, production resource,
credential, connector state, external system, or customer-facing behavior to recover. No database
downgrade or data restoration is needed.

For planning issue #57 only, revert its documentation commit to restore PRODUCT-005 as the recorded
current task and remove this unimplemented PRODUCT-006 specification. That documentation-only
rollback has no runtime, schema, data, production, or external effect.

## Open Questions

None. Issue #56 fixes the signature, result fields, input and URL rules, size bound, text
normalization, extraction order and fallback semantics, ignored content, implementation/import
boundaries, tests, verification, delivery, risk, and rollback. Any new question that would change
those contracts must pause implementation and be resolved in the specification before runtime work
continues.
