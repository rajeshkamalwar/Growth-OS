# Local Codex Handoff

## Purpose
Remove manual copy/paste between ChatGPT and Codex without depending on paid GitHub Actions.

The flow is:

`ChatGPT -> GitHub issue -> local controller on your Mac -> Codex CLI -> branch -> draft PR -> GitHub -> ChatGPT review`

## One-time prerequisites

1. Clone the repository on the Mac that will run Codex.
2. Install and authenticate GitHub CLI (`gh`).
3. Install and authenticate Codex CLI.
4. Keep the repository checkout clean when the controller runs.

The controller uses the repository's existing `AGENTS.md` safety contract. This milestone
creates draft PRs but does not review, merge, or deploy them.

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
5. Codex implements and tests locally.
6. The controller commits and pushes the result.
7. The controller opens a draft PR and posts the PR link back to the issue.
8. The issue receives `codex-pr-open`.
9. ChatGPT can inspect the PR directly through GitHub.
10. Review and merge automation is a separate milestone; this controller stops at a draft PR.

## Safety rules

- No automatic review or merge in the current controller.
- No automatic production deployment.
- Only issues explicitly labeled `codex-ready` run.
- Only the configured repository owner's issues are accepted.
- Dirty working trees are rejected.
- Only one task runs at a time.
- Codex runs in workspace-write sandbox mode.
- `AGENTS.md` remains authoritative.
- Approval-gated architecture/auth/billing/tenant/destructive changes remain blocked.

## Emergency stop

Press Ctrl-C to stop watch mode. The controller records `STOPPED` status and releases its lock.
If Codex is actively processing an issue, the interruption is also recorded as an issue failure
so the queue cannot advance silently. Remove `codex-ready` from queued issues to prevent them
from starting on the next run. The current controller never merges or deploys.
