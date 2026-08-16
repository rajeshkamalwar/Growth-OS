#!/usr/bin/env python3
"""Local GitHub -> Codex -> draft PR handoff controller.

Safety properties:
- Processes only open issues labeled `codex-ready`.
- Only accepts issues authored by the configured repository owner.
- Requires a clean working tree.
- Runs one task at a time using a lock file.
- Uses `codex exec --sandbox workspace-write`.
- Creates a task branch, commit, push, and draft PR.
- Never merges or deploys.
- Writes runtime status/logs under `.git` so monitoring never dirties the repository.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, TextIO, TypedDict, cast

REPO = os.environ.get("GROWTH_OS_REPO", "rajeshkamalwar/Growth-OS")
OWNER = os.environ.get("GROWTH_OS_OWNER", "rajeshkamalwar")
READY_LABEL = "codex-ready"
RUNNING_LABEL = "codex-running"
DONE_LABEL = "codex-pr-open"
FAILED_LABEL = "codex-failed"
LOCK_FILE = Path(".git/codex-handoff.lock")
STATUS_FILE = Path(".git/codex-handoff-status.json")
LOG_DIR = Path(".git/codex-handoff-logs")
DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 3600
_LOCK_HANDLE: TextIO | None = None


class IssueAuthor(TypedDict):
    login: str


class Issue(TypedDict):
    number: int
    title: str
    body: NotRequired[str | None]
    author: NotRequired[IssueAuthor | None]
    url: NotRequired[str]


class StatusContext(TypedDict):
    issue: int
    title: str
    branch: str
    started_at: str


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def run(
    *args: str, input_text: str | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def gh_json(*args: str) -> Any:
    result = run("gh", *args)
    return json.loads(result.stdout or "null")


def ensure_tools() -> None:
    for command in ("git", "gh", "codex"):
        result = subprocess.run(["which", command], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Required command not found: {command}")
    run("gh", "auth", "status")


def ensure_labels() -> None:
    labels = {
        READY_LABEL: "Ready for local Codex execution",
        RUNNING_LABEL: "Currently running in local Codex controller",
        DONE_LABEL: "Codex opened a draft PR",
        FAILED_LABEL: "Codex handoff failed",
    }
    for name, description in labels.items():
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                name,
                "--repo",
                REPO,
                "--description",
                description,
                "--force",
            ],
            capture_output=True,
            text=True,
        )


def clean_tree_required() -> None:
    status = run("git", "status", "--porcelain").stdout.strip()
    if status:
        raise RuntimeError(
            "Working tree is not clean. Commit/stash changes before running the controller."
        )


def poll_interval(value: str) -> int:
    """Parse a bounded polling interval from CLI or environment input."""
    try:
        interval = int(value)
    except ValueError as exc:
        raise ValueError("poll interval must be an integer number of seconds") from exc
    if not MIN_POLL_INTERVAL <= interval <= MAX_POLL_INTERVAL:
        raise ValueError(
            f"poll interval must be between {MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL} seconds"
        )
    return interval


def pid_is_running(pid: int) -> bool:
    """Return whether a PID exists without sending it a signal."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_lock() -> None:
    """Acquire the single-controller lock, recovering stale lock files."""
    global _LOCK_HANDLE
    if _LOCK_HANDLE is not None:
        raise RuntimeError("Controller lock is already held by this process")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK_FILE.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.seek(0)
        owner = lock.read().strip() or "unknown"
        lock.close()
        raise RuntimeError(f"Controller lock held by active controller PID {owner}") from None

    lock.seek(0)
    try:
        existing_pid = int(lock.read().strip())
    except ValueError:
        existing_pid = -1
    if existing_pid != os.getpid() and pid_is_running(existing_pid):
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
        raise RuntimeError(f"Controller lock held by active controller PID {existing_pid}")

    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    os.fchmod(lock.fileno(), 0o600)
    _LOCK_HANDLE = lock


def release_lock() -> None:
    global _LOCK_HANDLE
    if _LOCK_HANDLE is None:
        return
    try:
        LOCK_FILE.unlink(missing_ok=True)
    finally:
        fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_UN)
        _LOCK_HANDLE.close()
        _LOCK_HANDLE = None


