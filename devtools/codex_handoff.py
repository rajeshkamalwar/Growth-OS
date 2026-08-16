#!/usr/bin/env python3
"""Local GitHub -> Codex -> draft PR handoff controller.

Safety properties:
- Processes only open issues labeled `codex-ready`.
- Only accepts issues authored by the configured repository owner.
- Requires a clean working tree.
- Runs one task at a time using a lock file.
- Uses workspace-write for implementation/fixes and read-only for independent review.
- Runs trusted local verification after implementation and every fix round.
- Creates a task branch, commits, pushes, and a reviewed draft PR.
- Never merges or deploys.
- Writes runtime status/logs under `.git` so monitoring never dirties the repository.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO, TypedDict, cast

REPO = os.environ.get("GROWTH_OS_REPO", "rajeshkamalwar/Growth-OS")
OWNER = os.environ.get("GROWTH_OS_OWNER", "rajeshkamalwar")
READY_LABEL = "codex-ready"
RUNNING_LABEL = "codex-running"
DONE_LABEL = "codex-pr-open"
REVIEWED_LABEL = "codex-review-passed"
FAILED_LABEL = "codex-failed"
LOCK_FILE = Path(".git/codex-handoff.lock")
STATUS_FILE = Path(".git/codex-handoff-status.json")
LOG_DIR = Path(".git/codex-handoff-logs")
REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_SCHEMA_SOURCE = REPO_ROOT / "devtools" / "codex-review.schema.json"
REVIEW_SCHEMA_RUNTIME = Path(".git/codex-handoff-review.schema.json")
TRUSTED_REVIEW_SCHEMA = REVIEW_SCHEMA_SOURCE.read_text(encoding="utf-8")
DEFAULT_POLL_INTERVAL = 60
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 3600
MAX_FIX_ROUNDS = 2
MAX_REVIEW_RESULT_BYTES = 65_536
MAX_REVIEW_FINDINGS = 20
LOCAL_DATABASE_URL = "postgresql+asyncpg://growth_os:growth_os@localhost:5432/growth_os"
VERIFICATION_COMMANDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Ruff lint", (".venv/bin/python", "-m", "ruff", "check", ".")),
    ("Ruff format", (".venv/bin/python", "-m", "ruff", "format", "--check", ".")),
    ("strict mypy", (".venv/bin/python", "-m", "mypy")),
    ("pytest", (".venv/bin/python", "-m", "pytest")),
    ("pip-audit", (".venv/bin/python", "-m", "pip_audit")),
    (
        "Alembic upgrade SQL",
        (".venv/bin/python", "-m", "alembic", "upgrade", "head", "--sql"),
    ),
    (
        "Alembic downgrade SQL",
        (".venv/bin/python", "-m", "alembic", "downgrade", "head:base", "--sql"),
    ),
    ("git diff validation", ("git", "diff", "--check")),
)
_LOCK_HANDLE: TextIO | None = None


class IssueAuthor(TypedDict):
    login: str


class RequiredIssue(TypedDict):
    number: int
    title: str


class Issue(RequiredIssue, total=False):
    body: str | None
    author: IssueAuthor | None
    url: str


class StatusContext(TypedDict):
    issue: int
    title: str
    branch: str
    started_at: str


class ReviewFinding(TypedDict):
    priority: str
    title: str
    detail: str
    path: str | None
    line: int | None


class ReviewResult(TypedDict):
    verdict: str
    summary: str
    findings: list[ReviewFinding]


def now_iso() -> str:
    # timezone.utc keeps this standalone controller compatible with the documented Python 3.9.
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017


def run(
    *args: str,
    input_text: str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def gh_json(*args: str) -> Any:
    result = run("gh", *args)
    return json.loads(result.stdout or "null")


def ensure_tools() -> None:
    for command in ("git", "gh", "codex"):
        result = subprocess.run(["which", command], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Required command not found: {command}")
    if not Path(".venv/bin/python").is_file():
        raise RuntimeError(
            "Required verification environment not found: .venv/bin/python. "
            "Install the repository dev dependencies before running the controller."
        )
    run("gh", "auth", "status")


def ensure_labels() -> None:
    labels = {
        READY_LABEL: "Ready for local Codex execution",
        RUNNING_LABEL: "Currently running in local Codex controller",
        DONE_LABEL: "Codex opened a draft PR",
        REVIEWED_LABEL: "Independent Codex review passed with zero findings",
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


def run_codex_stream(
    prompt: str,
    log_file: Path,
    status_context: StatusContext,
    *,
    command: tuple[str, ...] = ("codex", "exec", "--sandbox", "workspace-write"),
    state: str = "IMPLEMENTING",
    env: dict[str, str] | None = None,
) -> tuple[int, str]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tail: list[str] = []
    with log_file.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        write_status(state, codex_pid=process.pid, log_file=log_file, **status_context)
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


def _review_result_error(detail: str) -> RuntimeError:
    return RuntimeError(f"Invalid review result: {detail}")


def load_review_result(result_file: Path) -> ReviewResult:
    """Load and defensively validate the reviewer's untrusted final response."""
    try:
        size = result_file.stat().st_size
    except OSError as exc:
        raise _review_result_error("result file is missing or unreadable") from exc
    if size > MAX_REVIEW_RESULT_BYTES:
        raise _review_result_error("review result is too large")
    try:
        payload = json.loads(result_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise _review_result_error("result is not valid UTF-8 JSON") from exc

    if not isinstance(payload, dict) or set(payload) != {"verdict", "summary", "findings"}:
        raise _review_result_error("top-level fields do not match the contract")
    verdict = payload["verdict"]
    summary = payload["summary"]
    findings = payload["findings"]
    if not isinstance(verdict, str) or verdict not in {"pass", "changes_requested"}:
        raise _review_result_error("verdict is not allowed")
    if not isinstance(summary, str) or not 1 <= len(summary) <= 2000:
        raise _review_result_error("summary length is invalid")
    if not isinstance(findings, list) or len(findings) > MAX_REVIEW_FINDINGS:
        raise _review_result_error("findings must be a bounded list")

    validated_findings: list[ReviewFinding] = []
    expected_fields = {"priority", "title", "detail", "path", "line"}
    for candidate in findings:
        if not isinstance(candidate, dict) or set(candidate) != expected_fields:
            raise _review_result_error("finding fields do not match the contract")
        priority = candidate["priority"]
        title = candidate["title"]
        detail = candidate["detail"]
        path = candidate["path"]
        line = candidate["line"]
        if not isinstance(priority, str) or priority not in {"P0", "P1", "P2", "P3"}:
            raise _review_result_error("finding priority is not allowed")
        if not isinstance(title, str) or not 1 <= len(title) <= 200:
            raise _review_result_error("finding title length is invalid")
        if not isinstance(detail, str) or not 1 <= len(detail) <= 2000:
            raise _review_result_error("finding detail length is invalid")
        if path is not None and (not isinstance(path, str) or not 1 <= len(path) <= 500):
            raise _review_result_error("finding path is invalid")
        if line is not None and (type(line) is not int or not 1 <= line <= 1_000_000):
            raise _review_result_error("finding line is invalid")
        validated_findings.append(
            {
                "priority": priority,
                "title": title,
                "detail": detail,
                "path": path,
                "line": line,
            }
        )

    if verdict == "pass" and validated_findings:
        raise _review_result_error("pass verdict cannot contain findings")
    if verdict == "changes_requested" and not validated_findings:
        raise _review_result_error("changes_requested verdict requires findings")
    return {"verdict": verdict, "summary": summary, "findings": validated_findings}


def run_verification(issue: Issue, status_context: StatusContext, pass_number: int) -> None:
    """Run the trusted, shell-free local quality gate set."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"verify-{issue['number']}-{pass_number}.log"
    write_status(
        "VERIFYING",
        log_file=log_file,
        detail=f"Running local verification pass {pass_number}",
        **status_context,
    )
    environment = os.environ.copy()
    environment["GROWTH_OS_DATABASE_URL"] = LOCAL_DATABASE_URL
    with log_file.open("w", encoding="utf-8") as log:
        for name, command in VERIFICATION_COMMANDS:
            log.write(f"$ {json.dumps(command)}\n")
            result = run(*command, check=False, env=environment)
            log.write(result.stdout)
            log.write(result.stderr)
            log.flush()
            if result.returncode != 0:
                raise RuntimeError(
                    f"Local verification failed during {name} with exit code "
                    f"{result.returncode}. See {log_file}."
                )


def run_reviewer(issue: Issue, status_context: StatusContext, review_round: int) -> ReviewResult:
    """Run an independent read-only reviewer and validate its structured result."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_SCHEMA_RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_SCHEMA_RUNTIME.write_text(TRUSTED_REVIEW_SCHEMA, encoding="utf-8")
    log_file = LOG_DIR / f"review-{issue['number']}-{review_round}.log"
    review_temp = Path(
        tempfile.mkdtemp(prefix=f"review-{issue['number']}-{review_round}-", dir=LOG_DIR.resolve())
    )
    result_file = review_temp / "result.json"
    prompt = f"""Review this task branch against origin/main and the issue contract below.

Issue #{issue["number"]}: {issue["title"]}

{issue.get("body") or ""}

Review only for actionable acceptance, correctness, security, race, data-integrity, test, or
scope defects. Do not report optional style suggestions. Inspect the actual diff and relevant
repository rules. Return `pass` with zero findings only when no actionable defect remains;
otherwise return `changes_requested` with precise findings. Do not modify any repository file
or rerun the full local gate suite; the controller runs those gates separately.
"""
    command = (
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--add-dir",
        str(review_temp),
        "--output-schema",
        str(REVIEW_SCHEMA_RUNTIME),
        "--output-last-message",
        str(result_file),
        "-",
    )
    environment = os.environ.copy()
    environment["TMPDIR"] = str(review_temp)
    try:
        return_code, output_tail = run_codex_stream(
            prompt,
            log_file,
            status_context,
            command=command,
            state="REVIEWING",
            env=environment,
        )
        if return_code != 0:
            raise RuntimeError(f"Reviewer exited with {return_code}:\n{output_tail[-3000:]}")
        return load_review_result(result_file)
    finally:
        shutil.rmtree(review_temp, ignore_errors=True)


def run_fixer(
    issue: Issue,
    findings: list[ReviewFinding],
    status_context: StatusContext,
    fix_round: int,
) -> None:
    """Apply only validated reviewer findings in the existing task branch."""
    log_file = LOG_DIR / f"fix-{issue['number']}-{fix_round}.log"
    prompt = f"""Address validated review findings for issue #{issue["number"]}: {issue["title"]}.

Original issue contract:
{issue.get("body") or ""}

Validated findings:
{json.dumps(findings, indent=2)}

Fix every finding completely and minimally. Obey AGENTS.md. Stay within the original issue
scope. Do not commit, push, merge, deploy, or perform external actions. Leave only justified
repository changes for the controller to verify.
"""
    return_code, output_tail = run_codex_stream(prompt, log_file, status_context, state="FIXING")
    if return_code != 0:
        raise RuntimeError(f"Fixer exited with {return_code}:\n{output_tail[-3000:]}")
    if not run("git", "status", "--porcelain").stdout.strip():
        raise RuntimeError("Reviewer fixer produced no changes")


def commit_review_fix(issue: Issue, fix_round: int) -> None:
    run("git", "add", "-A")
    run("git", "commit", "-m", f"codex: address review round {fix_round} for #{issue['number']}")
    run("git", "push")


def mark_pr_review_passed(pr_url: str) -> None:
    """Add the machine-readable review-passed marker to the draft PR."""
    run("gh", "pr", "edit", pr_url, "--repo", REPO, "--add-label", REVIEWED_LABEL)


def run_review_fix_loop(issue: Issue, status_context: StatusContext) -> ReviewResult:
    """Review, fix, and reverify with a strict two-fix upper bound."""
    for review_round in range(1, MAX_FIX_ROUNDS + 2):
        result = run_reviewer(issue, status_context, review_round)
        if result["verdict"] == "pass":
            return result
        if review_round > MAX_FIX_ROUNDS:
            raise RuntimeError("Reviewer still found defects after two fix rounds")
        run_fixer(issue, result["findings"], status_context, review_round)
        run_verification(issue, status_context, review_round + 1)
        commit_review_fix(issue, review_round)
    raise AssertionError("unreachable review loop state")


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

    run_verification(issue, status_context, 1)

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
    comment(number, f"Codex opened a draft PR for independent review: {pr_url}")
    run_review_fix_loop(issue, status_context)
    mark_pr_review_passed(pr_url)
    write_status(
        "REVIEW_PASSED",
        detail="Independent review passed with zero findings",
        pr_url=pr_url,
        **status_context,
    )
    comment(number, f"Independent review passed with zero findings: {pr_url}")
    label(number, add=REVIEWED_LABEL)
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
