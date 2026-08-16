# Current Task

## Task ID
FOUNDATION-002

## Authorization
Replace the completed FOUNDATION-001 task with this application-foundation task and proceed.

## Goal
Create the initial Growth OS application foundation without implementing product-specific SEO, GEO, SMM, backlink, CRO, billing, or production integrations yet.

## Required Outcome
Establish a clean, testable, multi-tenant-ready application skeleton that future Growth OS modules can safely build on.

## Scope
- Create the initial FastAPI backend structure.
- Add application configuration/settings with environment-based configuration.
- Add a PostgreSQL-ready data layer and migration foundation.
- Define the initial tenant/workspace/site domain model without implementing complex business logic.
- Add health/readiness endpoints.
- Add local development setup and documented startup instructions.
- Add unit-test foundation and relevant initial tests.
- Add lint/type-check configuration.
- Add CI for the selected Python application stack.
- Preserve the existing Project Brain documentation and safety contract.
- Work on a new task branch and finish through a draft pull request.

## Architectural Constraints
- Follow `AGENTS.md`, `docs/PRODUCT.md`, `docs/GOALS.md`, `docs/ARCHITECTURE.md`, `docs/V1-SCOPE.md`, and `docs/DECISIONS.md`.
- FastAPI/Python is the preferred core backend for this task.
- PostgreSQL is the operational source-of-truth target.
- Do not introduce n8n, Temporal, pgvector, OpenAI Agents SDK, MagicAI, Dograh, MiroFish, Antigravity, or other optional toolbox components unless required for a minimal interface boundary; these are not part of this foundation task.
- Do not build the frontend yet unless a minimal non-product scaffold is strictly required by tooling.
- Do not deploy anything to production.
- Do not add real production secrets or credentials.
- Do not implement autonomous external side effects.

## Initial Domain Model
Design the minimum clean foundation for:
- Tenant / Workspace
- User membership / role boundary (domain model only; no auth redesign)
- Website / Site
- Connector status placeholder/interface
- Audit timestamps / identifiers

The implementation must be multi-tenant-aware from the beginning and avoid cross-tenant access patterns.

## Acceptance Criteria
- A documented FastAPI application starts locally.
- `GET /health` returns a successful liveness response.
- A readiness endpoint exists and distinguishes application readiness from simple liveness.
- Configuration is environment-driven and secrets are not committed.
- PostgreSQL-compatible persistence foundation exists with migrations.
- Initial tenant/workspace/site models are defined with clear tenant ownership boundaries.
- Tests cover health/readiness and at least the core tenant-boundary model behavior that can be validated at this stage.
- Lint and type checks are configured and pass.
- CI runs relevant tests/checks on pull requests.
- No production deployment workflow is added.
- No product-specific autonomous agents or marketing functionality are implemented.
- Existing architecture/source-of-truth documentation is not silently rewritten.
- `git diff --check` passes.
- Work is delivered as a draft PR from a new branch, not by committing implementation directly to `main`.

## Stop / Approval Conditions
Stop and request approval if implementation would require:
- changing the agreed high-level architecture
- authentication redesign
- billing changes
- destructive database changes
- weakening tenant isolation
- production infrastructure
- production credentials/secrets
- production deployment
- high-risk irreversible actions

## Completion Output
Codex must report:
- branch name
- files changed
- architecture choices made within this task
- commands/checks executed and their results
- acceptance-criteria status
- risks and limitations
- migration/rollback notes
- draft PR reference
