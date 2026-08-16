# Current Task

## Task ID
FOUNDATION-001

## Goal
Create the initial repository foundation for the Autonomous Growth OS and establish the zero-copy-paste ChatGPT -> Project Brain -> Codex workflow.

## Scope
- Install project documentation and `AGENTS.md`.
- Establish task/plan conventions.
- Configure branch/PR-first development.
- Add CI placeholders/checklist when application stack is selected.
- Do not implement the Growth OS application itself yet.

## Acceptance Criteria
- `AGENTS.md` exists and defines safety/working rules.
- Product, goals, architecture, scope, and decisions are versioned.
- A plan template exists.
- A task/PR template exists.
- Codex can be instructed with: `Read AGENTS.md and execute docs/CURRENT-TASK.md.`
- No direct production deployment exists.
- Work is completed through a draft PR.

## Stop / Approval Conditions
Stop and request approval for destructive database changes, authentication redesign, billing changes, tenant-boundary changes, secrets, production infrastructure, or production deployment.

## Completion Output
Return files changed, checks executed, acceptance criteria status, risks/limitations, rollback notes, and draft PR reference.
