# Current Task

## Task ID
FOUNDATION-005 (GitHub issue #11)

## Authorization
Make the local development handoff controller persistently watch for authorized work.

## Goal
Extend `devtools/codex_handoff.py` with a bounded `--watch` mode while preserving `--once`
and `--status`.

## Required Outcome
- Watch mode polls continuously at a configurable interval bounded from 5 to 3600 seconds.
- Ctrl-C stops cleanly, records stopped status, and releases the controller lock.
- A live controller lock rejects a second controller; stale or malformed locks recover safely.
- A task failure is recorded and stops the controller before another issue is selected.
- Existing one-shot and status modes remain available.
- The bounded auto-merge policy is recorded, while reviewer/fix/merge automation remains a
  later milestone.

## Constraints
- Do not install or configure an operating-system service in this milestone.
- Do not implement automatic review or merge in this milestone.
- Do not change authentication, tenant isolation, billing, production infrastructure, or
  deployment behavior.
- Do not perform product or customer-facing external actions.
- Follow `AGENTS.md` and the repository source-of-truth documents.

## Completion Gates
- Ruff format/lint, strict mypy, pytest, pip-audit, migration validation, and
  `git diff --check` pass where available.
- Controller behavior has deterministic tests with subprocess, GitHub, and sleep boundaries
  mocked.
- Existing application APIs remain intact.
- Work is delivered from a task branch through a draft pull request.
