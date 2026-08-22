# PRODUCT-015: Cached Robots Outcome Selector

## Status: approved — executable only after planning merge and `main` reinspection

On 2026-08-17, the user explicitly approved implementation of this exact material security-policy composition contract. The approval becomes executable only after the planning PR for issue #107 merges and the orchestrator re-inspects `main`. Planning issue #107 does not itself queue implementation; only after that merge and reinspection may the orchestrator apply `codex-ready` to issue #104.

## Objective

Add a deterministic, synchronous, offline selector that couples one caller-held PRODUCT-011 `FetchedRobots` value to its canonical UTC storage timestamp, delegates freshness exactly once to PRODUCT-014, returns the exact fetched object only while fresh, and drops it completely when missing or expired.

This milestone performs no clock read, cache/backend/file/database access, HTTP/DNS, robots or target fetch, URL parsing, site/target binding, robots permission evaluation, persistence, scheduling, logging, audit, API/CLI, worker, crawler, or runtime integration. Tests use values only.

## Risk and approval boundary

Risk is **high** because selecting a cached robots acquisition outcome can affect future crawl authorization. After the planning merge and `main` reinspection, approval authorizes only the deterministic, synchronous, offline cached-outcome selector, its values-only tests, verification, and a reviewed draft implementation PR under issue #104's exact contract. The implementation PR must not be auto-merged and must remain open after all gates and a fresh independent cache/time/protocol/security-focused read-only review with zero blocking findings for a separate explicit human merge decision. Approval does not authorize implementation merge, cache storage or retrieval, stale-on-error reuse, clock access, live retrieval, site/target binding, robots permission evaluation, crawling, scheduling, persistence, tenant/site database integration, audit or runtime integration, deployment, production traffic, or any external/customer-facing activity. It does not authorize weakening or broadening issue #104.

## Public contract

Add `src/growth_os/robots/cache_selection.py` and extend `growth_os.robots` exports with exactly:

```python
@dataclass(frozen=True, slots=True)
class CachedRobotsOutcome:
    stored_at: datetime
    fetched_robots: FetchedRobots


class RobotsCacheSelectionReason(StrEnum):
    FRESH = "fresh"
    REFRESH_REQUIRED = "refresh_required"


class RobotsCacheSelectionErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"


class RobotsCacheSelectionError(ValueError):
    code: RobotsCacheSelectionErrorCode


@dataclass(frozen=True, slots=True)
class RobotsCacheSelectionDecision:
    reusable: bool
    reason: RobotsCacheSelectionReason
    cache_decision: RobotsCacheDecision
    fetched_robots: FetchedRobots | None


def select_cached_robots(
    *,
    cached_outcome: CachedRobotsOutcome | None,
    now: datetime,
) -> RobotsCacheSelectionDecision: ...
```

Both dataclasses are immutable/equality-comparable with exactly those fields and order. Selector errors expose only stable message `Robots cache selection failed: invalid_input` and never include timestamps, URLs, bodies, rules, headers, redirect data, cache data, tenant/site data, or exception text.

## Exact input and composition contract

- Accept only null or an exact `CachedRobotsOutcome`; reject subclasses and duck types with selector `INVALID_INPUT` before calling PRODUCT-014.
- For a present outcome, require `type(cached_outcome.stored_at) is datetime` and `type(cached_outcome.fetched_robots) is FetchedRobots`; reject subclasses/coercion before PRODUCT-014. PRODUCT-014 remains authoritative for canonical UTC, future timestamp, and overflow validation.
- Pass `stored_at=None` for a missing outcome, otherwise pass the exact stored timestamp, and pass the exact caller-supplied `now` to `evaluate_robots_cache` exactly once. Do not catch, wrap, or rewrite PRODUCT-014 errors.
- Preserve the exact returned `RobotsCacheDecision` object in every result.
- If PRODUCT-014 returns `FRESH`, return `reusable=True`, reason `FRESH`, and the exact same `FetchedRobots` object by identity.
- If PRODUCT-014 returns `MISSING` or `EXPIRED`, return `reusable=False`, reason `REFRESH_REQUIRED`, and null `fetched_robots`; never expose or return an expired object from the decision.
- Reject any impossible or caller-forged PRODUCT-014 result shape with selector `INVALID_INPUT`: exact decision type only; `FRESH` must be reusable with non-null stored/expires values, while `MISSING` and `EXPIRED` must be non-reusable with their contract-consistent nullability.
- Do not validate, copy, decode, mutate, or reinterpret the `FetchedRobots` fields. A future separately approved caller must pass a selected fresh object through PRODUCT-013, which validates exact site/target/provenance and PRODUCT-012 semantics before any permission decision.

