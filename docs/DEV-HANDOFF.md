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
controller may run at a time. The operating-system file lock is authoritative: contention rejects
a second controller, while stale PID text in an unlocked file is replaced safely even if that PID
has since been reused by an unrelated process.

Active Codex children have a 30-minute inactivity limit. Prompt delivery uses monitored
nonblocking pipe writes, so a child that stops reading stdin cannot evade the deadline. Each
output event resets the in-memory liveness deadline, while lightweight durable heartbeat writes
are rate-limited. Potentially expensive recovery hashing runs only at child lifecycle boundaries,
after the child has stopped, so it cannot block stdout draining or defeat the inactivity limit. A
hard controller crash records the launch base; startup captures the final scope only after proving
the instrumented child process group is gone and the task `HEAD` is unchanged, but does not treat
post-crash content as child-owned without explicit `--confirm-recovery` authorization.
Every child runs in an isolated process group; at the limit the controller terminates the whole
group, waits 10 seconds, then kills the group if
necessary before capturing recovery scope. This bounds hangs and prevents orphaned descendant
commands from continuing to mutate the workspace. After either signal it checks the group itself,
not merely the leader, and refuses to snapshot until group disappearance is proven. The status
record includes the process-group
identity (group ID plus OS start time, stable across the launch-gate `exec`) and timeout; after a
controller crash, a still-live child is terminated only when that
identity matches and its heartbeat is stale. The recorded process group is checked independently
of the leader PID. A live group whose recorded leader is dead is not safe to signal because its
numeric group ID may have been reused, so the controller durably records `RECOVERY_BLOCKED` and
stops before workspace inspection. A later startup retries safely if the group disappears.
Missing or mismatched provenance fails closed.
When `--watch` restarts while a fully proven orphan is still inside its output-inactivity window,
it keeps the controller lock and rechecks at the bounded poll interval instead of exiting. Once the
heartbeat becomes stale, normal group termination and recovery proceed.
Status checkpoints are written to a same-directory temporary file, flushed, and atomically
replaced so a crash cannot turn the only recovery record into partial JSON.
New children start behind a one-byte launch gate: the wrapper cannot execute Codex until its PID,
process-group identity, heartbeat, timeout, and base `HEAD` are durable. Controller death before
that checkpoint closes the pipe, causing the wrapper to exit without executing the task command.
After task context is known, reconciliation errors durably move stale active states to
`RECOVERY_BLOCKED`; branch or issue drift therefore cannot leave a dead child recorded forever as
`IMPLEMENTING`.

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

On every `--once` startup and `--watch` cycle, the controller reconciles an `IMPLEMENTING`,
`FIXING`, or `RECOVERABLE_CHANGES` status before requiring a clean tree or selecting another
issue. If the recorded workspace-write Codex PID is dead and the exact recorded task branch still
contains changes and a final boundary snapshot exists, status becomes `RECOVERABLE_CHANGES`. For a
hard controller death without that snapshot, startup proves that the recorded process group is
gone, the exact task branch is checked out, and its launch `HEAD` is unchanged, then records
`RECOVERY_CONFIRMATION_REQUIRED`. The controller does not infer that current content is child-owned;
an operator must run `python3 devtools/codex_handoff.py --confirm-recovery` to authorize and hash
the current scope. Before recovery stages anything, the controller requires both the current
paths and content digest to match that child-captured snapshot exactly, including rejection of
same-path edits made after the child stopped. Legacy/pre-heartbeat status without a child-captured
content manifest remains preserved at `RECOVERABLE_CHANGES`, but automatic recovery stops for
explicit operator confirmation because branch and issue identity cannot prove who created each
dirty file. Only the explicit confirmation command may turn the current tree into authorized scope.
With a proven manifest, it runs the full verification suite and continues without rerunning
implementation or a review-fix round. Verification and finalization failures never replace that
trusted manifest with a fresh snapshot; any files created or mutated by a failing gate therefore
cause the next recovery validation to stop instead of being staged. Recovery validates the same
manifest again after successful gates and immediately before staging, so gate side effects cannot
expand the committed scope either. Recovery from committed checkpoints likewise requires the tree
to remain clean after verification and before any push, PR, or review side effect.

Commit, push, and draft-PR creation are persisted as explicit finalization checkpoints. Before
staging, the controller records the current `HEAD`, exact changed paths, and a content-only digest.
That digest permits only the expected index transition if interruption occurs between `git add`
and `git commit`; path, base `HEAD`, or working-tree content changes still fail closed. After
staging, the expected Git tree is checkpointed before commit. If the controller dies after Git
creates the commit but before the next status write, startup accepts only an exact one-commit
advance with the expected parent, bounded task subject, and tree. Restarted recovery verifies the
local commit, remote task-branch head, and draft PR head as applicable before it executes any
repository verification command or GitHub mutation. It then retries the idempotent branch push
when needed and discovers the branch's unique open draft PR before attempting creation. A
transient failure after commit, push, PR creation, or during the independent reviewer therefore
resumes from the completed checkpoint instead of trying to create another commit or PR.
Review-fix commits use the same pre-staging content and pre-commit `HEAD` checkpoints, including
an exact bounded review-round commit subject, so either adjacent crash window is recoverable.
Recovery audit comments carry stable hidden event markers and are queried before posting, keeping
retries idempotent even if a prior attempt stopped immediately after GitHub accepted a comment.

Recovery fails closed when the PID is still live or branch/task identity cannot be proven. A dead
child with no changes is a clean `FAILED` run, and the controller publishes that terminal state to
the proven owner-authored GitHub issue before stopping. Verification or finalization failure keeps
status at `RECOVERABLE_CHANGES`, preserves the task branch and files, releases the controller lock,
and prevents another issue from starting. Recovery never auto-merges; its reviewed draft PR
remains open for human handling. Starting a new task and starting a workspace-write fix round clear
prior task/finalization recovery checkpoints so a later child failure cannot inherit another task
or an already-completed phase.

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

Press Ctrl-C to stop watch mode. If Codex is active, the controller first terminates and reaps its
entire isolated process group. Changed files are recorded as `RECOVERABLE_CHANGES`; otherwise the
interruption is recorded as an issue failure. An idle interruption records `STOPPED`, and every
path releases the controller lock so the queue cannot advance silently. Remove `codex-ready` from
queued issues to prevent them from starting on the next run. The controller never deploys.
