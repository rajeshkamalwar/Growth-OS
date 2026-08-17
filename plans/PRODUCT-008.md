# PRODUCT-008: Fail-Closed Single-Page Public HTML Acquisition

## Status and Authority

This is the reviewed pre-implementation execution contract for PRODUCT-008. The authoritative
runtime contract is [GitHub issue #64](https://github.com/rajeshkamalwar/Growth-OS/issues/64); this
plan specifies how to implement and verify that issue without broadening or weakening it. Issue #65
authorizes only this plan and the corresponding current-task update.

After this planning PR merges and the orchestrator re-inspects `main`, `docs/CURRENT-TASK.md`
authorizes an implementation agent to execute issue #64. The orchestrator owns queueing and may
apply `codex-ready` only then. This planning task does not queue implementation, apply a label,
merge, deploy, call a URL, or create any external/customer-facing effect.

The user explicitly approved development of this material security boundary on 2026-08-17. That
approval covers implementation, comprehensive fake-only tests, the exact dependency change, and a
reviewed draft PR only. PRODUCT-008 is **high risk** because it establishes outbound-network and
SSRF policy. The implementation controller must not auto-merge it: after all gates and a fresh
security-focused read-only review pass have zero blocking findings, the exact reviewed draft PR
must remain open for separate human merge approval.

## Objective and Non-Action Boundary

Add an explicit async primitive that fetches one public HTTP(S) HTML page, following only its
bounded redirect chain, for later use with the existing offline evidence extractor. It runs only
when a caller directly invokes it. It is not integrated into an API, startup path, service,
repository, database, connector, execution path, job, worker, scheduler, CLI, or deployment.

Do not implement autonomous or scheduled crawling, robots.txt decisions, tenant/audit linkage,
rate limiting, concurrency control, persistence, idempotency, parsing, extraction, hashing,
monitoring, or metrics. Do not import the acquisition module from active application paths. Do not
contact a real external website in tests, validation, review, or examples, and do not deploy.

## Inspected Repository and Tooling State

- Python requirement is `>=3.12`; the inspected environment is Python 3.12.13.
- `pyproject.toml` is the only dependency manifest; there is no lockfile. Production dependencies
  currently include FastAPI, SQLAlchemy/Alembic, asyncpg, pydantic-settings, and Uvicorn.
- `aiohttp` is neither declared nor installed in the inspected environment. Add exactly
  `aiohttp>=3.12,<4` to `[project].dependencies`; install the resolved dependency set for checks,
  but create no lockfile unless issue #64 is separately amended.
- Existing offline HTML extraction is `src/growth_os/evidence/on_page.py`, publicly exported by
  `growth_os.evidence`. Acquisition must not change or automatically invoke it.
- Tests use pytest/pytest-asyncio; quality gates use Ruff, strict mypy, pip-audit, `make check`, and
  offline Alembic SQL rendering. No database or live network is required for PRODUCT-008 tests.

## Authorized Files and Dependency

The future implementation may change only:

```text
pyproject.toml                           add aiohttp>=3.12,<4 only
src/growth_os/acquisition/__init__.py   exact public exports
src/growth_os/acquisition/html.py       acquisition and security boundary
tests/acquisition/test_html.py          controlled fake-only contract/security tests
```

No README, runtime integration, migration, schema, model, route, service, repository, connector,
execution, job, worker, scheduler, infrastructure, deployment, secret, auth, billing, permission,
tenant-isolation, or protected product/architecture/goal/scope/decision document change is
authorized. Add no other HTTP, DNS, URL, DOM, crawling, browser, retry, or scheduling dependency.

## Exact Public Contract

Export only these four names from `growth_os.acquisition`:

```python
class HtmlFetchErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    DISALLOWED_PORT = "disallowed_port"
    DNS_FAILURE = "dns_failure"
    DISALLOWED_ADDRESS = "disallowed_address"
    TIMEOUT = "timeout"
    TLS_FAILURE = "tls_failure"
    NETWORK_FAILURE = "network_failure"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    INVALID_REDIRECT = "invalid_redirect"
    HTTP_STATUS = "http_status"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    BODY_TOO_LARGE = "body_too_large"
    UNSUPPORTED_CHARSET = "unsupported_charset"


class HtmlFetchError(RuntimeError):
    code: HtmlFetchErrorCode
    status_code: int | None


@dataclass(frozen=True, slots=True)
class FetchedHtml:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: str
    redirect_chain: tuple[str, ...]


async def fetch_html(*, url: str) -> FetchedHtml: ...
```

`FetchedHtml` is equality-comparable, immutable, and has exactly those fields and order.
`HtmlFetchError` exposes stable `code` and nullable `status_code`; `status_code` is non-null only for
`HTTP_STATUS`. Its stable message must be value-redacted and contain no body, DNS result, socket or
certificate detail, header, query, fragment, credential, or upstream exception text. Do not log.

Reject non-string input with `TypeError` without coercion. Map every specified policy, transport,
and content failure to `HtmlFetchError`; never leak raw aiohttp, socket, TLS, timeout, Unicode,
codec, or URL-parser exceptions. Preserve exception chaining only when useful internally. Never
swallow `asyncio.CancelledError`.

## One-Parser URL Normalization and Admission

Use a single parser/URL object representation for validation, stable serialization, redirect
resolution, and the exact value passed to aiohttp, preventing validation/connection parser drift.
Apply the same process to the initial URL and every redirect destination:

- Require an absolute case-insensitive `http` or `https` scheme and a non-empty DNS hostname or IP
  literal. Map malformed URL, host, or IDNA input to `INVALID_URL`.
- Reject username/password and empty-but-present userinfo.
- Permit only port 80 for HTTP and 443 for HTTPS. Normalize an explicitly supplied default port
  consistently. Map every non-default or syntactically invalid explicit port to `DISALLOWED_PORT`.
- Remove fragments, preserve path and query, and perform no semantic path/query rewriting beyond
  the selected parser's stable serialization.
- Never expose a caller option for headers, proxy, cookies, credentials, TLS, resolver, limits,
  method, retry, or redirect policy.

`requested_url` is the normalized fragment-free initial URL. Resolve each `Location` against the
current normalized URL before repeating full normalization/admission. `redirect_chain` contains
every normalized URL actually requested, starting with `requested_url` and ending with
`final_url`.

## Global-Only DNS Admission and Resolver Pinning

Before **every** request hop, including cross-origin redirects:

1. Validate an IP literal directly; otherwise call the event loop's `getaddrinfo` for stream
   sockets under the 30-second overall deadline.
2. Require at least one answer. Empty answers and resolver failures map to `DNS_FAILURE`.
3. Accept only IPv4/IPv6 values for which `ipaddress.ip_address(...).is_global` is true. If any
   answer is malformed, unsupported, zone-scoped, or non-global, reject the entire hop with
   `DISALLOWED_ADDRESS`; mixed safe/unsafe answers are wholly rejected.
4. Deduplicate valid addresses without adding, converting, or broadening them.
5. Pin exactly that validated set in a per-hop aiohttp `TCPConnector` custom resolver. Disable DNS
   caching, ensure the connector never performs another system resolution, and retain the original
   URL hostname for TLS SNI and certificate/hostname verification.
6. Close each per-hop session/connector on success, failure, redirect, timeout, and cancellation.

Admission must reject loopback, private, link-local, shared, documentation, benchmarking,
reserved, unspecified, multicast, and all other non-global IPv4/IPv6; IPv4-mapped private IPv6;
mixed answers; and alternative numeric spellings that the platform resolver maps to non-global
addresses.

## Exact Request, TLS, Timeout, and Redirect Policy

Each hop is exactly one GET with automatic redirects disabled and exactly these headers:

```text
User-Agent: GrowthOSBot/0.1
Accept: text/html,application/xhtml+xml
Accept-Encoding: identity
```

Use aiohttp/default platform certificate and hostname verification without an insecure override.
Use `trust_env=False`, a disabled/dummy cookie jar, no proxy, auth, referrer, caller headers, cache,
browser/JavaScript behavior, application retry, POST, HEAD fallback, or alternate method. Configure
a 5-second connection timeout and 10-second socket-read timeout inside one 30-second overall
deadline that covers DNS, all requests, response streaming, and the complete redirect chain.

Handle only 301, 302, 303, 307, and 308 as redirects. Require exactly one non-empty parseable
`Location`, resolve it against the current normalized URL, and re-normalize, revalidate, re-resolve,
and re-pin before the next GET. Cross-origin public redirects are allowed under the identical
policy. Permit at most five redirect responses, hence six requests total; a sixth redirect raises
`TOO_MANY_REDIRECTS` without fetching its destination. Missing, blank, or invalid `Location` raises
`INVALID_REDIRECT`.

Any non-redirect response other than 200 raises `HTTP_STATUS`, exposing only its integer status.
Never read or return a failed response body.

## Content, Size, Charset, and Error Mapping

For a 200 response:

- Parse and accept only base media type `text/html` or `application/xhtml+xml`, normalized to
  lowercase. Reject absent or other content type before consuming the body with
  `UNSUPPORTED_CONTENT_TYPE`.
- Stream aiohttp's automatically decompressed bytes in bounded chunks. Accept exactly 2,000,000
  decompressed bytes; on the first byte beyond, fail immediately with `BODY_TOO_LARGE`.
- Honor a valid declared charset; use UTF-8 when absent. Map an unknown/invalid declared charset to
  `UNSUPPORTED_CHARSET`.
- Decode malformed byte sequences with replacement for deterministic acquisition and no codec
  leakage. Return only normalized base content type and decoded body; do not parse, hash, persist,
  audit, or log content.

Map URL/parser/IDNA/host failures to `INVALID_URL`; invalid/non-default explicit ports to
`DISALLOWED_PORT`; resolver failure/empty results to `DNS_FAILURE`; unsafe/unsupported answers to
`DISALLOWED_ADDRESS`; overall/connect/read timeout to `TIMEOUT`; certificate, hostname, and TLS
handshake failures to `TLS_FAILURE`; and other aiohttp client/connection failures to
`NETWORK_FAILURE`. Redirect, status, content type, size, and charset failures use their exact enum
codes. Do not retry any failure. Cleanup and redaction rules apply to every mapping.

## Acceptance Test Matrix

All response/transport tests use controlled fakes. Address tests inject or monkeypatch resolver
results without opening sockets. Add a network-denial guard so any accidental real DNS/socket use
fails the suite.

### Public shape and error safety

- Prove exact enum names/values/order, package exports, dataclass fields/order, tuple chain,
  equality/immutability, keyword-only signature, and strict non-coercing input type.
- Prove stable error codes/status values/messages, redaction of URL query/fragment/userinfo,
  response bodies, headers, DNS/socket/TLS/certificate/upstream text, and no raw exception leakage
  or logging.

### URL and redirect behavior

- Cover mixed-case schemes, DNS names, IPv4/IPv6 literals, IDNA/malformed host/URL input,
  fragment removal, preserved path/query, explicit/implicit default ports, every invalid and
  non-default port, and every form of userinfo including empty-present values.
- Cover relative, scheme-relative, same-origin, and cross-origin redirects; all five accepted
  redirect codes; exact normalized chain; missing/blank/multiple-or-invalid `Location`; five-hop
  acceptance; sixth-redirect failure; and proof no seventh request occurs.

### SSRF, rebinding, and pinning

- Cover direct-IP and resolved global/non-global/mixed/empty/malformed/unsupported/zone-scoped/
  mapped answers, representative prohibited ranges, deduplication, and alternate numeric spellings.
- Prove resolution and admission happen per hop, redirect rebinding is rejected, only the validated
  address set reaches the custom resolver, system DNS is not called again, connector DNS cache is
  disabled, and original hostname remains the TLS SNI/certificate name.
- Prove every per-hop session and connector closes on success, redirect, each failure, timeout, and
  cancellation.

### Transport, response, and cancellation

- Assert exact GET method/headers, TLS defaults, `trust_env=False`, dummy cookies, absent proxy,
  auth, referrer, caller overrides, retries and automatic redirects, plus exact connect/read/overall
  timeout behavior.
- Prove 200-only success and that non-200/invalid redirect/unsupported media failures do not read
  bodies. Cover media-type case/parameters and absent/near-miss types.
- Prove chunked decompressed limits at 2,000,000 and 2,000,001 bytes, early termination, declared
  and default charset, unknown/invalid charset, and replacement decoding.
- Prove timeout/TLS/network mappings, no retries, cleanup, and direct propagation of
  `asyncio.CancelledError` without logging.

### Repository boundary

- Prove no real network occurs and no API, persistence, connector, execution, job, worker, startup,
  CLI, scheduler, or other active-path import/call exists.
- Inspect imports/dependencies to prove only aiohttp was added and no parser, browser, retry,
  crawling, or scheduling dependency appeared.
- Prove evidence extraction, tenant boundaries, migrations, and all existing behavior remain
  unchanged through focused/full repository gates.

Tests should verify observable issue #64 behavior without unnecessarily fixing private helper
layout. Test seams for controlled resolution and transport may remain private; the package must
export only the four public names.

## Dependency-Ordered Implementation Tasks

### Task 1: Add the exact dependency and immutable public surface

Add only `aiohttp>=3.12,<4`, the acquisition package, exact enum/error/result/function contract,
and exact four-name package export list. Define stable redacted error construction before network
logic so every later boundary uses it.

Dependencies: merged issue #65 planning PR and re-inspected `main`.

Acceptance: dependency, signatures, fields, enum values, equality/immutability, exports, strict
input typing, and message/status redaction exactly match issue #64.

Verification: focused public-contract/error tests, dependency diff inspection, Ruff, and mypy.

### Task 2: Implement one-parser URL normalization

Create the single URL representation and normalization/admission path used for both initial and
redirect URLs and passed unchanged to aiohttp.

Dependencies: Task 1 fixes error codes and result identity.

Acceptance: schemes, host/IP, credentials, default/invalid ports, IDNA/malformed values, fragment
removal, path/query preservation, stable serialization, and redirect resolution match issue #64.

Verification: focused URL/redirect normalization tests with no network.

### Task 3: Implement global-only resolution and exact pinning

Add per-hop direct-IP/resolver admission, all-answer global enforcement, deduplication, custom
resolver pinning, disabled DNS cache, original TLS hostname retention, and unconditional cleanup.

Dependencies: Task 2 supplies the admitted host and normalized request URL.

Acceptance: global-only, mixed-answer rejection, per-hop rebinding defense, exact address set,
single system resolution, SNI/certificate hostname, and closure behavior match issue #64.

Verification: comprehensive injected DNS/address/pinning tests without sockets.

### Checkpoint: Admission boundary

- One URL representation controls validation and connection semantics.
- Every hop is independently admitted and an unsafe answer rejects the full set.
- aiohttp can connect only to the validated addresses while verifying the original hostname.
- No session/connector can escape cleanup.

### Task 4: Implement one-hop GET transport and response admission

Build the exact GET configuration, TLS/proxy/cookie/auth/referrer/retry/automatic-redirect policy,
connect/read limits, status handling, content-type admission, streamed decompressed byte cap, and
charset decoding.

Dependencies: Task 3 provides a validated pinned per-hop connector.

Acceptance: exact headers/options/timeouts; 200-only success; failure bodies unread; exact HTML/
XHTML handling; byte boundary; deterministic decoding; and redacted timeout/TLS/network/content
errors match issue #64.

Verification: controlled fake transport/response tests, including cleanup and cancellation.

### Task 5: Orchestrate the bounded redirect chain and overall deadline

Compose admitted one-hop requests under one 30-second deadline, manually process only permitted
redirect statuses, repeat normalization/resolution/pinning, enforce the five-response/six-request
limit, and build the exact result/chain.

Dependencies: Tasks 2-4 provide normalization, admission, and one-hop behavior.

Acceptance: relative/scheme-relative/cross-origin redirect behavior, per-hop security checks,
limits, no seventh request, requested/final URL identity, complete chain, cleanup, timeout, and
cancellation all match issue #64.

Verification: full focused PRODUCT-008 suite with fake multi-hop scenarios and network denial.

### Checkpoint: Complete runtime contract

- Direct invocation is the only entry point and performs at most one six-request redirect chain.
- Every hop is normalized, resolved, globally admitted, pinned, and cleaned independently.
- Response/status/content/size/charset rules and every error mapping are exact and redacted.
- No retry, real test network, integration, persistence, autonomous call, or deployment exists.

### Task 6: Run full security and repository verification

Run all focused and full checks below. Inspect the dependency tree/diff and changed paths. Confirm
no protected path, migration, tenant boundary, runtime integration, extra dependency, or real
network activity appears. Do not bypass or reclassify any failure.

Dependencies: Tasks 1-5 complete the implementation and tests.

Acceptance: every command passes, only four authorized implementation paths change, migrations
render unchanged, tenant boundaries remain intact, and no external side effect occurred.

Verification: capture command results and changed-file evidence for the draft PR.

### Task 7: Obtain independent security review and deliver unmerged

After deterministic gates pass, obtain a fresh separate read-only, security-focused reviewer pass
against issue #64, concentrating on parser differential, SSRF/DNS rebinding, resolver pinning/TLS
hostname, redirect limits, resource bounds, cleanup/cancellation, redaction, and non-integration.
Fix every blocking finding and rerun affected plus full gates and the review until there are zero
blocking findings.

Dependencies: Task 6 has a fully verified exact-scope implementation.

Acceptance: zero blocking findings; dedicated branch; exact reviewed head pushed; draft PR open;
no unresolved review findings; no auto-merge, human merge, deployment, URL call, or integration.

Verification: record reviewed head and review result, inspect draft status, and leave the PR open
for separate human implementation-merge approval.

## Complete Verification Commands

Run from repository root. `make install` is required after the dependency change so aiohttp and its
resolved install metadata are present in the environment. Tests must deny real DNS/socket traffic.

```bash
make install

.venv/bin/pytest tests/acquisition/test_html.py
.venv/bin/pytest tests/evidence/test_on_page.py tests/evidence/test_diff.py
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pip-audit
make check

.venv/bin/alembic upgrade head --sql > /tmp/product-008-upgrade.sql
.venv/bin/alembic downgrade head:base --sql > /tmp/product-008-downgrade.sql

git diff -- pyproject.toml
git diff --name-only origin/main...HEAD
git diff --check
git status --short
```

`make check` repeats Ruff lint, strict mypy, full pytest, and pip-audit; it does not replace Ruff
format checking, offline migration rendering, dependency/scope inspection, or `git diff --check`.
The `/tmp` SQL files are disposable and must not be committed. Do not call an external URL during
any command, test, example, validation, or review.

## Delivery, Risk, and Rollback

Deliver implementation on a dedicated task branch through a draft PR. The exact reviewed draft
must remain unmerged after all checks and review until a human separately approves its merge. No
approval in issue #64 or this plan authorizes deployment, production traffic, scheduled/autonomous
crawling, robots decisions, tenant integration, or another external action.

Implementation rollback is a revert of the implementation commit followed by reinstalling the
prior dependency set. Because the primitive is unintegrated and never invoked during development,
there is no schema, durable data, production resource, credential, customer, or external-system
state to recover. Planning rollback reverts issue #65's documentation commit, restores PRODUCT-007
as `docs/CURRENT-TASK.md`, and removes this unimplemented plan.

The authoritative implementation assessment is:

```json
{
  "risk": "high",
  "roadmap_authorized": true,
  "reversible": true,
  "production_deployment": false,
  "external_customer_side_effect": false,
  "stop_categories": ["material_security_tradeoffs"]
}
```

The issue #65 planning change itself is low-risk, reversible documentation with no deployment,
external customer side effect, or stop category. Neither assessment merges or deploys anything.
