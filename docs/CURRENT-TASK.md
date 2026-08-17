# Current Task

## Task ID

PRODUCT-009 ([GitHub issue #68](https://github.com/rajeshkamalwar/Growth-OS/issues/68))

## Status: Implementation Authorized After Planning Merge — Human Merge Required

PRODUCT-008 is merged. The next dependency is the approved RFC 9309 offline robots permission
evaluator recorded in [`plans/PRODUCT-009.md`](../plans/PRODUCT-009.md).

The user explicitly approved PRODUCT-009 implementation on 2026-08-17 under the exact contract in
issue #68. That approval becomes executable only after this planning PR merges and the orchestrator
re-inspects `main`. This planning task does not itself queue implementation; only after that
re-inspection may the orchestrator apply `codex-ready` to issue #68.

The approval authorizes only the deterministic offline evaluator, its tests and verification, and
a reviewed draft implementation PR. PRODUCT-009 remains **high risk** because it defines a
material security permission policy. The implementation PR must not be auto-merged: after all
gates pass, including a fresh independent protocol/security review with zero blocking findings,
it must remain open for a separate explicit human merge decision.

The approval does not authorize merging the implementation PR, fetching robots.txt or any other
network resource, integrating with PRODUCT-008, crawling or scheduling, deployment or production
traffic, any external/customer-facing effect, or weakening or broadening issue #68's contract.

## Authorized Implementation Boundary

The authorized implementation defines a deterministic, offline evaluator for the fixed product
token `GrowthOSBot`. It accepts caller-supplied UTF-8 robots.txt bytes and a caller-supplied target
path/query, and returns a value-backed allow/disallow decision with exact rule provenance where
applicable. The complete exact contract, limits, RFC parsing and matching semantics, tests,
future integration gates, risk boundary, and rollback are preserved in
[`plans/PRODUCT-009.md`](../plans/PRODUCT-009.md) from issue #68.

The evaluator performs no HTTP, DNS, file access, scheduling, persistence, caching, logging, audit,
active enforcement, or runtime integration. A future separately approved integration must define
retrieval status semantics, initial-authority context, redirects, caching/expiry, tenant/site
ownership, audit linkage, rate/concurrency controls, idempotency, and fail-closed operational
behavior.

## Planning Delivery and Rollback

This approval-record update is documentation only. It changes exactly this file and
`plans/PRODUCT-009.md`, and it does not modify runtime code, tests, dependencies, migrations,
protected product/architecture/goal/decision documents, infrastructure, or deployment.

Planning rollback restores the proposal-only approval gate for PRODUCT-009. No runtime,
dependency, schema, data, production, or external recovery is needed.
