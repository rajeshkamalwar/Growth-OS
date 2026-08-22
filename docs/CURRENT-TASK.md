# Current Task

## Task ID

PRODUCT-015 ([GitHub issue #104](https://github.com/rajeshkamalwar/Growth-OS/issues/104))

## Status: approved — executable only after planning merge and `main` reinspection

PRODUCT-014 and PR #103 are merged at
`2cef25ca3b2e1aae62657ba2e3e271dce9d689a5`.

On 2026-08-17, the user explicitly approved implementation of PRODUCT-015 under issue #104's
exact contract, preserved in [`plans/PRODUCT-015.md`](../plans/PRODUCT-015.md). That approval
becomes executable only after the planning PR for issue #107 merges and the orchestrator
re-inspects `main`. Planning issue #107 does not itself queue implementation; only after that
merge and reinspection may the orchestrator apply `codex-ready` to issue #104.

## Approval and Merge Gates

After the planning merge and `main` reinspection, approval authorizes only the deterministic,
synchronous, offline cached-outcome selector, its values-only tests, verification, and a reviewed
draft implementation PR under issue #104's exact contract.

PRODUCT-015 remains **high risk** because selecting a cached robots acquisition outcome can affect
future crawl authorization. The implementation PR must not be auto-merged and must remain open
after all gates and a fresh independent cache/time/protocol/security-focused read-only review with
zero blocking findings for a separate explicit human merge decision.

Approval does not authorize implementation merge, cache storage or retrieval, stale-on-error
reuse, clock access, live retrieval, site/target binding, robots permission evaluation, crawling,
scheduling, persistence, tenant/site database integration, audit or runtime integration,
deployment, production traffic, or any external/customer-facing activity. It does not authorize
weakening or broadening issue #104.

Every no-action, fail-closed, exact-type and exact-identity composition requirement, PRODUCT-014
delegation rule, PRODUCT-012 acquisition-error boundary, PRODUCT-013 future-use gate, and future
integration gate in the complete PRODUCT-015 contract remains mandatory.

## Planning Delivery and Rollback

Planning issue #107 is documentation only and changes exactly this file and
`plans/PRODUCT-015.md`. It records the 2026-08-17 approval but does not itself queue implementation
or authorize implementation before its planning PR merges and the orchestrator re-inspects
`main`. It does not authorize implementation merge, deployment, live requests, or any external
activity.

Planning rollback restores the prior proposal-only wording in both changed files. No runtime,
dependency, schema, durable data, production resource, credential, or external recovery is
needed.
