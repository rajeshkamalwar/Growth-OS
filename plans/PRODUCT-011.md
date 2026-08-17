# PRODUCT-011: Fail-Closed Robots.txt Acquisition

## Status: Proposed — approval required; not authorized for implementation

This plan preserves the complete proposed contract from
[GitHub issue #80](https://github.com/rajeshkamalwar/Growth-OS/issues/80).

Neither planning issue #81 nor its merge authorizes `codex-ready` on issue #80, implementation,
implementation merge, live retrieval, permission evaluation, crawling, caching, scheduling,
integration, deployment, or any external activity.

## Status: explicit security approval required

This issue is a proposed outbound-network security contract. Do not apply `codex-ready` or implement it until the user explicitly approves the robots.txt acquisition boundary after its planning proposal is merged.

## Objective

Add an explicitly invoked, asynchronous, fail-closed robots.txt acquisition primitive for a caller-supplied public HTTP(S) site URL. Derive the initial authority's root `/robots.txt` URL, fetch through the same SSRF-resistant per-hop transport guarantees as PRODUCT-008, and return a bounded terminal status/body value that can later be supplied to PRODUCT-010.

This milestone remains unintegrated. It does not evaluate permission, fetch a target page, crawl, cache, schedule, persist, audit, expose an API/CLI, or run from an active application path. Tests must use controlled fakes only and must never contact a real website.

## Risk and approval boundary

Risk is **high** because this adds outbound network behavior and may refactor the shared SSRF/TLS transport boundary. Approval authorizes implementation, tests, verification, and a reviewed draft PR only. It does not authorize merging the implementation, live retrieval, PRODUCT-010 composition, target-page fetching, crawling, caching, scheduling, deployment, production traffic, or any external/customer-facing effect.

## Public contract

Add `src/growth_os/acquisition/robots.py` and extend `growth_os.acquisition` exports with exactly:

```python
class RobotsFetchErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    DISALLOWED_PORT = "disallowed_port"
    DNS_FAILURE = "dns_failure"
    DISALLOWED_ADDRESS = "disallowed_address"
    TIMEOUT = "timeout"
    TLS_FAILURE = "tls_failure"
    NETWORK_FAILURE = "network_failure"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    INVALID_REDIRECT = "invalid_redirect"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    BODY_TOO_LARGE = "body_too_large"
    UNSUPPORTED_CHARSET = "unsupported_charset"


class RobotsFetchError(RuntimeError):
    code: RobotsFetchErrorCode


@dataclass(frozen=True, slots=True)
class FetchedRobots:
    requested_site_url: str
    robots_url: str
    final_url: str
    status_code: int
    content_type: str | None
    body: bytes | None
    redirect_chain: tuple[str, ...]


async def fetch_robots(*, site_url: str) -> FetchedRobots: ...
```

The dataclass is immutable/equality-comparable with exactly those fields and order. Errors expose only a stable code/message `Robots fetch failed: <code>` and never URLs, authorities, IPs, headers, bodies, DNS/TLS/socket details, redirect targets, or exception text. A non-string `site_url` raises exactly `TypeError("site_url must be a string")`.

## Initial URL contract

- Apply PRODUCT-008's exact absolute HTTP(S), hostname/IP, userinfo, IDNA, malformed-authority, and default-port-only validation to `site_url`.
- Remove fragment, path, parameters, and query only after validating the complete supplied URL representation.
- Construct exactly the normalized initial origin plus lowercase root path `/robots.txt`, with no query or fragment.
- `requested_site_url` is the fully normalized supplied site URL with its original normalized path/query and no fragment.
- `robots_url` is the derived initial `/robots.txt` URL. Redirects never change the authority context represented by this field.
- Do not accept FTP, file, schemes other than HTTP(S), relative/scheme-relative initial URLs, non-default ports, userinfo, malformed hosts, or caller-supplied headers/options.

## Shared transport and SSRF contract

Use one internal implementation for the security-critical URL normalization, address admission, DNS resolution, resolver pinning, TLS hostname preservation, and per-hop connector/session behavior shared with PRODUCT-008. Do not copy a second independently drifting SSRF implementation.

A behavior-preserving extraction/refactor of PRODUCT-008 internals is authorized only as needed for reuse. Preserve every existing `fetch_html` public type, export, signature, normalization, request, redirect, timeout, decoding, error, cleanup, cancellation, and test behavior exactly.

For the initial robots request and every redirect hop:

- synchronously normalize before I/O;
- resolve immediately before the request;
- require every answer to be a global public IPv4/IPv6 address and reject mixed public/private, unsupported, malformed, scoped, mapped-private, empty, or changed/unvalidated answer data;
- pin exactly the admitted answer set in a fresh per-hop resolver/connector while retaining the original hostname for Host/SNI/TLS verification;
- permit only HTTP(S) and scheme-default ports;
- close the response, session, connector, and resolver on success, error, timeout, redirect, and cancellation.

No environment proxy, netrc, cookies, auth, referrer, automatic redirects, DNS cache, retry, caller SSL override, caller headers, or caller connector is permitted. Use platform TLS verification defaults.

## Request, redirect, and timeout contract

Each hop is one GET with exactly:

```text
User-Agent: GrowthOSBot/0.1
Accept: text/plain
Accept-Encoding: identity
```

Use the PRODUCT-008 timeout budgets: 5-second connect/socket-connect, 10-second socket-read, and one 30-second whole-chain deadline. Cancellation propagates unchanged.

Follow only 301, 302, 303, 307, and 308 responses with exactly one nonblank Location. Resolve relative redirects against the current URL; cross-authority redirects are allowed only after the identical validation/resolution/pinning checks. Follow at most five redirect responses. A sixth redirect response raises `TOO_MANY_REDIRECTS`. Invalid/missing/duplicate Location raises `INVALID_REDIRECT`.

The redirect chain contains the normalized URL requested at each hop, including the initial robots URL and final terminal URL, but never an unrequested next target.

## Terminal response contract

For every terminal response other than status 200:

- return `FetchedRobots` with the exact status;
- set `content_type` and `body` to null;
- do not iterate/read the response body;
- do not reinterpret status semantics—PRODUCT-010 owns that offline policy.

For status 200:

- require exactly one Content-Type header whose media type is `text/plain` case-insensitively;
- permit no charset parameter or exactly one nonempty charset whose ASCII-case-insensitive value is `utf-8`; reject duplicates, empty values, or any other charset with `UNSUPPORTED_CHARSET`;
- reject a missing/duplicate/malformed/non-text Content-Type with `UNSUPPORTED_CONTENT_TYPE`;
- read the auto-decompressed body in 64 KiB chunks, accepting exactly 512,000 bytes and raising `BODY_TOO_LARGE` before retaining byte 512,001;
- return raw bytes without decoding, truncating, BOM removal, newline changes, or content interpretation.

Do not classify a terminal status as allowed/disallowed, manufacture a body, use a cached policy, or call PRODUCT-009/010.

## Error mapping

Map normalization, port, DNS, address, timeout, TLS, network, redirect, content-type, charset, and size failures to the exact redacted `RobotsFetchErrorCode`. Preserve `asyncio.CancelledError` unchanged. Do not expose HTTP status as an error because all terminal statuses are returned.

## Architecture and non-action boundary

- Reuse the existing aiohttp/yarl dependency set; add no dependency.
- Keep acquisition independent of evidence, robots policy/access packages, FastAPI, database/SQLAlchemy/Alembic, tenant context, services, repositories, connectors, execution, jobs, and workers.
- Do not import the new primitive from `growth_os.main`, APIs, services, repositories, models, execution, jobs, or any active runtime path.
- Do not log request/response details or results.
- Do not add caching, conditional requests, persistence, routes, CLI, scheduler, worker, crawler, target-page orchestration, permission evaluation, audit events, metrics, retries, rate/concurrency controls, or production behavior.
- A future separately approved integration must define error-to-PRODUCT-010 mapping, cache/expiry/validators, tenant/site ownership, audit linkage, idempotency, rate/concurrency, scheduling, target-page authorization, and fail-closed operational behavior.

## Acceptance tests

Use controlled fakes/monkeypatched resolution only; deny real DNS/network. Prove:

1. exact public types/fields/exports/signature/immutability, strict type behavior, stable redacted errors, and no new dependency;
2. initial site normalization and exact root robots URL derivation across path/query/fragment, case, IDNA, IP literals, explicit default ports, and rejection of every invalid URL/authority/port form covered by PRODUCT-008;
3. all per-hop DNS/address admission, mixed-answer rejection, rebinding resistance, resolver pinning, Host/SNI retention, session/connector settings, headers, TLS defaults, and no proxy/cookies/auth/referrer/automatic redirect/cache/retry/overrides;
4. relative, absolute, cross-authority, malformed, missing, duplicate, and six-redirect behavior with revalidation before each request and exact redirect-chain provenance;
5. timeout/error mapping, cancellation propagation, and response/session/connector cleanup on every path;
6. every representative non-200 status returns without body iteration and with null content fields;
7. 200 Content-Type/charset matrix, raw-byte preservation, auto-decompression configuration, chunking, and exact 512,000/512,001-byte boundary;
8. PRODUCT-008's entire focused suite remains unchanged and passes, with explicit regression assertions for its public API and request semantics;
9. static/runtime isolation proves no evidence/policy/access, database, connector, audit, execution, logging, active-path, or real-network call;
10. no migration, persistence, API, CLI, scheduler, cache, crawler, PRODUCT-009/010 composition, or runtime integration.

Run PRODUCT-008 acquisition regressions, PRODUCT-009/010 tests, all evidence tests, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate SSRF/protocol/security-focused read-only reviewer pass with zero blocking findings.

## Delivery and rollback

After explicit approval, deliver implementation on a dedicated branch through a reviewed draft PR and stop for a separate human merge decision because this changes the outbound-network security boundary. Do not deploy or perform a live request.

Rollback is reverting the implementation commit, restoring PRODUCT-008 internals if refactored, and removing the robots acquisition API/tests. No dependency, schema, durable data, production resource, credential, or external state requires recovery.

## Auto-merge assessment

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

## Planning delivery and rollback

Planning issue #81 changes exactly `docs/CURRENT-TASK.md` and this plan. It records PRODUCT-010
as merged and PRODUCT-011 as a proposal requiring explicit approval; it does not authorize any
implementation or external action.

Validate documentation/link/command/path hygiene, all repository local gates, offline migration
rendering, `git diff --check`, and exact two-file scope. Obtain a fresh separate read-only
SSRF/protocol/security review with zero blocking findings, then deliver the planning change on a
dedicated branch through a draft PR.

Planning rollback restores PRODUCT-010 as current and removes this PRODUCT-011 proposal. No
runtime, dependency, schema, data, production, or external recovery is needed.

The planning issue #81 assessment is:

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
