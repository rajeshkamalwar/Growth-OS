# AGENTS.md

## Purpose
This repository is the source of truth for the Autonomous Growth OS product.

Before making any code change, read:
1. `docs/PRODUCT.md`
2. `docs/GOALS.md`
3. `docs/ARCHITECTURE.md`
4. `docs/V1-SCOPE.md`
5. `docs/DECISIONS.md`
6. `docs/CURRENT-TASK.md`

If a task conflicts with these documents, stop and surface the conflict. Do not silently rewrite requirements to match an implementation.

## Working Rules
- Never commit directly to `main`.
- Work only on a task branch.
- Finish work through a draft pull request.
- Do not deploy to production unless the task explicitly authorizes it.
- Do not force-push.
- Do not bypass failing tests, lint, type checks, security checks, or migrations.
- Do not expose, print, commit, or move secrets into source control.
- Do not make unrelated refactors unless required for the task and documented.
- Do not delete production data.
- Do not modify tenant isolation, authentication, billing, permissions, database-destructive migrations, secrets, or production infrastructure without explicit approval.
- Prefer reversible changes.
- Every external side effect must be idempotent where practical.
- All autonomous actions must be auditable.
- If confidence is insufficient for a high-risk action, request approval instead of guessing.
- Treat user-visible metrics as evidence-backed claims; never fabricate measurements.

## Required Completion Checks
For every implementation task:
- Run relevant unit tests.
- Run integration tests where applicable.
- Run lint/type checks.
- Run security checks where available.
- Confirm no unrelated files changed.
- Confirm migrations have rollback/recovery notes.
- Confirm tenant boundaries remain intact.
- Summarize what changed, what was tested, known limitations, and rollback steps.

## Documentation Protection
Changes to any of these require explicit mention in the PR:
- `docs/PRODUCT.md`
- `docs/GOALS.md`
- `docs/ARCHITECTURE.md`
- `docs/V1-SCOPE.md`
- `docs/DECISIONS.md`

Implementation must follow architecture; architecture must not be rewritten merely to justify implementation.

## Risk Gates
### Low risk — may proceed
- Read-only integrations
- Tests
- Internal refactors with no behavior change
- Documentation
- Reversible UI changes

### Medium risk — proceed only when task explicitly covers it
- New API endpoints
- New background jobs
- New database tables
- New third-party integrations
- Autonomous low-risk actions

### High risk — approval required
- Authentication/authorization
- Billing
- Tenant isolation
- Destructive database changes
- Production infrastructure
- Secret management
- Spending money
- Sending high-volume outreach
- Deleting pages/data
- Production deployment

## Auto-Merge Policy
Codex/Goal Orchestrator may automatically merge a development PR into `main` only when all
of the following are true:

1. The task is low or medium risk and is authorized by the active project goal or roadmap.
2. The implementation is on a dedicated task branch.
3. Lint, formatting, strict typing, tests, security/dependency checks, migration validation
   where applicable, and `git diff --check` all pass locally.
4. A separate reviewer pass finds no blocking issue; all findings are fixed and reverified,
   and no unresolved review comments remain.
5. The change is reversible and causes no production deployment or external customer-facing
   side effect.

Automatic merge must stop for authentication/authorization architecture, tenant isolation,
billing, destructive migrations, secrets, production infrastructure or deployment, deleting
meaningful data, spending money, publishing externally, social posting, website changes,
outreach/email, backlink creation or outreach, third-party account modifications, material
security tradeoffs, or anything explicitly classified high risk.

This policy authorizes merge only. It does not authorize deployment or any otherwise gated
external action.

## Definition of Done
A task is not done because code was written. It is done only when its acceptance criteria are met, tests pass, evidence is provided, risks are documented, and a draft PR is ready for review.