def write_status(
    state: str,
    *,
    issue: int | None = None,
    title: str | None = None,
    branch: str | None = None,
    log_file: Path | None = None,
    started_at: str | None = None,
    detail: str | None = None,
    codex_pid: int | None = None,
    pr_url: str | None = None,
) -> None:
    previous: dict[str, object] = {}
    if STATUS_FILE.exists():
        try:
            previous = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}
    payload = {
        "state": state,
        "issue": issue if issue is not None else previous.get("issue"),
        "title": title if title is not None else previous.get("title"),
        "branch": branch if branch is not None else previous.get("branch"),
        "started_at": started_at if started_at is not None else previous.get("started_at"),
        "updated_at": now_iso(),
        "controller_pid": os.getpid(),
        "codex_pid": codex_pid,
        "log_file": str(log_file) if log_file else previous.get("log_file"),
        "detail": detail,
        "pr_url": pr_url if pr_url is not None else previous.get("pr_url"),
    }
    STATUS_FILE.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def show_status() -> int:
    if not STATUS_FILE.exists():
        print("No handoff status has been recorded yet.")
        return 0
    data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    print(f"State: {data.get('state', 'UNKNOWN')}")
    if data.get("issue"):
        print(f"Issue: #{data['issue']} — {data.get('title', '')}")
    if data.get("branch"):
        print(f"Branch: {data['branch']}")
    if data.get("started_at"):
        print(f"Started: {data['started_at']}")
    if data.get("updated_at"):
        print(f"Last update: {data['updated_at']}")
    if data.get("codex_pid"):
        print(f"Codex PID: {data['codex_pid']}")
    if data.get("pr_url"):
        print(f"PR: {data['pr_url']}")
    if data.get("detail"):
        print(f"Detail: {data['detail']}")
    if data.get("log_file"):
        print(f"Log: {data['log_file']}")
        print(f"Watch: tail -f {data['log_file']}")
    return 0


def next_issue() -> Issue | None:
    issues = gh_json(
        "issue",
        "list",
        "--repo",
        REPO,
        "--state",
        "open",
        "--label",
        READY_LABEL,
        "--limit",
        "1",
        "--json",
        "number,title,body,author,url",
    )
    if not isinstance(issues, list) or not issues:
        return None
    issue = cast(Issue, issues[0])
    author_data = issue.get("author")
    author = (author_data.get("login") if author_data else "").lower()
    if author != OWNER.lower():
        raise RuntimeError(f"Refusing issue #{issue['number']}: author {author!r} is not {OWNER!r}")
    return issue


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:48] or "task").rstrip("-")


def label(issue_number: int, add: str | None = None, remove: str | None = None) -> None:
    if add:
        run("gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-label", add)
    if remove:
        subprocess.run(
            ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--remove-label", remove],
            capture_output=True,
            text=True,
        )


def comment(issue_number: int, text: str) -> None:
    run("gh", "issue", "comment", str(issue_number), "--repo", REPO, "--body", text)


def prepare_task_branch(branch: str) -> None:
    run("git", "fetch", "origin", "main")
    run("git", "checkout", "main")
    run("git", "pull", "--ff-only", "origin", "main")

    local_branch = run("git", "branch", "--list", branch).stdout.strip()
    if local_branch:
        run("git", "branch", "-D", branch)

    remote_branch = run("git", "ls-remote", "--heads", "origin", branch).stdout.strip()
    if remote_branch:
        raise RuntimeError(
            f"Remote task branch already exists: {branch}. Refusing to overwrite it automatically."
        )

    run("git", "checkout", "-b", branch)


def reset_noop_branch(branch: str) -> None:
    run("git", "checkout", "main")
    subprocess.run(["git", "branch", "-D", branch], capture_output=True, text=True)


