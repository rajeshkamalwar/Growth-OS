# Current Task

## Task ID
FOUNDATION-004 (GitHub issue #9)

## Authorization
Build the tenant-safe internal execution/control layer on FOUNDATION-003.

## Goal
Add execution jobs/runs, inert action proposals, approval decisions, bounded retries,
idempotency, and an audit trail without performing external actions.

## Required Outcome
- Execution and proposal state is explicit and terminal transitions are guarded.
- Every execution request is idempotent within its tenant.
- Approval decisions are append-only, tenant-safe, and final.
- High-risk proposed actions cannot bypass explicit human approval.
- Meaningful execution and decision changes create tenant-scoped audit events.
- Control-plane list APIs preserve bounded pagination and structured errors.

## Constraints
- Do not add an executor, scheduler, connector, agent, LLM, n8n, or Temporal integration.
- Do not change tenant-context or authentication architecture.
- Do not perform external actions or production side effects.
- Follow `AGENTS.md` and the repository source-of-truth documents.

## Completion Gates
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and
  `git diff --check` pass where available.
- Existing health/readiness and FOUNDATION-003 APIs remain intact.
- Work is delivered from a task branch through a draft pull request.