## Fail-closed and non-action boundary

- `reusable=True` means only that the exact cached acquisition object may be supplied to PRODUCT-013; it is not an allow decision and does not authorize any network request.
- Missing and expired outcomes always require refresh and provide no fetched object. An acquisition error must remain governed by PRODUCT-012; no stale fallback exists.
- Use only the standard library plus PRODUCT-011 and PRODUCT-014 public types/function. Do not import or call PRODUCT-009/010/012/013, acquisition functions, shared URL transport, clocks, filesystem, cache backend, database, repositories, services, connectors, logging, audit, execution, jobs, workers, schedulers, or runtime paths.
- Add no dependency, migration, schema, route, CLI, storage, validator logic, cache backend, crawler, or active integration.

Future separately approved milestones must still define cache storage/atomicity and keys, tenant/site ownership, acquisition/update ordering, validator semantics if any, audit linkage, idempotency, rate/concurrency, scheduling, target-page acquisition ordering, durable execution, and fail-closed operational behavior.

## Acceptance tests

1. Exact public types, fields, exports, signatures, immutability/equality, and stable redacted selector errors.
2. Null/exact-type validation ordering, rejecting dataclass/datetime/fetched subclasses and duck types before PRODUCT-014.
3. PRODUCT-014 called exactly once with exact timestamp/now identity for missing, fresh, and expired cases; its errors propagate unchanged.
4. Fresh selection preserves exact cache-decision and fetched-object identity.
5. Missing/expired selection returns refresh-required, false, and no fetched object, including exact expiry boundary.
6. Forged/inconsistent PRODUCT-014 decision shapes fail closed with selector invalid-input.
7. Repeated calls deterministic; inputs unchanged; no clock, storage, stale fallback, copying, or mutation.
8. Static/runtime isolation proves no PRODUCT-009/010/012/013, acquisition, transport, network/DNS/file/database/cache/connector/audit/execution/logging/active-path call.
9. No dependency, migration, persistence, API, CLI, scheduler, validator, backend, crawler, or runtime integration.
10. PRODUCT-008 through PRODUCT-014, acquisition, robots, and evidence regressions remain unchanged and pass.

Run focused cache-selection/robots/acquisition/evidence tests, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate cache/time/protocol/security-focused read-only reviewer pass with zero blocking findings.

## Delivery and rollback

After the planning PR for issue #107 merges and the orchestrator re-inspects `main`, deliver implementation on a dedicated branch through a reviewed draft PR and stop for a separate explicit human merge decision. Do not auto-merge the implementation PR, deploy, or perform any live request.

Rollback removes the selector API/tests. No dependency, schema, durable data, production resource, credential, or external state requires recovery.

## Embedded PRODUCT-015 high-risk assessment

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

Planning issue #107 is documentation only and does not itself queue implementation. The orchestrator may apply `codex-ready` to issue #104 only after this planning PR merges and `main` is re-inspected. Approval does not authorize implementation before those conditions, implementation merge, cache storage or retrieval, stale-on-error reuse, clock access, live retrieval, site/target binding, robots permission evaluation, crawling, scheduling, persistence, tenant/site database integration, audit or runtime integration, deployment, production traffic, or external/customer-facing activity. It does not weaken any public-contract, exact-type, validation-ordering, one-call delegation, identity, boundary, isolation, acceptance, future-gate, non-action, or rollback requirement above.

Validate documentation format, links, commands, paths, exact two-file scope, full repository gates, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate read-only cache/time/protocol/security review with zero blocking findings. Deliver through a dedicated branch and draft PR.

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
