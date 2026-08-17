# PRODUCT-014: Offline Robots Cache Freshness Policy

## Status: implementation approved after planning merge and reinspection

On 2026-08-17, the user explicitly approved this exact material security-policy contract for implementation under issue #98. The authorization becomes executable only after the planning PR for issue #101 merges and the orchestrator re-inspects `main`. Planning issue #101 does not itself queue implementation; only after that merge and reinspection may the orchestrator apply `codex-ready` to issue #98.

## Objective

Add a deterministic, synchronous, offline policy that decides whether the timestamp of a caller-held robots acquisition cache entry is fresh enough to be consulted. Use one fixed 24-hour TTL, fail closed for missing or expired entries, and never permit stale fallback.

This milestone does not contain or return cached robots content, perform HTTP/DNS/file/database/cache access, read a clock, fetch robots or a target page, bind a site/target, evaluate robots permission, schedule, persist, log, audit, execute, expose API/CLI, run a worker/crawler, or integrate with an active runtime path. Tests use values only.

## Risk and approval boundary

Risk is **high** because cache freshness determines whether a future crawler may reuse a prior robots acquisition outcome. After the planning PR merges and `main` is re-inspected, approval authorizes only the deterministic, synchronous, offline fixed-24-hour policy, values-only tests, verification, and a reviewed draft implementation PR under issue #98's exact contract. It does not authorize implementation merge, stale-on-error reuse, cache storage or reuse, system-clock reads, live retrieval, target fetching, crawling, scheduling, persistence, tenant/site database integration, audit or runtime integration, deployment, production traffic, or any external/customer-facing effect. It does not weaken or broaden issue #98.

The implementation PR must not be auto-merged and must remain open after all gates and a fresh independent time/cache/protocol/security-focused read-only review with zero blocking findings for a separate explicit human merge decision.

## Public contract

Add `src/growth_os/robots/cache.py` and extend `growth_os.robots` exports with exactly:

```python
class RobotsCacheReason(StrEnum):
    MISSING = "missing"
    FRESH = "fresh"
    EXPIRED = "expired"


class RobotsCacheErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"


class RobotsCacheError(ValueError):
    code: RobotsCacheErrorCode


@dataclass(frozen=True, slots=True)
class RobotsCacheDecision:
    reusable: bool
    reason: RobotsCacheReason
    stored_at: datetime | None
    expires_at: datetime | None


def evaluate_robots_cache(
    *,
    stored_at: datetime | None,
    now: datetime,
) -> RobotsCacheDecision: ...
```

The dataclass is immutable/equality-comparable with exactly those fields and order. `RobotsCacheError` exposes only code `INVALID_INPUT` and stable message `Robots cache policy failed: invalid_input`; it never includes timestamps, URLs, cache values, bodies, rules, headers, validators, tenant/site data, or exception text.

## Exact time and input contract

- Accept only exact `datetime.datetime` instances or null where specified; reject subclasses/coercion.
- Require `now` to be an exact timezone-aware UTC datetime whose `tzinfo is datetime.timezone.utc`; reject naive or non-canonical offset/timezone objects even if their offset is zero.
- When present, require `stored_at` under the same exact canonical UTC rule.
- Reject `stored_at > now`; future-dated cache timestamps never become reusable.
- Use exactly `timedelta(hours=24)` as the fixed TTL. Do not accept caller TTL, headers, Cache-Control, Expires, Age, ETag, Last-Modified, validators, grace periods, clock skew, stale windows, or configuration.
- Compute `expires_at = stored_at + timedelta(hours=24)` with standard datetime arithmetic. Overflow raises the stable invalid-input error.
- If `stored_at is None`, return `reusable=False`, reason `MISSING`, and null stored/expires values after validating `now`.
- If `stored_at` is present and `now < expires_at`, return `reusable=True`, reason `FRESH`, and preserve the exact `stored_at` object plus computed expiry.
- At exact equality and for `now > expires_at`, return `reusable=False`, reason `EXPIRED`, preserve exact stored time, and return computed expiry.

