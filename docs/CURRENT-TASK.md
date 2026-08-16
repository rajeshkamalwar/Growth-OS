# Current Task

## Task ID
PLANNING-003 ([GitHub issue #39](https://github.com/rajeshkamalwar/Growth-OS/issues/39))

## Authorization
Correct the pre-implementation PRODUCT-002 specification so it matches the authoritative
[GitHub issue #36](https://github.com/rajeshkamalwar/Growth-OS/issues/36) contract. This task does
not queue or authorize PRODUCT-002 runtime implementation.

## Required Outcome
- Use `workspace_primary_growth_goals` for the table and
  `WorkspacePrimaryGrowthGoal` / `workspace_primary_growth_goal` for the model and resource.
- Use `/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/primary-growth-goal` for the API path.
- Use `workspace_primary_growth_goal.created` and
  `workspace_primary_growth_goal.updated` for audit events.
- Bound optional `success_definition` to 2,000 characters.
- Align migration, test, rollback, example, filename, prose, and verification references with
  those corrected names while preserving the rest of issue #36's contract.

## Constraints
- Change only `docs/CURRENT-TASK.md` and `plans/PRODUCT-002.md`.
- Do not change issue #36, broaden PRODUCT-002, or modify runtime source, migrations, tests,
  README, dependencies, protected product, architecture, goal, or decision documents, or
  infrastructure.
- Do not queue PRODUCT-002. The orchestrating agent may do so only after this correction merges
  and the resulting `main` branch is inspected.
- Do not deploy or cause external behavior.

## Specification Correction

Issue #36 remains authoritative. PLANNING-003 corrects superseded names and the
`success_definition` bound before PRODUCT-002 is queued; no runtime implementation occurred under
the superseded names.

## Completion Gates
- The corrected documents exactly match issue #36 for table, route, resource/event naming, and
  field bounds, with no superseded PRODUCT-002 contract terms remaining.
- Only `docs/CURRENT-TASK.md` and `plans/PRODUCT-002.md` change.
- Applicable repository gates and `git diff --check` pass.
- A separate read-only reviewer reports zero blocking findings.
- Work remains on the dedicated task branch for the controller to deliver through a draft pull
  request.
