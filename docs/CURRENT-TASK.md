# Current Task

## Task ID
FOUNDATION-007 (GitHub issue #18)

## Authorization
Add deterministic enforcement of the bounded development auto-merge policy.

## Goal
Allow the local controller to squash-merge an eligible verified and independently reviewed PR
without user relay, while leaving every ambiguous or forbidden PR open for human handling.

## Required Outcome
- A strict owner-authored assessment opts a task into merge evaluation.
- Only roadmap-authorized, reversible low/medium-risk work with no deployment, external side
  effect, stop category, or protected path may proceed.
- GitHub metadata, the exact reviewed head, mergeability, review state, and unresolved threads
  are checked immediately before merge.
- Eligible PRs are made ready and squash-merged with an exact-head guard and no bypass flags.
- Ineligible PRs remain open and record an auditable non-failure blocked result.

## Constraints
- Do not deploy, bypass branch protection, force-push, or use admin merge.
- Do not change authentication, tenant isolation, billing, secrets, destructive migrations,
  production infrastructure, websites, external accounts, outreach, publishing, or spending.
- Do not change product runtime behavior or install an operating-system service.
- Preserve all existing implementation, verification, review/fix, lock, and failure controls.

## Completion Gates
- Deterministic tests cover assessment parsing, every policy stop class, exact-head PR validation,
  unresolved review state, blocked handoff, and guarded merge.
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and
  `git diff --check` pass.
- A separate read-only reviewer reports zero blocking findings.
- Work is delivered from a dedicated task branch through a pull request.
