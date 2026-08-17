# Current Task

## Task ID

PRODUCT-009 ([GitHub issue #68](https://github.com/rajeshkamalwar/Growth-OS/issues/68))

## Status: Approval Gate — Not an Executable Task

PRODUCT-008 is merged. The next dependency is the proposed RFC 9309 offline robots permission
evaluator recorded in [`plans/PRODUCT-009.md`](../plans/PRODUCT-009.md).

PRODUCT-009 is **Proposed — approval required; not authorized for implementation**. It is a
material security policy because its semantics will eventually determine whether autonomous
network access is permitted. The user must explicitly approve the robots permission policy before
issue #68 may become an executable implementation task.

Neither planning issue #69 nor its merge authorizes applying `codex-ready` to issue #68, runtime
implementation, implementation merge, deployment, retrieval of robots.txt or any other resource,
or crawling. The orchestrator must leave issue #68 unqueued until explicit approval is recorded.

## Proposed Runtime Boundary

The proposal defines a deterministic, offline evaluator for the fixed product token
`GrowthOSBot`. It accepts caller-supplied UTF-8 robots.txt bytes and a caller-supplied target
path/query, and returns a value-backed allow/disallow decision with exact rule provenance where
applicable. The complete proposed contract, limits, RFC parsing and matching semantics, tests,
future integration gates, risk boundary, and rollback are preserved in
[`plans/PRODUCT-009.md`](../plans/PRODUCT-009.md) from issue #68.

The proposal performs no HTTP, DNS, file access, scheduling, persistence, caching, logging, audit,
active enforcement, or runtime integration. A future separately approved integration must define
retrieval status semantics, initial-authority context, redirects, caching/expiry, tenant/site
ownership, audit linkage, rate/concurrency controls, idempotency, and fail-closed operational
behavior.

## Planning Delivery and Rollback

This approval-gate update is documentation only. It changes exactly this file and the new
`plans/PRODUCT-009.md`, and it does not modify runtime code, tests, dependencies, migrations,
protected product/architecture/goal/decision documents, infrastructure, or deployment.

Planning rollback restores PRODUCT-008 as the recorded current task and removes the PRODUCT-009
proposal. No runtime, dependency, schema, data, production, or external recovery is needed.
