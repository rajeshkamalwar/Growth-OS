# PRODUCT-010: Offline Robots Access-Outcome Policy

## Status and Authority

**Implementation explicitly approved 2026-08-17 — executable after this planning PR merges and
the orchestrator re-inspects `main`; separate human implementation-merge approval required.**

This plan preserves the exact runtime contract from
[GitHub issue #74](https://github.com/rajeshkamalwar/Growth-OS/issues/74). The user explicitly
approved implementation under that contract on 2026-08-17. The approval becomes executable only
after planning issue #77's PR merges and the orchestrator re-inspects `main`.

This planning task does not itself queue implementation. Only after the merge and reinspection
may the orchestrator apply `codex-ready` to issue #74. The approval authorizes only the
deterministic offline access-outcome interpreter, its tests and verification, and a reviewed draft
implementation PR. It does not authorize merging that PR, robots.txt retrieval, HTTP/DNS,
caching, redirects, integration with PRODUCT-008, crawling, scheduling, deployment, production
traffic, external/customer-facing activity, or weakening or broadening issue #74.

## Objective

Add a deterministic, offline interpreter that combines a caller-supplied robots retrieval outcome with PRODUCT-009's evaluator and returns one fail-closed access decision for a caller-supplied target path.

This is the next dependency before robots HTTP acquisition or crawler integration. It performs no HTTP, DNS, file access, caching, scheduling, persistence, logging, audit, or active enforcement and is not imported by any runtime path.

The policy is grounded in [RFC 9309 sections 2.3.1 and 2.4](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1): successful retrieval follows parseable rules; 4xx is unavailable; 5xx/network failure is unreachable and complete-disallow; caching remains outside this milestone.

## Risk and approval boundary

Risk is **high** because status/error semantics determine whether future autonomous network access
is permitted. Approval authorizes implementation, tests, verification, and a reviewed draft PR
only. After all gates pass, including a fresh independent protocol/security-focused read-only
review with zero blocking findings, the implementation PR must not be auto-merged and must remain
open for a separate explicit human merge decision. Approval does not authorize merging the
implementation, robots.txt retrieval, HTTP/DNS, caching, redirects, integrating with PRODUCT-008,
crawling, scheduling, deployment, production traffic, any external/customer-facing effect, or
weakening or broadening issue #74's contract.

## Public contract

Create `src/growth_os/robots/access.py` and extend package exports with exactly:

```python
class RobotsAccessReason(StrEnum):
    POLICY = "policy"
    UNAVAILABLE = "unavailable"
    UNREACHABLE = "unreachable"
    INDETERMINATE = "indeterminate"
    INVALID_POLICY = "invalid_policy"


@dataclass(frozen=True, slots=True)
class RobotsAccessDecision:
    allowed: bool
    reason: RobotsAccessReason
    status_code: int | None
    policy_decision: RobotsDecision | None
    policy_error_code: RobotsPolicyErrorCode | None


def evaluate_robots_access(
    *,
    status_code: int | None,
    robots_txt: bytes | None,
    target_path: str,
) -> RobotsAccessDecision: ...
```

The dataclass is immutable/equality-comparable with exactly those fields and order. Reuse PRODUCT-009's public values and evaluator; add no second parser or matcher. Errors remain stable/redacted and never include content, paths, rules, response details, or parser internals.

## Input and validation contract

- Accept exact `int | None` for `status_code`, exact `bytes | None` for `robots_txt`, and exact `str` for `target_path`; reject booleans, subclasses, and coercion.
- Integer status codes must be from 100 through 599.
- A body is required only for status 200 and forbidden for every other status and for `None`.
- Validate `target_path` under PRODUCT-009 for every outcome before returning a decision. Invalid target or argument combinations raise `RobotsPolicyError(INVALID_INPUT)`.
- Do not accept URLs, headers, redirect histories, exceptions, cache entries, timestamps, tenant identifiers, or caller-selected fallback behavior.

## Outcome policy

Return exactly:

1. **200 OK**: call `evaluate_robots` with the supplied bytes and target path.
   - A valid policy returns `allowed` copied from the nested decision, reason `POLICY`, status 200, that exact nested `policy_decision`, and null `policy_error_code`.
   - `TOO_LARGE` or `INVALID_ENCODING` from PRODUCT-009 fails closed: return disallowed `INVALID_POLICY`, status 200, null nested decision, and the exact error code.
   - `INVALID_INPUT` remains a raised input error and is never converted into a decision.
2. **400-499**: RFC-unavailable; return allowed `UNAVAILABLE`, preserve the status, and use null nested/error fields.
3. **500-599 or `None`**: RFC-unreachable/network failure; return disallowed `UNREACHABLE`, preserve the status or null, and use null nested/error fields.
4. **100-199, 201-399**: no complete 200 representation is available to this offline boundary; return disallowed `INDETERMINATE`, preserve the status, and use null nested/error fields.

In particular, 204/206, all redirects including 304, and redirect exhaustion do not imply an empty or unavailable policy. They remain fail-closed `INDETERMINATE`. A future fetcher must follow its separately approved redirect contract before calling this function.

Do not consult or infer a cached policy. A future separately approved integration may define RFC caching, validators, expiry, and long-term unreachable behavior.

## Architecture and non-action boundary

- Python standard library plus PRODUCT-009 only; add no dependency.
- Keep independent of aiohttp, acquisition, evidence, FastAPI, SQLAlchemy/Alembic, tenant context, services, repositories, connectors, execution, jobs, and workers.
- Do not modify PRODUCT-008 or PRODUCT-009 behavior.
- Do not add HTTP/DNS, URL construction, redirects, cache logic, persistence, route, CLI, audit event, active integration, or production behavior.
- Do not log inputs or decisions.
- Future separately approved acquisition/integration must define initial authority, `/robots.txt` URL construction, per-hop SSRF and redirect controls, content-type handling, cache/expiry/validators, rate/concurrency, tenant/site ownership, audit linkage, idempotency, and fail-closed operational behavior.

## Acceptance tests

Add focused tests proving:

1. exact public types, fields, exports, immutability, strict types, stable redacted input errors, status bounds, and body/status invariants;
2. 200 allowed/disallowed/no-group/no-rule/robots-URI decisions preserve the exact nested PRODUCT-009 decision;
3. 200 oversized and invalid-UTF-8 bodies become disallowed `INVALID_POLICY` with exact error provenance, while invalid target input still raises;
4. every 4xx is allowed `UNAVAILABLE`; representative 5xx and `None` are disallowed `UNREACHABLE`;
5. representative 1xx, 201/204/206, 3xx/304, and redirect-exhaustion-shaped terminal input are disallowed `INDETERMINATE`;
6. all non-policy outcomes have null nested/error fields as specified, no cache or fallback is inferred, and repeated calls are deterministic;
7. static and dynamic isolation proves no network, DNS, HTTP, filesystem, database, connector, audit, execution, logging, or active-runtime call;
8. no dependency, migration, route, persistence, acquisition/evidence modification, or runtime integration.

Run PRODUCT-009 and PRODUCT-010 focused tests, acquisition/evidence regressions, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate protocol/security-focused read-only reviewer pass with zero blocking findings.

## Delivery and rollback

After this planning PR merges and the orchestrator re-inspects `main`, deliver implementation on a
dedicated branch through a reviewed draft PR and stop for a separate human merge decision because
this is a material security policy. Do not auto-merge or deploy. Rollback is reverting the
implementation commit; no dependency, schema, durable data, production resource, or external
state requires recovery.

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
## Planning Delivery and Rollback

Planning issue #77 changes exactly `docs/CURRENT-TASK.md` and this plan. It records the user's
explicit implementation approval but does not itself queue implementation. Only after this
planning PR merges and the orchestrator re-inspects `main` may the orchestrator apply
`codex-ready` to issue #74. Neither this planning issue nor its merge authorizes implementation
merge, robots.txt retrieval, HTTP/DNS, caching, redirects, crawling, integration with PRODUCT-008,
scheduling, deployment, production traffic, external/customer-facing activity, or weakening or
broadening issue #74.

Validate documentation format, links, commands, paths, final two-file scope, full repository
local gates, offline migration rendering, and `git diff --check`. Obtain a fresh independent
protocol/security-focused read-only review with zero blocking findings, then deliver the planning
change through a dedicated branch and draft PR.

Planning rollback restores the proposal-only approval gate for PRODUCT-010. No runtime,
dependency, schema, data, production resource, or external state requires recovery.

The planning issue #77 assessment is:

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

The planning assessment authorizes only the reversible documentation change. The user's recorded
approval separately authorizes PRODUCT-010 implementation only after this planning PR merges and
the orchestrator re-inspects `main`; neither authorization permits any external action or merging
the implementation PR.
