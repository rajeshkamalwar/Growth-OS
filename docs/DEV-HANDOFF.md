# Local Codex Handoff

## Purpose
Remove manual copy/paste between ChatGPT and Codex without depending on paid GitHub Actions.

The flow is:

`Goal -> GitHub issue -> local controller -> implement -> verify -> review/fix -> policy -> merge`

## One-time prerequisites

1. Clone the repository on the Mac that will run Codex.
2. Install and authenticate GitHub CLI (`gh`).
3. Install and authenticate Codex CLI.
4. Create the Python 3.12 verification environment:

   ```bash
   python3.12 -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

5. Keep the repository checkout clean when the controller runs.

The controller uses the repository's existing `AGENTS.md` safety contract. It creates draft
PRs, runs deterministic local gates, performs an independent read-only review, and may apply up
to two verified fix rounds. It may merge only when the strict bounded policy passes. It never
deploys.

## Install Codex CLI

```bash
npm install -g @openai/codex
codex --login
```

Verify:

```bash
codex --version
gh auth status
```

## Run one task

From the repository root:

```bash
python3 devtools/codex_handoff.py --once
```

## Run continuously

From the repository root:

```bash
python3 devtools/codex_handoff.py --watch
```

The default polling interval is 60 seconds. Set an explicit interval from 5 to 3600 seconds:

```bash
python3 devtools/codex_handoff.py --watch --poll-interval 30
```

`GROWTH_OS_POLL_INTERVAL` can supply the default when `--poll-interval` is omitted. Only one
controller may run at a time. A second controller rejects a live lock, while a lock left by a
dead process is recovered automatically.

Active Codex children have a 30-minute no-output limit. Each output event updates the status
heartbeat. At the limit the controller sends a graceful termination request, waits 10 seconds,
then kills the child if necessary. This bounds hangs without treating silence as success.

The controller looks for the oldest open issue labeled `codex-ready`.

It will only accept an issue authored by `rajeshkamalwar` by default. Override only intentionally:

```bash
export GROWTH_OS_OWNER=rajeshkamalwar
export GROWTH_OS_REPO=rajeshkamalwar/Growth-OS
```

## Task lifecycle

1. ChatGPT creates a GitHub issue containing the implementation contract.
2. The issue is explicitly marked `codex-ready`.
3. The local controller creates a branch from fresh `main`.
4. It passes the issue plus repository rules to `codex exec --sandbox workspace-write`.
5. Codex implements the issue in workspace-write mode.
6. The controller runs Ruff lint/format, strict mypy, pytest, pip-audit, offline Alembic
   upgrade/downgrade SQL, and `git diff --check` without a shell.
7. The controller commits, pushes, and opens a draft PR.
8. A fresh Codex reviewer inspects the branch against `origin/main` in read-only mode and
   returns a bounded structured result.
9. Findings trigger at most two workspace-write fix rounds. Every round is fully reverified,
   committed, pushed to the same draft PR, and reviewed again.
10. A zero-finding review records `REVIEW_PASSED` and applies `codex-pr-open`. Any invalid output,
    failed gate, no-change fix, or exhausted loop records failure and stops.
11. The controller parses exactly one `## Auto-merge assessment` JSON contract, applies trusted
    risk and protected-path checks, and validates the current PR, exact reviewed head, blocking
    reviews, and unresolved threads.
12. An eligible PR is marked ready and squash-merged with an exact-head guard. An ineligible or
    ambiguous PR records `MERGE_BLOCKED` and remains open for human handling.

## Interrupted-child recovery

On every `--once` startup and `--watch` cycle, the controller reconciles an `IMPLEMENTING` or
`RECOVERABLE_CHANGES` status before requiring a clean tree or selecting another issue. If the
recorded Codex PID is dead and the exact recorded task branch still contains changes, status
becomes `RECOVERABLE_CHANGES`. The controller then reloads the exact open, owner-authored GitHub
issue, runs the full verification suite, and continues with commit, push, draft-PR creation, and
independent review without rerunning implementation.

Recovery fails closed when the PID is still live or branch/task identity cannot be proven. A dead
child with no changes is a clean `FAILED` run. Verification or finalization failure keeps status
at `RECOVERABLE_CHANGES`, preserves the task branch and files, releases the controller lock, and
prevents another issue from starting. Recovery never auto-merges; its reviewed draft PR remains
open for human handling.

An issue opts into merge evaluation with exactly one assessment block:

````markdown
## Auto-merge assessment

```json
{
  "risk": "low",
  "roadmap_authorized": true,
  "reversible": true,
  "production_deployment": false,
  "external_customer_side_effect": false,
  "stop_categories": []
}
```
````

Use `low` or `medium` only. A missing/malformed block or any other value stops merge.

## Safety rules

- Automatic merge requires an explicit structured low/medium-risk assessment and every D-014
  and `AGENTS.md` condition to pass.
- No automatic production deployment.
- Only issues explicitly labeled `codex-ready` run.
- Only the configured repository owner's issues are accepted.
- Dirty working trees are rejected.
- Uncommitted task work is never discarded automatically.
- Only one task runs at a time.
- Codex runs in workspace-write sandbox mode.
- Review runs in a separate read-only Codex process.
- Reviewer output is size-bounded, schema-constrained, and validated before it reaches a fixer.
- The fix loop is capped at two rounds and every change must pass the full local gate set.
- Merge uses no admin, force, or branch-protection bypass flag and is pinned to the reviewed SHA.
- Missing policy data, protected paths, stale metadata, blocking reviews, or unresolved threads
  leave the reviewed PR open.
- `AGENTS.md` remains authoritative.
- Approval-gated architecture/auth/billing/tenant/destructive changes remain blocked.

## Emergency stop

Press Ctrl-C to stop watch mode. The controller records `STOPPED` status and releases its lock.
If Codex is actively processing an issue, the interruption is also recorded as an issue failure
so the queue cannot advance silently. Remove `codex-ready` from queued issues to prevent them
from starting on the next run. The controller never deploys.