## Fail-closed composition boundary

- `reusable=True` means only that a future separately approved caller may consult its own associated cache value; it is not a robots allow decision and does not authorize network access.
- A future caller must still supply the cached acquisition outcome through PRODUCT-013, which enforces exact site/target/provenance binding and PRODUCT-012 permission semantics.
- `MISSING` or `EXPIRED` never permits stale use. A later acquisition failure must remain governed by PRODUCT-012 fail-closed error mapping; this policy never converts failure into cache reuse.
- Do not accept or inspect `FetchedRobots`, `RobotsFetchErrorCode`, `RobotsGateDecision`, `BoundRobotsDecision`, URLs, paths, response values, or caller-selected reasons.

## Determinism and non-action boundary

Use only the standard library. Do not call `datetime.now`, system clocks, sleep, filesystem, database, repositories, services, connectors, HTTP/DNS, acquisition, PRODUCT-009/010/011/012/013 functions, logging, audit, execution, jobs, workers, schedulers, or runtime paths. Add no dependency, migration, schema, route, CLI, storage, cache backend, validator logic, crawler, or active integration.

Future separately approved milestones must still define cache storage and atomicity, cache keys and tenant/site ownership, acquisition/update ordering, validator semantics if any, audit linkage, idempotency, rate/concurrency, scheduling, target-page acquisition ordering, durable execution, and fail-closed operational behavior.

## Acceptance tests

1. Exact public enums/types/fields/exports/signature/immutability/equality and stable redacted errors.
2. Strict exact datetime/null type rejection, including subclasses, naive values, and non-canonical zero-offset timezone objects.
3. Missing entry behavior after `now` validation.
4. Fixed 24-hour computation immediately after storage, one microsecond before expiry, exact expiry, and after expiry.
5. Future-dated and overflow inputs fail with the stable error.
6. Exact `stored_at` identity is preserved and expiry uses standard UTC datetime arithmetic.
7. Repeated calls are deterministic and inputs remain unchanged; no clock or configurable TTL is consulted.
8. Static/runtime isolation proves no acquisition, robots gate/binding, network/DNS/file/database/cache/connector/audit/execution/logging/active-path call.
9. No dependency, migration, persistence, API, CLI, scheduler, validator, cache backend, crawler, or runtime integration.
10. PRODUCT-008 through PRODUCT-013, acquisition, robots, and evidence regressions remain unchanged and pass.

Run focused cache/robots/acquisition/evidence tests, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate time/cache/protocol/security-focused read-only reviewer pass with zero blocking findings.

## Delivery and rollback

After the planning PR merges and the orchestrator re-inspects `main`, deliver implementation on a dedicated branch through a reviewed draft PR and stop for a separate explicit human merge decision. Do not auto-merge, deploy, or perform any live request.

Rollback removes the cache policy API/tests. No dependency, schema, durable data, production resource, credential, or external state requires recovery.

## Embedded PRODUCT-014 high-risk assessment

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

## Planning authorization boundary

Planning issue #101 is documentation only and does not itself queue implementation. It records the user's 2026-08-17 approval, which becomes executable only after this planning PR merges and the orchestrator re-inspects `main`; only then may the orchestrator apply `codex-ready` to #98. It does not authorize implementation merge, stale-on-error reuse, cache storage or reuse, system-clock reads, live retrieval, target-page fetching, crawling, scheduling, persistence, tenant/site database integration, audit or runtime integration, deployment, production traffic, or external/customer-facing activity. The values-only, offline, no-clock, no-storage, no-live-network boundary and every future-integration gate remain mandatory.

Validate documentation format, links, commands, paths, exact two-file scope, full repository gates, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate read-only time/cache/protocol/security review with zero blocking findings. Deliver through a dedicated branch and draft PR.

## Auto-merge assessment

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
