# Current Task

## Task ID

PRODUCT-006 ([GitHub issue #56](https://github.com/rajeshkamalwar/Growth-OS/issues/56))

## Authorization

Add a small, strictly typed internal component for deterministic offline extraction of bounded
on-page SEO evidence from caller-supplied HTML and its source URL. Follow the reviewed
implementation specification in [`plans/PRODUCT-006.md`](../plans/PRODUCT-006.md); issue #56
remains the authoritative runtime contract. If implementation requires a contract or design
change, update and review the specification before changing runtime code.

This current-task update authorizes implementation only after this planning PR merges. This
planning task does not queue implementation, apply `codex-ready`, merge the implementation,
deploy, fetch any URL, or cause any external or customer-facing effect. The orchestrator owns
implementation queueing and may apply `codex-ready` only after re-inspecting the resulting `main`.

## Goal

Create `src/growth_os/evidence/on_page.py` and package exports as needed, exposing exactly:

```python
extract_on_page_evidence(*, html: str, source_url: str) -> OnPageEvidence
```

`OnPageEvidence` is an immutable, equality-comparable typed value with exactly:

```python
source_url: str
title: str | None
meta_description: str | None
canonical_url: str | None
robots: str | None
html_lang: str | None
h1_texts: tuple[str, ...]
```

The pure component is parsing substrate for a later crawler. It accepts caller-supplied strings;
it does not fetch, persist, score, infer, recommend, audit, log supplied HTML, or act.

## Input and Normalization Contract

- Reject an invalid source URL or HTML longer than 1,000,000 Unicode code points with
  `ValueError`. Exactly 1,000,000 code points is accepted. The function accepts strings only.
- A source URL is valid only when absolute, has a case-insensitive `http` or `https` scheme and a
  hostname, and contains no username or password. Remove its fragment in returned `source_url`;
  otherwise retain the standard-library parsed URL representation. Perform no network request.
- Parse with Python's standard-library `html.parser.HTMLParser` and `urllib.parse` only, with HTML
  character references decoded. Malformed but parseable HTML produces deterministic best-effort
  evidence rather than parser-specific errors.
- For every extracted text or content value, decode entities, collapse consecutive Unicode
  whitespace to one ASCII space, trim, and treat an empty normalized value as absent.
- Tag and attribute names follow HTML case-insensitive behavior.

## Exact Extraction Contract

- `title`: first non-empty `<title>` text in document order, including descendant text.
- `meta_description`: normalized `content` of the first `<meta>` whose trimmed `name` equals
  `description` case-insensitively and whose normalized content is non-empty.
- `robots`: normalized `content` of the first `<meta>` whose trimmed `name` equals `robots`
  case-insensitively and whose normalized content is non-empty. Preserve directive spelling,
  order, and content; do not interpret it.
- `html_lang`: normalized non-empty `lang` from the first `<html>` start tag. Do not infer it and
  do not fall through to a later `<html>` tag.
- `h1_texts`: every non-empty `<h1>` text in document order, including descendant text, returned
  as an immutable tuple.
- Ignore text nested inside `script`, `style`, `template`, and `noscript` while collecting title
  and H1 text.
- `canonical_url`: select the first `<link>` in document order whose whitespace-separated `rel`
  tokens include `canonical` case-insensitively and whose normalized `href` is non-empty. Resolve
  relative and scheme-relative hrefs against normalized `source_url` with `urllib.parse.urljoin`,
  remove the fragment, and return the result only when it is absolute HTTP(S), has a hostname, and
  has no username/password. If this first candidate is invalid, return `None`; never select a
  later candidate.
- Repeated title/description/robots values use the stated first-non-empty rules. Preserve all
  non-empty H1s in order. Do not score quality or manufacture defaults.

## Strict Boundaries

- Use the Python standard library only and add no dependency.
- Keep the component independent of FastAPI, SQLAlchemy, repositories, services, tenant context,
  connectors, execution, and workers.
- Add no API route, migration, database model, credential, connector behavior, job, browser
  automation, generalized DOM/crawler/plugin/provider/scoring/issue-classification/persistence
  abstraction, network/DNS/file/database access, or external side effect.
- Do not alter authentication, authorization, permissions, tenant isolation, billing, secrets,
  infrastructure, deployment, or protected product/architecture/goal/decision documents.
- README changes are limited to the internal offline semantics and explicit non-fetch boundary.

## Verification Gates

- Focused tests prove exact fields, immutability/equality, ordinary and malformed extraction,
  entity/whitespace handling, nested markup, duplicate and blank behavior, document order,
  mixed-case parsing, void elements, ignored content, all canonical variants, source validation,
  exact HTML size boundary, non-action behavior, and import/scope boundaries.
- Run `.venv/bin/pytest tests/evidence/test_on_page.py`, full `.venv/bin/pytest`,
  `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .`, `.venv/bin/mypy`,
  `.venv/bin/pip-audit`, `make check`, and `git diff --check` without bypassing failures.
- Confirm only issue-authorized implementation, focused test, package-export, and README files
  change; tenant boundaries remain untouched; and no migration, route, dependency, persistence,
  execution, connector, worker, or external-action integration appears.
- Obtain a separate read-only reviewer pass with zero blocking findings. Deliver on a dedicated
  task branch through a draft pull request. Do not merge or deploy.

## Risk and Rollback

PRODUCT-006 is low risk: it is a pure, internal, standard-library-only parser with no external
side effect, storage, schema, or customer-facing behavior. Revert the implementation commit to
remove it; no schema, durable data, production resource, or external system needs recovery.

For this planning-only issue #57 change, revert its documentation commit to restore PRODUCT-005 as
the recorded current task and remove the unimplemented PRODUCT-006 plan. That rollback has no
runtime, schema, data, production, or external effect.
