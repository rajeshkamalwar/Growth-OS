# Current Task

## Task ID

PRODUCT-012 ([GitHub issue #86](https://github.com/rajeshkamalwar/Growth-OS/issues/86))

## Status: Proposed — approval required; not authorized for implementation

PRODUCT-011 is merged. PRODUCT-012 is the proposed offline robots acquisition outcome gate
recorded in [`plans/PRODUCT-012.md`](../plans/PRODUCT-012.md).

PRODUCT-012 remains **high risk** because its mapping determines whether a future crawler could
proceed after a robots acquisition outcome or failure. Do not apply `codex-ready` to issue #86 or
implement the proposal unless the user explicitly approves its exact contract after this planning
proposal merges.

Neither planning issue #87 nor its merge authorizes `codex-ready` on issue #86, implementation,
implementation merge, live retrieval, crawling, caching, scheduling, persistence, integration,
deployment, or any external activity.

## Approval Gate

The complete proposed contract, including exact public values, strict input and provenance
invariants, fetched-result composition, unreachable and rejected error mapping, fail-closed
behavior, target validation, isolation, tests, future integration gates, risk, and rollback, is
preserved in [`plans/PRODUCT-012.md`](../plans/PRODUCT-012.md).

This is an approval gate, not an executable task. A future explicit approval may authorize only
implementation, tests, verification, and a reviewed draft PR under issue #86's exact contract.
Implementation merge and all live or external activity require separate authorization.

## Planning Delivery and Rollback

Planning issue #87 is documentation only. It changes exactly this file and
`plans/PRODUCT-012.md`; it does not modify runtime code, tests, README, dependencies, migrations,
protected product/architecture/goal/decision documents, infrastructure, or deployment.

Planning rollback restores PRODUCT-011 as current and removes the PRODUCT-012 proposal. No
runtime, dependency, schema, data, production, or external recovery is needed.