def run_codex_stream(prompt: str, log_file: Path, status_context: StatusContext) -> tuple[int, str]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tail: list[str] = []
    with log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            ["codex", "exec", "--sandbox", "workspace-write"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        write_status("CODING", codex_pid=process.pid, log_file=log_file, **status_context)
        assert process.stdin is not None
        process.stdin.write(prompt)
        process.stdin.close()
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            tail.append(line)
            if len(tail) > 100:
                tail.pop(0)
        return_code = process.wait()
    return return_code, "".join(tail)


def process_issue(issue: Issue) -> None:
    number = int(issue["number"])
    title = issue["title"]
    body = issue.get("body") or ""
    branch = f"codex/issue-{number}-{slugify(title)}"
    started_at = now_iso()
    log_file = LOG_DIR / f"handoff-{number}.log"
    status_context: StatusContext = {
        "issue": number,
        "title": title,
        "branch": branch,
        "started_at": started_at,
    }

    write_status("SYNCING", log_file=log_file, detail="Preparing task branch", **status_context)
    label(number, add=RUNNING_LABEL, remove=READY_LABEL)
    comment(number, f"Local Codex controller started this task on branch `{branch}`.")
    prepare_task_branch(branch)

    prompt = f"""You are the implementation agent for this repository.

Before making changes, read AGENTS.md and every source-of-truth document it requires.
Then execute GitHub issue #{number}: {title}

The GitHub issue below is an implementation contract, not a suggestion.

Issue body:
{body}

Execution rules:
- Obey AGENTS.md and all repository safety gates.
- Inspect the current repository before deciding what work is needed.
- Implement the requested scope completely and minimally.
- Stay strictly within this issue's scope.
- Do not merge, deploy, modify production, or weaken safety controls.
- Run all relevant tests/checks before finishing.
- Leave the working tree containing only justified task changes.
- If the issue conflicts with source-of-truth docs or requires a stop/approval condition,
  stop and explain the exact conflict instead of bypassing it.
- Do NOT return a no-change result merely because related foundation code already exists.
- A no-change result is allowed only if every acceptance criterion in the issue is already
  satisfied by the current repository state. If you believe that is true, verify each criterion
  with concrete repository evidence and relevant commands/tests before concluding no changes
  are required.
- For implementation tasks, prefer making the necessary code/test/documentation changes over
  describing what could be changed.

Completion expectation:
Finish with a concise implementation summary covering files changed, architecture choices,
checks run and results, acceptance-criteria status, risks/limitations, and rollback notes.
"""

    return_code, output_tail = run_codex_stream(prompt, log_file, status_context)
    if return_code != 0:
        raise RuntimeError(f"Codex exited with {return_code}:\n{output_tail[-3000:]}")

    changed = run("git", "status", "--porcelain").stdout.strip()
    if not changed:
        reset_noop_branch(branch)
        raise RuntimeError(
            "Codex returned successfully but produced no repository changes for an "
            "implementation task. The controller treats this as a failed handoff so the task "
            "can be reviewed/requeued instead "
            "of being falsely marked complete.\n\n"
            f"Codex output:\n{output_tail[-3000:]}"
        )

    write_status(
        "COMMITTING", log_file=log_file, detail="Committing Codex changes", **status_context
    )
    run("git", "add", "-A")
    run("git", "commit", "-m", f"codex: resolve issue #{number}")

    write_status("PUSHING", log_file=log_file, detail="Pushing task branch", **status_context)
    run("git", "push", "-u", "origin", branch)

    pr_body = (
        f"Automated local Codex handoff for #{number}.\n\n"
        "This PR was created by the self-hosted controller. It is intentionally a draft. "
        "It must be reviewed before merge. No production deployment is authorized."
    )
    pr_url = run(
        "gh",
        "pr",
        "create",
        "--repo",
        REPO,
        "--base",
        "main",
        "--head",
        branch,
        "--draft",
        "--title",
        f"{title}",
        "--body",
        pr_body,
    ).stdout.strip()

    write_status(
        "PR_CREATED", log_file=log_file, detail="Draft PR opened", pr_url=pr_url, **status_context
    )
    comment(number, f"Codex completed and opened draft PR: {pr_url}")
    label(number, add=DONE_LABEL, remove=RUNNING_LABEL)


def record_issue_failure(issue: Issue, exc: BaseException) -> None:
    """Persist and publish a terminal failure for the selected issue."""
    number = int(issue["number"])
    detail = str(exc)[-1000:]
    write_status("FAILED", issue=number, title=issue.get("title"), detail=detail)
    label(number, add=FAILED_LABEL, remove=RUNNING_LABEL)
    comment(number, f"Local Codex controller failed:\n\n```text\n{str(exc)[-3000:]}\n```")


def run_once() -> int:
    ensure_tools()
    ensure_labels()
    clean_tree_required()
    acquire_lock()
    try:
        issue = next_issue()
        if issue is None:
            write_status("IDLE", detail="No codex-ready issues found")
            print("No codex-ready issues found.")
            return 0
        try:
            process_issue(issue)
            return 0
        except Exception as exc:
            record_issue_failure(issue, exc)
            raise
    finally:
        release_lock()


def run_watch(interval: int) -> int:
    """Continuously process ready issues until interrupted or a task fails."""
    ensure_tools()
    ensure_labels()
    acquire_lock()
    try:
        while True:
            clean_tree_required()
            issue = next_issue()
            if issue is None:
                write_status(
                    "IDLE", detail=f"Watching for codex-ready issues every {interval} seconds"
                )
                time.sleep(interval)
                continue
            try:
                process_issue(issue)
            except KeyboardInterrupt:
                record_issue_failure(
                    issue, RuntimeError("Controller interrupted during task processing")
                )
                raise
            except Exception as exc:
                record_issue_failure(issue, exc)
                raise
    except KeyboardInterrupt:
        write_status("STOPPED", detail="Controller stopped by operator")
        return 0
    finally:
        release_lock()


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--once", action="store_true", help="Process at most one ready issue and exit"
    )
    modes.add_argument("--watch", action="store_true", help="Continuously watch for ready issues")
    modes.add_argument("--status", action="store_true", help="Show the latest local handoff status")
    parser.add_argument(
        "--poll-interval",
        type=poll_interval,
        default=poll_interval(
            os.environ.get("GROWTH_OS_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL))
        ),
        metavar="SECONDS",
        help=f"Watch interval ({MIN_POLL_INTERVAL}-{MAX_POLL_INTERVAL}; default: %(default)s)",
    )
    args = parser.parse_args()

    if args.status:
        return show_status()
    if not args.once and not args.watch:
        print("Use --once, --watch, or --status.")
        return 2
    try:
        if args.watch:
            return run_watch(args.poll_interval)
        return run_once()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
