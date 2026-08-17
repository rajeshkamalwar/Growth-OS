# Current Task

## Task ID

PRODUCT-011 ([GitHub issue #80](https://github.com/rajeshkamalwar/Growth-OS/issues/80))

## Status: Approved for Implementation After Planning Merge/Reinspection; Human Merge Required

PRODUCT-010 is merged. On 2026-08-17, the user explicitly approved implementation of the
fail-closed robots.txt acquisition boundary recorded in
[`plans/PRODUCT-011.md`](../plans/PRODUCT-011.md), under issue #80's exact contract.

The authorization becomes executable only after planning issue #83's PR merges and the
orchestrator re-inspects `main`. Planning issue #83 itself does not queue implementation. Only
after that merge and reinspection may the orchestrator apply `codex-ready` to issue #80.

PRODUCT-011 remains **high risk** because it adds outbound HTTP/DNS behavior and may refactor the
shared PRODUCT-008 SSRF/TLS transport boundary. The approval authorizes only the explicitly
invoked, asynchronous, fail-closed robots.txt acquisition primitive, controlled-fake tests,
verification, and a reviewed draft implementation PR under issue #80's exact contract.

The implementation PR must not be auto-merged. It must remain open after all gates and a fresh
independent SSRF/protocol/security-focused read-only review with zero blocking findings, pending a
separate explicit human merge decision. Approval does not authorize implementation merge, live
retrieval, PRODUCT-010 composition, target-page fetching, crawling, caching, scheduling,
persistence, runtime integration, deployment, production traffic, or any external/customer-facing
activity, and it does not weaken or broaden issue #80.

## Authorized Implementation Boundary

The authorized implementation adds an explicitly invoked, asynchronous, fail-closed robots.txt
acquisition primitive for a caller-supplied public HTTP(S) site URL. It derives the initial
authority's root `/robots.txt` URL, fetches through the same SSRF-resistant per-hop transport
guarantees as PRODUCT-008, and returns a bounded terminal status/body value that may later be
supplied to PRODUCT-010 only through a separately approved integration.

The complete contract, including its public types, URL derivation, shared transport
constraints, SSRF/DNS/rebinding/TLS guarantees, request protocol, terminal-response handling,
bounded body rules, cleanup, isolation tests, risk gates, future integration requirements, and
rollback, is preserved in [`plans/PRODUCT-011.md`](../plans/PRODUCT-011.md) from issue #80.

The implementation must remain unintegrated. It does not evaluate permission, fetch a target
page, crawl, cache, schedule, persist, audit, expose an API/CLI, or run from an active application
path. Tests must use controlled fakes only and must never contact a real website.

## Planning Delivery and Rollback

Planning issue #83 is documentation only. It changes exactly this file and
`plans/PRODUCT-011.md`; it does not queue or implement PRODUCT-011 and does not modify runtime
code, tests, README, dependencies, migrations, protected product/architecture/goal/decision
documents, infrastructure, or deployment.

Planning rollback reverts issue #83's approval record and restores PRODUCT-011's proposal-only
gate. No runtime, dependency, schema, data, production, or external recovery is needed.
