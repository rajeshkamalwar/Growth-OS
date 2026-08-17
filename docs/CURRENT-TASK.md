# Current Task

## Task ID

PRODUCT-014 ([GitHub issue #98](https://github.com/rajeshkamalwar/Growth-OS/issues/98))

## Status: Proposed — explicit security approval required

PRODUCT-013 and PR #97 are merged at
`ca199a8d611b3d4f44e49aedea4deb3725e1f38b`.

PRODUCT-014 proposes the exact offline robots cache freshness policy preserved in
[`plans/PRODUCT-014.md`](../plans/PRODUCT-014.md). It is **high risk** because cache freshness
determines whether a future crawler may reuse a prior robots acquisition outcome. Do not apply
`codex-ready` to issue #98 or implement PRODUCT-014 until this planning proposal is merged and the
user explicitly approves that exact policy.

## Approval and Merge Gates

Only a future explicit approval may authorize implementation, values-only tests, verification,
and a reviewed draft PR under issue #98's exact contract. Implementation merge remains separately
human-gated even after every implementation and review gate passes.

No current authorization exists for implementation, implementation merge, stale-on-error reuse,
cache storage or reuse, live retrieval, target-page fetching, crawling, scheduling, persistence,
tenant/site database integration, audit, runtime integration, deployment, production traffic, or
external/customer-facing activity. Every no-action, fail-closed, and future-integration gate in
the complete PRODUCT-014 contract remains mandatory.

## Planning Delivery and Rollback

Planning issue #99 is documentation only. It changes exactly this file and
`plans/PRODUCT-014.md`; it records PRODUCT-013 and PR #97 as merged and establishes PRODUCT-014 as
the next proposed milestone. It does not itself authorize or queue PRODUCT-014 implementation or
any live or external activity.

Planning rollback restores the prior PRODUCT-013 current-task record and removes the PRODUCT-014
proposal. No runtime, dependency, schema, data, production, credential, or external recovery is
needed.
