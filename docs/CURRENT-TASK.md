# Current Task

## Task ID
FOUNDATION-006 (GitHub issue #16)

## Authorization
Add deterministic local verification and an independent reviewer/fix loop to the persistent
development controller.

## Goal
Move each implemented task from unreviewed draft PR to a verified, independently reviewed draft
PR without making the user relay findings between agents.

## Required Outcome
- The controller runs the complete repository gate set after implementation and each fix.
- A fresh read-only reviewer returns a bounded, schema-constrained result that is also validated
  defensively by the controller.
- Actionable findings trigger at most two workspace-write fixer rounds, each followed by full
  verification, commit, push, and another independent review.
- Invalid review output, failed verification, no-change fixes, and exhausted rounds fail closed.
- Only a zero-finding review marks the draft PR and issue review-passed.

## Constraints
- Do not install or configure an operating-system service.
- Do not implement automatic merge or merge-policy evaluation in this milestone.
- Do not change authentication, tenant isolation, billing, production infrastructure, or
  deployment behavior.
- Do not perform product or customer-facing external actions.
- Follow `AGENTS.md` and the repository source-of-truth documents.

## Completion Gates
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and
  `git diff --check` pass where available.
- Controller behavior has deterministic tests covering clean review, fix/reverify/review,
  malformed output, failed verification, no-change fixes, and loop exhaustion.
- Existing application APIs remain intact.
- Work is delivered from a task branch through a draft pull request.
