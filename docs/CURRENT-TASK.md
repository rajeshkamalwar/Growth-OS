# Current Task

## Task ID

PRODUCT-010 ([GitHub issue #74](https://github.com/rajeshkamalwar/Growth-OS/issues/74))

## Status: Approval Gate — Not an Executable Task

PRODUCT-009 is merged. The next dependency is the proposed offline robots access-outcome policy
recorded in [`plans/PRODUCT-010.md`](../plans/PRODUCT-010.md).

PRODUCT-010 is **Proposed — approval required; not authorized for implementation**. It is a
material security policy because its HTTP status, network-failure, and invalid-policy semantics
will determine whether future autonomous access is permitted. The user must explicitly approve
this policy before issue #74 may become executable.

Neither planning issue #75 nor its merge authorizes applying `codex-ready` to issue #74,
implementation, implementation merge, robots.txt retrieval, caching, integration with
PRODUCT-008, crawling, scheduling, deployment, production traffic, or any external/customer-facing
activity.

## Proposed Runtime Boundary

The proposal adds a deterministic offline interpreter over a caller-supplied retrieval outcome,
caller-supplied robots bytes where applicable, and caller-supplied target path. It composes the
merged PRODUCT-009 evaluator and returns a value-backed access decision with exact status,
nested-policy, or policy-error provenance.

The complete proposed contract, strict input invariants, RFC 9309 outcome semantics, fail-closed
behavior, tests, future integration gates, risk, and rollback are preserved in
[`plans/PRODUCT-010.md`](../plans/PRODUCT-010.md) from issue #74.

The proposal performs no HTTP, DNS, file access, URL construction, redirects, caching, scheduling,
persistence, logging, audit, active enforcement, or runtime integration. Any future acquisition
or crawler integration requires a separately reviewed and approved contract.

## Planning Delivery and Rollback

This approval-gate update is documentation only. It changes exactly this file and the new
`plans/PRODUCT-010.md`; it does not modify runtime code, tests, README, dependencies, migrations,
protected product/architecture/goal/decision documents, infrastructure, or deployment.

Planning rollback restores PRODUCT-009 as the recorded current task and removes the PRODUCT-010
proposal. No runtime, dependency, schema, data, production, or external recovery is needed.
