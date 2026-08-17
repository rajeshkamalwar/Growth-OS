# Current Task

## Task ID

PRODUCT-013 ([GitHub issue #92](https://github.com/rajeshkamalwar/Growth-OS/issues/92))

## Status: Implementation approved 2026-08-17 — executable after planning merge/reinspection

PRODUCT-012 and PR #91 are merged at
`43c2eee2c7bea41cc34cf8e81dd1f975d3409752`.

The user explicitly approved PRODUCT-013's exact offline site-bound robots adapter contract in
[`plans/PRODUCT-013.md`](../plans/PRODUCT-013.md) on 2026-08-17.

PRODUCT-013 remains **high risk** because its site/target/provenance binding determines whether a
future crawler could apply the correct robots outcome to a target URL. Approval becomes executable
only after this planning PR merges and the orchestrator re-inspects `main`. Planning issue #95 does
not itself queue implementation; only after that merge and reinspection may the orchestrator apply
`codex-ready` to issue #92.

Approval authorizes only the deterministic, synchronous, offline site-bound robots adapter, its
values-only tests, verification, and a reviewed draft implementation PR under issue #92's exact
contract. It does not authorize implementation merge, DNS or HTTP, robots or target retrieval,
crawling, caching/expiry, scheduling, persistence, tenant/site database integration, audit or
runtime integration, deployment, production traffic, external/customer-facing activity, or
weakening or broadening issue #92.

## Mandatory Human Implementation-Merge Gate

The complete approved contract, including its exact public contract, strict input/one-of rules,
shared URL normalization, exact-origin comparison, path-plus-query derivation, provenance equality,
identity-preserving PRODUCT-012 delegation, isolation, acceptance matrix, future gates,
non-action boundary, and rollback contract, is preserved in
[`plans/PRODUCT-013.md`](../plans/PRODUCT-013.md).

After all gates pass, including a fresh independent URL/protocol/security-focused read-only review
with zero blocking findings, the high-risk implementation PR must not be auto-merged and must
remain open for a separate explicit human merge decision. The values-only/offline/no-live-network
boundary and every future-integration gate remain mandatory.

## Planning Delivery and Rollback

Planning issue #95 is documentation only. It changes exactly this file and
`plans/PRODUCT-013.md`; it records approval but does not itself queue or implement PRODUCT-013,
apply `codex-ready`, merge implementation, or authorize any live or external activity.

Planning rollback restores the proposal-only approval gate for PRODUCT-013. No runtime,
dependency, schema, data, production, or external recovery is needed.
