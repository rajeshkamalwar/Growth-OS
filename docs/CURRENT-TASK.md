# Current Task

## Task ID

PRODUCT-011 ([GitHub issue #80](https://github.com/rajeshkamalwar/Growth-OS/issues/80))

## Status: Proposed — Approval Required; Not Authorized for Implementation

PRODUCT-010 is merged. The next proposed dependency is the fail-closed robots.txt acquisition
boundary recorded in [`plans/PRODUCT-011.md`](../plans/PRODUCT-011.md).

PRODUCT-011 remains an approval gate, not an executable task. It is **high risk** because it adds
outbound network behavior and may refactor the shared SSRF/TLS transport boundary. Do not apply
`codex-ready` to issue #80 or implement it until the user explicitly approves the complete
proposal after this planning PR merges.

Neither planning issue #81 nor its merge authorizes `codex-ready` on issue #80, implementation,
implementation merge, live retrieval, permission evaluation, crawling, caching, scheduling,
integration, deployment, or any external activity.

## Proposed Runtime Boundary

The proposal adds an explicitly invoked, asynchronous, fail-closed robots.txt acquisition
primitive for a caller-supplied public HTTP(S) site URL. It derives the initial authority's root
`/robots.txt` URL, fetches through the same SSRF-resistant per-hop transport guarantees as
PRODUCT-008, and returns a bounded terminal status/body value that may later be supplied to
PRODUCT-010 only through a separately approved integration.

The complete proposed contract, including its public types, URL derivation, shared transport
constraints, SSRF/DNS/rebinding/TLS guarantees, request protocol, terminal-response handling,
bounded body rules, cleanup, isolation tests, risk gates, future integration requirements, and
rollback, is preserved in [`plans/PRODUCT-011.md`](../plans/PRODUCT-011.md) from issue #80.

The proposal remains unintegrated. It does not evaluate permission, fetch a target page, crawl,
cache, schedule, persist, audit, expose an API/CLI, or run from an active application path. Tests
must use controlled fakes only and must never contact a real website.

## Planning Delivery and Rollback

Planning issue #81 is documentation only. It changes exactly this file and
`plans/PRODUCT-011.md`; it does not modify runtime code, tests, README, dependencies, migrations,
protected product/architecture/goal/decision documents, infrastructure, or deployment.

Planning rollback restores PRODUCT-010 as current and removes the PRODUCT-011 proposal. No
runtime, dependency, schema, data, production, or external recovery is needed.
