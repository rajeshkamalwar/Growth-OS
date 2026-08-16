# Current Task

## Task ID

PRODUCT-004 ([GitHub issue #48](https://github.com/rajeshkamalwar/Growth-OS/issues/48))

## Authorization

Add one tenant-safe, read-only onboarding-status projection over existing durable site, business
profile, primary growth goal, and autonomy policy records. Follow the reviewed implementation
specification in [`plans/PRODUCT-004.md`](../plans/PRODUCT-004.md); issue #48 remains the
authoritative runtime contract. If implementation requires a design change, update and review the
specification before changing runtime code.

This current-task update authorizes implementation of PRODUCT-004 after this planning change is
merged. It does not queue controller work, authorize deployment, or authorize applying the
`codex-ready` label to issue #48. The orchestrator owns that label only after it re-inspects the
resulting `main`.

## Goal

Expose exactly one GET endpoint:

```text
/api/v1/tenants/{tenant_id}/workspaces/{workspace_id}/onboarding-status
```

The response reports the parent tenant/workspace identity, four existence flags, foundational
completeness, and canonically ordered missing steps. `OnboardingStep` has exactly `site`,
`business_profile`, `primary_growth_goal`, and `autonomy_policy`, in that order. The response
fields are exactly:

- `tenant_id`
- `workspace_id`
- `has_site`
- `has_business_profile`
- `has_primary_growth_goal`
- `has_autonomy_policy`
- `is_foundation_complete`
- `missing_steps`

`is_foundation_complete` is true only when all four flags are true. `missing_steps` contains each
false flag's corresponding `OnboardingStep` in canonical enum order, never repository or creation
order.

This projection means foundational record completeness only. It is not connector authentication,
monitoring readiness, approval, permission, policy enforcement, execution eligibility, or
operational readiness.

## Required Outcome

- Add a strict typed response schema and the exact four-value `OnboardingStep` string enum.
- Add explicit repository behavior that checks tenant/workspace-scoped existence for all four
  record types efficiently, without returning or hydrating underlying resource content.
- Add service behavior that first validates the workspace through the established tenant-safe
  ownership path, derives the two summary fields deterministically, and performs no mutation.
- Add only the GET route above. It returns 200 for an existing same-tenant workspace, including
  when every foundational record is absent.
- Require the existing `X-Tenant-ID` context to match the path tenant. Missing and cross-tenant
  workspaces return the same established structured `not_found` response without disclosing
  cross-tenant existence or foundation state.
- Treat any tenant/workspace-scoped site as satisfying `has_site`; the other three flags represent
  existence of their zero-or-one workspace records.
- Update README usage and semantics to state the foundational-record-only meaning and every
  excluded readiness or authority interpretation above.
- Emit no audit event and perform no flush, commit, mutation, migration, job, network call, or
  external action.

## Implementation Constraints

- Extend the existing explicit Pydantic schema, `FoundationRepository`, `FoundationService`,
  structured-error, tenant-context, and foundation-router patterns. Do not add a generic projection
  framework, dependency, cache, table, migration, or persisted onboarding state.
- Query only existence using explicit tenant-and-workspace predicates for `Site`,
  `WorkspaceBusinessProfile`, `WorkspacePrimaryGrowthGoal`, and `WorkspaceAutonomyPolicy`.
  Prefer one repository round trip containing four named `EXISTS` expressions after tenant-safe
  parent validation; do not select models or resource fields.
- Derive `is_foundation_complete` with `all(...)` over the four flags and derive `missing_steps`
  from the fixed canonical order: `site`, `business_profile`, `primary_growth_goal`,
  `autonomy_policy`.
- Do not inspect connector rows or status, site reachability, record field quality, policy level or
  paused state, approvals, permissions, monitoring, execution, jobs, agents, integrations, or
  external systems. Existence alone determines each flag.
- Do not add POST, PATCH, PUT, DELETE, list, audit, mutation, frontend, worker, connector, or
  enforcement behavior.
- Do not change authentication, authorization, permissions, tenant-context architecture, billing,
  secrets, production infrastructure, deployment behavior, or protected product, architecture,
  goal, or decision documents.

## Verification Gates

- Deterministic API/service/repository tests cover none, each individual record, mixed subsets,
  and all four records; exact response fields and parent IDs; canonical `missing_steps`; and
  complete-only-when-all derivation.
- Tenant-isolation and error tests cover header/path mismatch, invalid UUIDs, missing workspace,
  cross-tenant workspace, same identifiers or records in another tenant, and established
  structured responses without leaking flags.
- Query-shape tests or equivalent focused assertions prove the projection selects only explicit
  existence expressions with tenant/workspace predicates and does not return underlying content.
- Side-effect tests prove GET creates no audit event, does not call flush/commit, and causes no
  mutation, connector call, job, execution transition, or external action.
- Route tests prove exactly the singular GET behavior and the absence of POST, PATCH, PUT, DELETE,
  and list variants.
- Run focused PRODUCT-004 tests, the full pytest suite, Ruff lint and format checks, strict mypy,
  pip-audit, `make check`, and `git diff --check` without bypassing failures.
- Confirm only issue-authorized implementation files change, tenant boundaries remain intact,
  rollback guidance is complete, and a separate read-only reviewer reports zero blocking findings.
- Deliver implementation from a dedicated task branch through a draft pull request. Do not merge
  or deploy.

## Rollback and Recovery

Revert the PRODUCT-004 implementation commit to remove the route, schema, repository/service
projection, focused tests, and README update. PRODUCT-004 adds no migration, persisted state,
mutation, audit, production operation, or external side effect, so no data rollback or recovery
procedure is required.

For this planning-only authorization change, revert its documentation commit to restore
PRODUCT-003 as the recorded current task and remove the unimplemented PRODUCT-004 plan.
