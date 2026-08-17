# PRODUCT-013: Offline Site-Bound Robots Adapter

## Status and Authority

**Implementation explicitly approved 2026-08-17 — executable after this planning PR merges and
the orchestrator re-inspects `main`; separate human implementation-merge approval required.**

This plan preserves the exact contract from
[GitHub issue #92](https://github.com/rajeshkamalwar/Growth-OS/issues/92). The user explicitly
approved implementation under that contract on 2026-08-17. The approval becomes executable only
after planning issue #95's PR merges and the orchestrator re-inspects `main`.

Planning issue #95 does not itself queue implementation. Only after the merge and reinspection may
the orchestrator apply `codex-ready` to issue #92. Approval authorizes only the deterministic,
synchronous, offline site-bound robots adapter, its values-only tests and verification, and a
reviewed draft implementation PR under issue #92's exact contract. It does not authorize
implementation merge, DNS or HTTP, robots or target retrieval, crawling, caching/expiry,
scheduling, persistence, tenant/site database integration, audit or runtime integration,
deployment, production traffic, external/customer-facing activity, or weakening or broadening
issue #92.

## Security status: implementation approved; human merge approval required

This is an approved material security-policy contract. After this planning PR merges and the
orchestrator re-inspects `main`, the orchestrator may queue implementation under issue #92. The
implementation PR must remain open after all gates and a fresh independent
URL/protocol/security-focused read-only review for a separate explicit human merge decision.

## Objective

Add a deterministic, synchronous, offline adapter that binds a caller-supplied absolute target URL to a caller-supplied site URL, verifies exact same-origin ownership, validates PRODUCT-011 acquisition provenance when present, derives the exact path-plus-query used by PRODUCT-009/010/012, and delegates exactly once to PRODUCT-012.

This milestone performs no HTTP, DNS, file access, target-page fetch, robots fetch, caching, scheduling, persistence, logging, audit, execution, API/CLI, worker, crawler, or runtime integration. Tests use values only and never contact a real website.

## Risk and approval boundary

Risk is **high** because site/target/provenance binding determines whether a future crawler could
apply the correct robots outcome to a target URL. Approval authorizes implementation, values-only
tests, verification, and a reviewed draft PR only. After all gates pass, including a fresh
independent URL/protocol/security-focused read-only review with zero blocking findings, the
implementation PR must not be auto-merged and must remain open for a separate explicit human merge
decision. Approval does not authorize implementation merge, DNS or HTTP, robots or target
retrieval, crawling, caching/expiry, scheduling, persistence, tenant/site database integration,
audit or runtime integration, deployment, production traffic, external/customer-facing activity,
or weakening or broadening issue #92.

## Public contract

Add `src/growth_os/robots/binding.py` and extend `growth_os.robots` exports with exactly:

```python
class RobotsBindingErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_URL = "invalid_url"
    DISALLOWED_PORT = "disallowed_port"
    CROSS_ORIGIN = "cross_origin"
    PROVENANCE_MISMATCH = "provenance_mismatch"


class RobotsBindingError(ValueError):
    code: RobotsBindingErrorCode


@dataclass(frozen=True, slots=True)
class BoundRobotsDecision:
    site_url: str
    target_url: str
    target_path: str
    gate_decision: RobotsGateDecision


def evaluate_bound_robots(
    *,
    site_url: str,
    target_url: str,
    fetched_robots: FetchedRobots | None,
    fetch_error_code: RobotsFetchErrorCode | None,
) -> BoundRobotsDecision: ...
```

The dataclass is immutable/equality-comparable with exactly those fields and order. Errors expose only the stable message `Robots binding failed: <code>` and never include URLs, paths, bodies, rules, redirect data, addresses, or exception text.

## Exact validation and binding contract

- Require exact strings for `site_url` and `target_url`; reject subclasses/coercion/empty values with `INVALID_INPUT`.
- Require exactly one of exact `FetchedRobots` and exact `RobotsFetchErrorCode`, matching PRODUCT-012’s one-of/type rules; malformed combinations use `INVALID_INPUT` before URL work.
- Normalize both URLs through the existing shared PRODUCT-008/011 absolute HTTP(S) URL normalizer without DNS resolution. Preserve its scheme, authority, IDNA, IP-literal, userinfo, malformed-authority, default-port-only, query, fragment-removal, and error behavior, mapped only to stable `INVALID_URL` or `DISALLOWED_PORT` binding errors.
- Require target and site to have the exact same normalized origin: scheme, normalized host, and effective default port. HTTP/HTTPS differences, subdomains, sibling domains, deceptive suffixes, distinct IP literals, and any other authority difference are `CROSS_ORIGIN`.
- Return normalized absolute site and target URLs with fragments removed. Derive `target_path` from the normalized target’s encoded absolute path plus optional encoded query, beginning with `/`; never include scheme, authority, userinfo, or fragment.
- When `fetched_robots` is present, require its `requested_site_url` to equal the normalized supplied site URL exactly before delegation. Any mismatch is `PROVENANCE_MISMATCH`; do not silently compare only origin or rewrite the fetched value.
- Delegate exactly once to PRODUCT-012 with the exact fetched/error object and derived target path. Preserve the exact returned `RobotsGateDecision` object and its allowed bit, reason, nested access decision, acquisition provenance, and error provenance without reinterpretation.
- Let PRODUCT-012 reject any other malformed caller-constructed fetched value with its unchanged stable error. Do not catch or rewrite PRODUCT-009/010/012 target/policy errors after successful binding.

## Determinism and non-action boundary

Use only existing dependencies and shared normalization plus PRODUCT-012 public values/functions. Do not resolve hosts or inspect IP admission, fetch robots/HTML, follow redirects, consult caches, construct fallbacks, mutate/copy inputs, or import this adapter from active application paths. Add no dependency, route, schema, migration, repository, service, connector, audit event, job, worker, scheduler, rate/concurrency control, or crawler orchestration.

Future separately approved milestones must still define cache/expiry/validators, tenant/site database ownership, audit linkage, idempotency, rate/concurrency, scheduling, target-page acquisition ordering, durable execution, and fail-closed operational behavior before any crawler or active runtime use.

## Acceptance tests

1. Exact public types, fields, exports, signature, immutability, equality, and redacted errors.
2. Exhaustive strict type/one-of input rejection before URL normalization or gate delegation.
3. URL normalization parity for case, IDNA, IP literals, default ports, paths, queries, fragments, invalid authorities, userinfo, schemes, and disallowed ports.
4. Same-origin acceptance and exhaustive cross-origin rejection, including deceptive hostname suffixes and scheme/port differences.
5. Exact encoded path-plus-query derivation for root, Unicode, percent-encoded, reserved, empty-query, and fragment cases, with PRODUCT-009 target validation preserved.
6. Exact fetched requested-site provenance equality and fail-closed mismatch behavior before gate delegation.
7. PRODUCT-012 called exactly once for representative fetched, unreachable, and rejected outcomes; exact nested decision identity/provenance preserved.
8. Repeated calls deterministic; inputs unchanged; no cache/fallback inferred.
9. Static/runtime isolation proves no network/DNS/file/database/connector/audit/execution/logging/active-path or real-network call.
10. PRODUCT-008 through PRODUCT-012 and evidence regressions remain unchanged and pass.

Run focused binding/robots/acquisition/evidence tests, full pytest, Ruff lint/format, strict mypy, pip-audit, `make check`, offline Alembic upgrade/downgrade rendering, and `git diff --check`. Obtain a fresh separate URL/protocol/security-focused read-only reviewer pass with zero blocking findings.

## Delivery and rollback

After this planning PR merges and the orchestrator re-inspects `main`, deliver implementation on a
dedicated branch through a reviewed draft PR and stop for a separate explicit human merge decision
because this defines material crawler-permission semantics. Do not deploy or perform any live
request.

Rollback removes the binding API/tests. No dependency, schema, durable data, production resource, credential, or external state requires recovery.

## Embedded PRODUCT-013 high-risk assessment

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

Planning issue #95 changes exactly `docs/CURRENT-TASK.md` and this plan. It records the user's
explicit implementation approval but does not itself queue or implement PRODUCT-013. Only after
this planning PR merges and the orchestrator re-inspects `main` may the orchestrator apply
`codex-ready` to issue #92. Neither planning issue #95 nor its merge authorizes implementation
merge, DNS or HTTP, robots or target retrieval, crawling, caching/expiry, scheduling, persistence,
tenant/site database integration, audit or runtime integration, deployment, production traffic,
external/customer-facing activity, or weakening or broadening issue #92.

Validate documentation/link/command/path hygiene, all repository local gates, offline migration
rendering, `git diff --check`, and exact two-file scope. Obtain a fresh separate read-only
URL/protocol/security review with zero blocking findings, then deliver the planning change on a
dedicated branch through a draft PR.

Planning rollback restores the proposal-only approval gate for PRODUCT-013. No runtime,
dependency, schema, data, production, or external recovery is needed.

The planning issue #95 assessment is:

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
approval separately authorizes PRODUCT-013 implementation only after this planning PR merges and
the orchestrator re-inspects `main`; neither authorization permits implementation merge, live
network activity, runtime integration, deployment, or any external/customer-facing action.
