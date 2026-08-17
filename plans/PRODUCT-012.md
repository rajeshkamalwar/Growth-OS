# PRODUCT-012: Offline Robots Acquisition Outcome Gate

## Status: Proposed — approval required; not authorized for implementation

This plan preserves the complete proposed contract from
[GitHub issue #86](https://github.com/rajeshkamalwar/Growth-OS/issues/86).

Do not apply `codex-ready` to issue #86 or implement this proposal until the user explicitly
approves this exact offline gate after this planning proposal is merged.

Neither planning issue #87 nor its merge authorizes `codex-ready` on issue #86, implementation,
implementation merge, live retrieval, crawling, caching, scheduling, persistence, integration,
deployment, or any external activity.

## Security status: explicit security approval required

This issue is a proposed material security-policy contract. Do not apply `codex-ready` or
implement it until the user explicitly approves this exact offline gate after its planning
proposal is merged.

## Objective

Add a deterministic, synchronous, offline adapter that combines either one caller-supplied PRODUCT-011 `FetchedRobots` value or one caller-supplied `RobotsFetchErrorCode` with a caller-supplied target path. It must compose PRODUCT-010 for valid terminal retrieval outcomes, classify transport-unreachable errors, fail closed on every other acquisition rejection, and preserve exact provenance.

This milestone performs no HTTP, DNS, file access, URL construction, redirects, caching, scheduling, persistence, logging, audit, active enforcement, or runtime integration. It does not fetch robots.txt or a target page and is not a crawler. Tests must use values/fakes only and must never contact a real website.

## Risk and approval boundary

Risk is **high** because the mapping determines whether a future crawler could proceed after a robots acquisition outcome or failure. Approval would authorize implementation, tests, verification, and a reviewed draft PR only. It would not authorize implementation merge, live retrieval, target-page fetching, crawling, caching, scheduling, persistence, tenant/site binding, audit, deployment, production traffic, or any external/customer-facing effect.

## Public contract

Add `src/growth_os/robots/gate.py` and extend `growth_os.robots` exports with exactly:

```python
class RobotsGateReason(StrEnum):
    ACCESS = "access"
    FETCH_UNREACHABLE = "fetch_unreachable"
    FETCH_REJECTED = "fetch_rejected"


class RobotsGateErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"


class RobotsGateError(ValueError):
    code: RobotsGateErrorCode


@dataclass(frozen=True, slots=True)
class RobotsGateDecision:
    allowed: bool
    reason: RobotsGateReason
    fetched_robots: FetchedRobots | None
    access_decision: RobotsAccessDecision | None
    fetch_error_code: RobotsFetchErrorCode | None


def evaluate_robots_gate(
    *,
    fetched_robots: FetchedRobots | None,
    fetch_error_code: RobotsFetchErrorCode | None,
    target_path: str,
) -> RobotsGateDecision: ...
```

The dataclass is immutable/equality-comparable with exactly those fields and order. `RobotsGateError` exposes only code `INVALID_INPUT` and stable message `Robots gate failed: invalid_input`; it never includes URLs, paths, response values, bodies, headers, rules, redirect targets, network details, or exception text.

## Strict input and provenance invariants

- Require exactly one of `fetched_robots` and `fetch_error_code`; both null or both non-null raise `RobotsGateError(INVALID_INPUT)`.
- When present, require an exact `FetchedRobots` instance and no duck typing/coercion. When present, require an exact `RobotsFetchErrorCode` member.
- Require exact strings for `requested_site_url`, `robots_url`, and `final_url`; each must be nonempty.
- Require `redirect_chain` to be an exact nonempty tuple of exact nonempty strings, with `robots_url == redirect_chain[0]` and `final_url == redirect_chain[-1]`.
- Require an exact non-boolean integer status from 100 through 599.
- For status 200 require `content_type == "text/plain"` and an exact bytes body. For every non-200 require null `content_type` and null `body`.
- Reject every malformed or internally inconsistent caller-constructed `FetchedRobots` with the stable gate invalid-input error before returning a decision.
- Validate `target_path` through PRODUCT-010 on every otherwise valid outcome, including fetch-error outcomes. Preserve PRODUCT-010's exact target-path error behavior; do not weaken, normalize, coerce, or reinterpret it.
- Do not accept exceptions, URLs as target paths, response/session objects, timestamps, cache values, tenant/site IDs, fallback flags, caller-selected reasons, or arbitrary strings in place of enums.

## Exact outcome mapping

### Valid fetched terminal outcome

Call `evaluate_robots_access` exactly once with the fetched status, body, and target path.

Return reason `ACCESS`; copy `allowed` from the exact nested `RobotsAccessDecision`; retain the exact same `FetchedRobots` and nested access-decision objects; set `fetch_error_code` null. Do not reinterpret any 200, 4xx, 5xx, `INDETERMINATE`, `INVALID_POLICY`, or nested policy result.

### Transport-unreachable acquisition error

The exact codes `DNS_FAILURE`, `TIMEOUT`, `TLS_FAILURE`, and `NETWORK_FAILURE` map through PRODUCT-010's network-failure input: call `evaluate_robots_access(status_code=None, robots_txt=None, target_path=target_path)` exactly once.

Return disallowed reason `FETCH_UNREACHABLE`, null fetched result, that exact nested `UNREACHABLE` access decision, and the exact fetch error code. The nested decision must have null status, policy decision, and policy error.

### Rejected acquisition error

The exact codes `INVALID_URL`, `DISALLOWED_PORT`, `DISALLOWED_ADDRESS`, `TOO_MANY_REDIRECTS`, `INVALID_REDIRECT`, `UNSUPPORTED_CONTENT_TYPE`, `BODY_TOO_LARGE`, and `UNSUPPORTED_CHARSET` are acquisition rejections without a complete terminal result.

Validate the target path once through PRODUCT-010's null-status path, discard that temporary decision, and return disallowed reason `FETCH_REJECTED`, null fetched result, null access decision, and the exact fetch error code. Do not manufacture a status/body, infer an empty policy, treat a protocol rejection as 4xx-unavailable, or permit access.

## Determinism and non-action boundary

- Use only standard-library code plus the existing PRODUCT-010 and PRODUCT-011 public values/functions; add no dependency.
- Do not catch or rewrite valid PRODUCT-009/010 policy input errors for `target_path`.
- Do not mutate inputs, instantiate replacement fetched results, copy bodies, decode content, parse URLs, or inspect redirect authorities.
- Do not call `fetch_robots`, `fetch_html`, DNS, aiohttp request/session/connector methods, filesystem, database, repositories, services, execution, logging, audit, API, jobs, or workers.
- Do not import the gate from `growth_os.main`, APIs, services, repositories, models, execution, jobs, workers, or any active runtime path.
- Do not add cache/expiry/validators, persistence, routes, CLI, scheduler, crawler, retries, rate/concurrency controls, target-page acquisition, or active authorization.
- Future separately approved milestones must still define cache/expiry/validators, tenant/site ownership, target-URL-to-site binding, audit linkage, idempotency, rate/concurrency, scheduling, and fail-closed operational orchestration before any crawler or active runtime use.

## Acceptance tests

Add focused tests proving:

1. exact public enums/types/fields/exports/signature/immutability and stable redacted gate errors;
2. strict one-of/type/provenance/status/content/body invariants reject every malformed caller-constructed input before a decision;
3. representative PRODUCT-010 fetched outcomes preserve the exact fetched object, exact nested decision identity/value, exact allowed bit, and reason `ACCESS`;
4. all four unreachable error codes map exactly once through PRODUCT-010 null status and retain exact error provenance;
5. every remaining PRODUCT-011 error code fails closed as `FETCH_REJECTED`, has no nested access decision, and never manufactures status/body or invokes network;
6. invalid target paths raise the unchanged PRODUCT-010/009 input error for fetched, unreachable, and rejected paths;
7. repeated calls are deterministic, inputs remain unchanged, and no cache/fallback is inferred;
8. static/runtime isolation proves no HTTP/DNS/file/database/connector/audit/execution/logging/active-path or real-network call;
9. no dependency, migration, persistence, API, CLI, scheduler, cache, crawler, target fetch, or runtime integration;
10. PRODUCT-009, PRODUCT-010, PRODUCT-011, and PRODUCT-008 focused regressions remain unchanged and pass.

Run all robots and acquisition tests, evidence regressions, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate protocol/security-focused read-only reviewer pass with zero blocking findings.

## Delivery and rollback

After explicit approval, deliver implementation on a dedicated branch through a reviewed draft PR and stop for a separate explicit human merge decision because this defines material crawler-permission semantics. Do not deploy or perform any live request.

Rollback is reverting the implementation commit and removing the gate API/tests. No dependency, schema, durable data, production resource, credential, or external state requires recovery.

## Embedded PRODUCT-012 high-risk assessment

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

Planning issue #87 changes exactly `docs/CURRENT-TASK.md` and this plan. It records PRODUCT-011 as
merged and PRODUCT-012 as proposed, but it does not itself queue or implement PRODUCT-012 and does
not authorize `codex-ready` on issue #86, implementation merge, or any external activity.

Validate documentation/link/command/path hygiene, all repository local gates, offline migration
rendering, `git diff --check`, and exact two-file scope. Obtain a fresh separate read-only
protocol/security review with zero blocking findings, then deliver the planning change on a
dedicated branch through a draft PR.

Planning rollback restores PRODUCT-011 as current and removes this PRODUCT-012 proposal. No
runtime, dependency, schema, data, production, or external recovery is needed.

The planning issue #87 assessment is:

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
