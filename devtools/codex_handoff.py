#!/usr/bin/env python3
"""Local GitHub -> Codex -> draft PR handoff controller.

Safety properties:
- Processes only open issues labeled `codex-ready`.
- Only accepts issues authored by the configured repository owner.
- Requires a clean working tree.
- Runs one task at a time using a lock file.
- Uses workspace-write for implementation/fixes and read-only for independent review.
- Runs trusted local verification after implementation and every fix round.
- Creates a task branch, commits, pushes, and a reviewed PR.
- May squash-merge only when the trusted bounded policy passes; never deploys.
- Writes runtime status/logs under `.git` so monitoring never dirties the repository.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import select
import shutil
import signal
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
MERGED_LABEL = "codex-merged"
MERGE_BLOCKED_LABEL = "codex-merge-blocked"
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
DEFAULT_CHILD_INACTIVITY_TIMEOUT = 1800
CHILD_TERMINATION_GRACE = 10.0
HEARTBEAT_CHECKPOINT_INTERVAL = 1.0
LAUNCH_GATE_SCRIPT = (
    "import os, sys; "
    "gate = int(sys.argv[1]); token = os.read(gate, 1); os.close(gate); "
    "sys.exit(125) if token != b'1' else os.execvpe(sys.argv[2], sys.argv[2:], os.environ)"
)
AUTO_MERGE_FIELDS = {
    "risk",
    "roadmap_authorized",
    "reversible",
    "production_deployment",
    "external_customer_side_effect",
    "stop_categories",
}
AUTO_MERGE_SECTION = re.compile(
    r"^## Auto-merge assessment[ \t]*\n+```json[ \t]*\n(.*?)\n```[ \t]*(?=\n+(?:## |\Z)|\Z)",
    re.MULTILINE | re.DOTALL,
)
PROTECTED_AUTO_MERGE_PATHS = {
    "agents.md",
    "docs/product.md",
    "docs/goals.md",
    "docs/architecture.md",
    "docs/v1-scope.md",
}
PROTECTED_AUTO_MERGE_PARTS = {
    ".github",
    "alembic",
    "auth",
    "authentication",
    "authorization",
    "billing",
    "credentials",
    "deploy",
    "deployment",
    "infra",
    "infrastructure",
    "outreach",
    "permissions",
    "secrets",
    "social",
    "tenant",
    "tenants",
    "terraform",
    "website",
}
PROTECTED_AUTO_MERGE_PREFIXES = (
    "acl",
    "auth",
    "backlink",
    "bill",
    "credential",
    "delete",
    "deploy",
    "email",
    "helm",
    "identity",
    "invoice",
    "k8s",
    "kubernetes",
    "mail",
    "migrat",
    "oauth",
    "outreach",
    "payment",
    "permission",
    "production",
    "publish",
    "pulumi",
    "rbac",
    "secret",
    "social",
    "stripe",
    "tenant",
    "terraform",
    "website",
)
PROTECTED_AUTO_MERGE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
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
    state: str


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


class AutoMergeAssessment(TypedDict):
    risk: str
    roadmap_authorized: bool
    reversible: bool
    production_deployment: bool
    external_customer_side_effect: bool
    stop_categories: list[str]


class MergeOutcome(TypedDict):
    merged: bool
    reasons: list[str]
    sha: str | None


class RecoverableChangesError(RuntimeError):
    """Recovery stopped while preserved task work remains unresolved."""


class ActiveOrphanError(RuntimeError):
    """A proven orphan is still within its bounded output-inactivity window."""


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
        MERGED_LABEL: "Codex merged an eligible reviewed development PR",
        MERGE_BLOCKED_LABEL: "Reviewed PR requires a human merge decision",
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
    last_child_output_at: str | None = None,
    pr_url: str | None = None,
    recoverable_paths: list[str] | None = None,
    recoverable_snapshot: str | None = None,
    recoverable_content_snapshot: str | None = None,
    finalization_checkpoint: str | None = None,
    commit_sha: str | None = None,
    pre_commit_sha: str | None = None,
    pending_commit_subject: str | None = None,
    recoverable_base_sha: str | None = None,
    pending_tree_sha: str | None = None,
    child_process_group: int | None = None,
    child_process_identity: str | None = None,
    child_inactivity_timeout: float | None = None,
    reset_recovery: bool = False,
) -> None:
    previous: dict[str, object] = {}
    if STATUS_FILE.exists():
        try:
            previous = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = {}
    recovery_previous = {} if reset_recovery else previous
    payload = {
        "state": state,
        "issue": issue if issue is not None else previous.get("issue"),
        "title": title if title is not None else previous.get("title"),
        "branch": branch if branch is not None else previous.get("branch"),
        "started_at": started_at if started_at is not None else previous.get("started_at"),
        "updated_at": now_iso(),
        "controller_pid": os.getpid(),
        "codex_pid": codex_pid,
        "last_child_output_at": (
            last_child_output_at
            if last_child_output_at is not None
            else recovery_previous.get("last_child_output_at")
        ),
        "log_file": str(log_file) if log_file else previous.get("log_file"),
        "detail": detail,
        "pr_url": pr_url if pr_url is not None else recovery_previous.get("pr_url"),
        "recoverable_paths": (
            recoverable_paths
            if recoverable_paths is not None
            else recovery_previous.get("recoverable_paths")
        ),
        "recoverable_snapshot": (
            recoverable_snapshot
            if recoverable_snapshot is not None
            else recovery_previous.get("recoverable_snapshot")
        ),
        "recoverable_content_snapshot": (
            recoverable_content_snapshot
            if recoverable_content_snapshot is not None
            else recovery_previous.get("recoverable_content_snapshot")
        ),
        "finalization_checkpoint": (
            finalization_checkpoint
            if finalization_checkpoint is not None
            else recovery_previous.get("finalization_checkpoint")
        ),
        "commit_sha": (
            commit_sha if commit_sha is not None else recovery_previous.get("commit_sha")
        ),
        "pre_commit_sha": (
            pre_commit_sha
            if pre_commit_sha is not None
            else recovery_previous.get("pre_commit_sha")
        ),
        "pending_commit_subject": (
            pending_commit_subject
            if pending_commit_subject is not None
            else recovery_previous.get("pending_commit_subject")
        ),
        "recoverable_base_sha": (
            recoverable_base_sha
            if recoverable_base_sha is not None
            else recovery_previous.get("recoverable_base_sha")
        ),
        "pending_tree_sha": (
            pending_tree_sha
            if pending_tree_sha is not None
            else recovery_previous.get("pending_tree_sha")
        ),
        "child_process_group": (
            child_process_group
            if child_process_group is not None
            else recovery_previous.get("child_process_group")
        ),
        "child_process_identity": (
            child_process_identity
            if child_process_identity is not None
            else recovery_previous.get("child_process_identity")
        ),
        "child_inactivity_timeout": (
            child_inactivity_timeout
            if child_inactivity_timeout is not None
            else recovery_previous.get("child_inactivity_timeout")
        ),
    }
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{STATUS_FILE.name}.", dir=STATUS_FILE.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(json.dumps(payload, indent=2) + "\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, STATUS_FILE)
        directory_fd = os.open(STATUS_FILE.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary_path.unlink(missing_ok=True)


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
    if data.get("last_child_output_at"):
        print(f"Last child output: {data['last_child_output_at']}")
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


def working_tree_paths() -> list[str]:
    """Return every staged, unstaged, deleted, or untracked path deterministically."""
    raw = run("git", "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    entries = raw.split("\0")
    paths: set[str] = set()
    index = 0
    while index < len(entries) and entries[index]:
        entry = entries[index]
        if len(entry) < 4 or entry[2] != " ":
            raise RuntimeError("Cannot parse working-tree scope for recovery")
        paths.add(entry[3:])
        if "R" in entry[:2] or "C" in entry[:2]:
            index += 1
            if index >= len(entries) or not entries[index]:
                raise RuntimeError("Cannot parse renamed working-tree path for recovery")
            paths.add(entries[index])
        index += 1
    return sorted(paths)


def recovery_snapshot(paths: list[str]) -> str:
    """Hash Git status, index metadata, and working-tree content for exact recovery scope."""
    digest = hashlib.sha256()
    head = run("git", "rev-parse", "HEAD").stdout.strip()
    if not head:
        raise RuntimeError("Cannot snapshot recovery base HEAD")
    digest.update(b"head\0" + head.encode())
    status = run("git", "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    digest.update(status.encode())
    for path_text in sorted(paths):
        path = Path(path_text)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("Cannot snapshot an unsafe recovery path")
        digest.update(b"\0path\0" + path_text.encode())
        index = run("git", "ls-files", "--stage", "-z", "--", path_text, check=False).stdout
        digest.update(b"\0index\0" + index.encode())
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            digest.update(b"\0missing")
            continue
        digest.update(f"\0mode\0{metadata.st_mode:o}".encode())
        if path.is_symlink():
            digest.update(b"\0symlink\0" + os.readlink(path).encode())
        elif path.is_file():
            digest.update(b"\0file\0")
            with path.open("rb") as source:
                while chunk := source.read(1_048_576):
                    digest.update(chunk)
        else:
            digest.update(b"\0other")
    return digest.hexdigest()


def recovery_content_snapshot(paths: list[str]) -> str:
    """Hash path identity and working-tree content without mutable index state."""
    digest = hashlib.sha256()
    for path_text in sorted(paths):
        path = Path(path_text)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError("Cannot snapshot an unsafe recovery path")
        digest.update(b"\0path\0" + path_text.encode())
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            digest.update(b"\0missing")
            continue
        digest.update(f"\0mode\0{metadata.st_mode:o}".encode())
        if path.is_symlink():
            digest.update(b"\0symlink\0" + os.readlink(path).encode())
        elif path.is_file():
            digest.update(b"\0file\0")
            with path.open("rb") as source:
                while chunk := source.read(1_048_576):
                    digest.update(chunk)
        else:
            digest.update(b"\0other")
    return digest.hexdigest()


def captured_recovery_scope() -> tuple[list[str] | None, str | None]:
    paths = working_tree_paths()
    if not paths:
        return None, None
    return paths, recovery_snapshot(paths)


def validate_recovery_scope() -> None:
    """Require the current dirty paths to exactly match the child-captured manifest."""
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("Cannot prove recovery working-tree scope") from exc
    expected = status.get("recoverable_paths") if isinstance(status, dict) else None
    expected_snapshot = status.get("recoverable_snapshot") if isinstance(status, dict) else None
    expected_content = (
        status.get("recoverable_content_snapshot") if isinstance(status, dict) else None
    )
    checkpoint = status.get("finalization_checkpoint") if isinstance(status, dict) else None
    if expected is None or (expected_snapshot is None and expected_content is None):
        raise RuntimeError(
            "Legacy recovery has no child-captured content manifest; "
            "explicit operator confirmation is required"
        )
    if not (
        isinstance(expected, list)
        and expected
        and all(isinstance(path, str) and path for path in expected)
        and working_tree_paths() == sorted(set(expected))
    ):
        raise RuntimeError(
            "Cannot prove recovery working-tree scope; refusing to stage preserved changes"
        )
    exact_snapshot_matches = isinstance(expected_snapshot, str) and (
        recovery_snapshot(expected) == expected_snapshot
    )
    staged_content_matches = (
        checkpoint in {"STAGING", "STAGED"}
        and isinstance(expected_content, str)
        and isinstance(status.get("recoverable_base_sha"), str)
        and run("git", "rev-parse", "HEAD").stdout.strip() == status.get("recoverable_base_sha")
        and recovery_content_snapshot(expected) == expected_content
    )
    if not exact_snapshot_matches and not staged_content_matches:
        raise RuntimeError(
            "Cannot prove recovery working-tree scope; refusing to stage preserved changes"
        )


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


def comment_once(issue_number: int, event: str, text: str) -> None:
    """Publish one auditable issue event even when recovery retries."""
    if not re.fullmatch(r"[a-z0-9-]+", event):
        raise ValueError("Invalid audit comment event marker")
    marker = f"<!-- growth-os-codex-handoff:{event} -->"
    payload = gh_json("issue", "view", str(issue_number), "--repo", REPO, "--json", "comments")
    comments = payload.get("comments") if isinstance(payload, dict) else None
    if not isinstance(comments, list):
        raise RuntimeError("GitHub returned invalid issue comments for audit deduplication")
    if any(isinstance(item, dict) and marker in str(item.get("body", "")) for item in comments):
        return
    comment(issue_number, f"{text}\n\n{marker}")


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
    inactivity_timeout: float = DEFAULT_CHILD_INACTIVITY_TIMEOUT,
    termination_grace: float = CHILD_TERMINATION_GRACE,
) -> tuple[int, str]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tail: list[str] = []
    with log_file.open("w", encoding="utf-8") as log:
        child_base_sha = run("git", "rev-parse", "HEAD").stdout.strip()
        if not child_base_sha:
            raise RuntimeError("Could not record Codex child base HEAD")
        write_status(
            "LAUNCHING",
            codex_pid=None,
            log_file=log_file,
            recoverable_base_sha=child_base_sha,
            reset_recovery=state in {"IMPLEMENTING", "FIXING"},
            **status_context,
        )
        gate_read, gate_write = os.pipe()
        try:
            process = subprocess.Popen(
                (sys.executable, "-c", LAUNCH_GATE_SCRIPT, str(gate_read), *command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
                pass_fds=(gate_read,),
            )
        except BaseException:
            os.close(gate_read)
            os.close(gate_write)
            raise
        os.close(gate_read)
        gate_open = True
        finalized = False
        stdin_open = False
        try:
            heartbeat = now_iso()
            child_identity = process_group_identity(process.pid)
            if child_identity is None:
                raise RuntimeError("Could not record Codex child process-group identity")
            recovery_paths, recovery_digest = captured_recovery_scope()
            write_status(
                state,
                codex_pid=process.pid,
                log_file=log_file,
                last_child_output_at=heartbeat,
                recoverable_paths=recovery_paths,
                recoverable_snapshot=recovery_digest,
                child_process_group=process.pid,
                child_process_identity=child_identity,
                child_inactivity_timeout=inactivity_timeout,
                recoverable_base_sha=child_base_sha,
                reset_recovery=state in {"IMPLEMENTING", "FIXING"},
                **status_context,
            )
            os.write(gate_write, b"1")
            os.close(gate_write)
            gate_open = False
            assert process.stdin is not None
            assert process.stdout is not None
            prompt_bytes = prompt.encode()
            prompt_offset = 0
            stdin_fd = process.stdin.fileno()
            os.set_blocking(stdin_fd, False)
            stdin_open = True
            if not prompt_bytes:
                process.stdin.close()
                stdin_open = False
            deadline = time.monotonic() + inactivity_timeout
            next_heartbeat_checkpoint = time.monotonic() + HEARTBEAT_CHECKPOINT_INTERVAL
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    message = f"Codex child exceeded {inactivity_timeout:g}s inactivity timeout\n"
                    log.write(message)
                    log.flush()
                    tail.append(message)
                    terminate_process_group(process, termination_grace)
                    recovery_paths, recovery_digest = captured_recovery_scope()
                    write_status(
                        state,
                        codex_pid=None,
                        log_file=log_file,
                        detail=message.strip(),
                        recoverable_paths=recovery_paths,
                        recoverable_snapshot=recovery_digest,
                        **status_context,
                    )
                    finalized = True
                    return process.returncode, "".join(tail)
                writers = [process.stdin] if stdin_open else []
                readable, writable, _ = select.select(
                    [process.stdout], writers, [], min(1.0, remaining)
                )
                if writable:
                    try:
                        written = os.write(
                            stdin_fd, prompt_bytes[prompt_offset : prompt_offset + 65_536]
                        )
                    except BlockingIOError:
                        written = 0
                    except BrokenPipeError:
                        written = 0
                        process.stdin.close()
                        stdin_open = False
                    if written:
                        prompt_offset += written
                        if prompt_offset == len(prompt_bytes):
                            process.stdin.close()
                            stdin_open = False
                if readable:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        continue
                    output = chunk.decode(errors="replace")
                    log.write(output)
                    log.flush()
                    tail.append(output)
                    if len(tail) > 100:
                        tail.pop(0)
                    heartbeat = now_iso()
                    output_time = time.monotonic()
                    deadline = output_time + inactivity_timeout
                    if output_time >= next_heartbeat_checkpoint:
                        write_status(
                            state,
                            codex_pid=process.pid,
                            log_file=log_file,
                            last_child_output_at=heartbeat,
                            **status_context,
                        )
                        next_heartbeat_checkpoint = output_time + HEARTBEAT_CHECKPOINT_INTERVAL
            return_code = process.wait()
            if stdin_open:
                process.stdin.close()
                stdin_open = False
            terminate_process_group(process, termination_grace)
            recovery_paths, recovery_digest = captured_recovery_scope()
            write_status(
                state,
                codex_pid=None,
                log_file=log_file,
                recoverable_paths=recovery_paths,
                recoverable_snapshot=recovery_digest,
                **status_context,
            )
            finalized = True
        finally:
            if gate_open:
                os.close(gate_write)
            if not finalized:
                if stdin_open and process.stdin is not None:
                    process.stdin.close()
                terminate_process_group(process, termination_grace)
                recovery_paths, recovery_digest = captured_recovery_scope()
                write_status(
                    state,
                    codex_pid=None,
                    log_file=log_file,
                    detail="Codex child interrupted; preserved changes require recovery",
                    recoverable_paths=recovery_paths,
                    recoverable_snapshot=recovery_digest,
                    **status_context,
                )
    return return_code, "".join(tail)


def terminate_process_group(process: subprocess.Popen[str], termination_grace: float) -> None:
    """Terminate the isolated child process group before recovery inspects the workspace."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    process.poll()
    deadline = time.monotonic() + termination_grace
    while process_group_is_running(process.pid) and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        process.poll()
    process.poll()
    if process_group_is_running(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + termination_grace
    while process_group_is_running(process.pid) and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        process.poll()
    if process_group_is_running(process.pid):
        raise RuntimeError("Codex child process group did not terminate")
    try:
        process.wait(timeout=termination_grace)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Codex child process leader did not terminate") from exc


def process_group_identity(pid: int) -> str | None:
    """Return stable OS evidence for the isolated process-group leader."""
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pgid=,lstart="],
        capture_output=True,
        text=True,
    )
    identity = result.stdout.strip()
    if result.returncode != 0 or not identity:
        return None
    pgid = identity.split(maxsplit=1)[0]
    return identity if pgid == str(pid) else None


def heartbeat_is_stale(value: object, timeout: object) -> bool:
    if (
        not isinstance(value, str)
        or not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or timeout <= 0
    ):
        raise RuntimeError("Cannot prove the orphaned child inactivity deadline")
    try:
        heartbeat = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError("Cannot parse the orphaned child heartbeat") from exc
    if heartbeat.tzinfo is None:
        raise RuntimeError("Orphaned child heartbeat is not timezone-aware")
    return (datetime.now(timezone.utc) - heartbeat).total_seconds() >= float(timeout)  # noqa: UP017


def process_group_is_running(process_group: int) -> bool:
    """Return whether any process still belongs to the recorded process group."""
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_orphan_process_group(pid: int, termination_grace: float) -> None:
    """Terminate a proven stale orphan process group before inspecting recovery scope."""
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + termination_grace
    while process_group_is_running(pid) and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    if process_group_is_running(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    deadline = time.monotonic() + termination_grace
    while process_group_is_running(pid) and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    if process_group_is_running(pid):
        raise RuntimeError("Orphaned Codex process group did not terminate")


def recovery_blocked_error(
    context: StatusContext, detail: str, *, codex_pid: int | None = None
) -> RuntimeError:
    """Durably leave an active stale state before failing closed."""
    write_status("RECOVERY_BLOCKED", codex_pid=codex_pid, detail=detail, **context)
    return RuntimeError(detail)


def reconcile_stale_run() -> StatusContext | None:
    """Fail closed or surface preserved work from an interrupted implementation."""
    if not STATUS_FILE.exists():
        return None
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError("Handoff status is unreadable; refusing startup recovery") from exc
    if not isinstance(status, dict) or status.get("state") not in {
        "IMPLEMENTING",
        "FIXING",
        "RECOVERABLE_CHANGES",
        "COMMITTING",
        "COMMITTED",
        "PUSHING",
        "PUSHED",
        "PR_CREATED",
        "VERIFYING",
        "REVIEWING",
        "REVIEW_PASSED",
        "RECOVERY_BLOCKED",
        "RECOVERY_CONFIRMATION_REQUIRED",
        "LAUNCHING",
        "SYNCING",
    }:
        return None

    issue = status.get("issue")
    title = status.get("title")
    branch = status.get("branch")
    started_at = status.get("started_at")
    if type(issue) is not int or not all(
        isinstance(value, str) and value for value in (title, branch, started_at)
    ):
        raise RuntimeError("Stale implementation status cannot prove task ownership")
    context: StatusContext = {
        "issue": issue,
        "title": cast(str, title),
        "branch": cast(str, branch),
        "started_at": cast(str, started_at),
    }
    if status["state"] == "RECOVERY_CONFIRMATION_REQUIRED":
        raise RuntimeError(
            "Recovery requires explicit operator confirmation via --confirm-recovery"
        )
    pid = status.get("codex_pid")
    stopped_child_scope_is_proven = False
    if (
        status["state"]
        in {
            "IMPLEMENTING",
            "FIXING",
            "REVIEWING",
            "RECOVERY_BLOCKED",
        }
        and type(pid) is int
    ):
        group = status.get("child_process_group")
        identity = status.get("child_process_identity")
        if type(group) is int and group == pid and isinstance(identity, str):
            group_running = process_group_is_running(group)
        elif pid_is_running(pid):
            raise recovery_blocked_error(
                context,
                "Cannot prove live orphaned Codex process-group identity",
                codex_pid=pid,
            )
        else:
            group_running = False
        if group_running:
            if not pid_is_running(pid) or process_group_identity(pid) != identity:
                detail = (
                    "Recovery blocked: a live recorded process group has no provable leader "
                    "identity; no signal was sent"
                )
                raise recovery_blocked_error(context, detail, codex_pid=pid)
            if not heartbeat_is_stale(
                status.get("last_child_output_at"), status.get("child_inactivity_timeout")
            ):
                raise ActiveOrphanError(
                    f"Recorded Codex process group {group} is still active; refusing recovery"
                )
            terminate_orphan_process_group(cast(int, group), CHILD_TERMINATION_GRACE)
        if type(group) is int and group == pid and isinstance(identity, str):
            stopped_child_scope_is_proven = True

    current_branch = run("git", "branch", "--show-current").stdout.strip()
    if current_branch != branch:
        raise recovery_blocked_error(
            context,
            "Cannot prove recovery branch identity: "
            f"status records {branch!r}, checkout is {current_branch!r}",
            codex_pid=pid if type(pid) is int else None,
        )
    if stopped_child_scope_is_proven:
        recorded_base = status.get("recoverable_base_sha")
        current_head = run("git", "rev-parse", "HEAD").stdout.strip()
        if not isinstance(recorded_base, str) or not recorded_base or current_head != recorded_base:
            raise recovery_blocked_error(
                context,
                "Cannot prove the stopped Codex child's task base HEAD",
                codex_pid=pid if type(pid) is int else None,
            )
    has_changes = bool(run("git", "status", "--porcelain").stdout.strip())
    checkpoint = status.get("finalization_checkpoint")
    has_trusted_manifest = (
        isinstance(status.get("recoverable_paths"), list)
        and bool(status.get("recoverable_paths"))
        and (
            isinstance(status.get("recoverable_snapshot"), str)
            or isinstance(status.get("recoverable_content_snapshot"), str)
        )
    )
    if status["state"] == "COMMITTING" and not has_changes and checkpoint == "STAGED":
        pre_commit_sha = status.get("pre_commit_sha")
        current_head = run("git", "rev-parse", "HEAD").stdout.strip()
        parent_head = run("git", "rev-parse", "HEAD^").stdout.strip()
        subject = run("git", "log", "-1", "--pretty=%s").stdout.strip()
        recorded_subject = status.get("pending_commit_subject")
        pending_tree_sha = status.get("pending_tree_sha")
        current_tree_sha = run("git", "rev-parse", "HEAD^{tree}").stdout.strip()
        allowed_subjects = {
            f"codex: resolve issue #{issue}",
            *(
                f"codex: address review round {round_number} for #{issue}"
                for round_number in (1, 2)
            ),
        }
        expected_subject = (
            recorded_subject
            if isinstance(recorded_subject, str) and recorded_subject in allowed_subjects
            else f"codex: resolve issue #{issue}"
        )
        if (
            isinstance(pre_commit_sha, str)
            and pre_commit_sha
            and current_head
            and parent_head == pre_commit_sha
            and subject == expected_subject
            and isinstance(pending_tree_sha, str)
            and pending_tree_sha
            and current_tree_sha == pending_tree_sha
        ):
            write_status(
                "RECOVERABLE_CHANGES",
                detail="Recovered a proven commit created before its checkpoint was recorded",
                finalization_checkpoint="COMMITTED",
                commit_sha=current_head,
                **context,
            )
            return context
        raise RuntimeError("Cannot prove the commit created by an interrupted finalization")
    if not has_changes and checkpoint not in {"COMMITTED", "PUSHED", "PR_CREATED"}:
        failure = RuntimeError("Interrupted Codex implementation left no working-tree changes")
        write_status("RECOVERY_BLOCKED", detail=str(failure), **context)
        issue_payload = load_recovery_issue(context)
        record_issue_failure(issue_payload, failure)
        raise failure

    if has_changes and not stopped_child_scope_is_proven and not has_trusted_manifest:
        detail = (
            "Legacy preserved work lacks attributable content provenance; explicit operator "
            "confirmation is required"
        )
        write_status("RECOVERY_CONFIRMATION_REQUIRED", detail=detail, **context)
        raise RuntimeError(detail)
    if has_changes and stopped_child_scope_is_proven:
        detail = (
            "Stopped child work lacks a final durable content manifest; explicit operator "
            "confirmation is required"
        )
        write_status(
            "RECOVERY_CONFIRMATION_REQUIRED",
            codex_pid=pid if type(pid) is int else None,
            detail=detail,
            **context,
        )
        raise RuntimeError(detail)
    write_status(
        "RECOVERABLE_CHANGES",
        detail="Preserved task work from an interrupted Codex run; recovery required",
        **context,
    )
    return context


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


def parse_auto_merge_assessment(body: str) -> AutoMergeAssessment:
    """Parse the single strict owner-authored auto-merge assessment block."""
    blocks = AUTO_MERGE_SECTION.findall(body)
    if len(blocks) != 1:
        raise ValueError("exactly one Auto-merge assessment JSON block is required")
    try:
        payload = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError("Auto-merge assessment is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != AUTO_MERGE_FIELDS:
        raise ValueError("Auto-merge assessment fields do not match the contract")

    risk = payload["risk"]
    roadmap_authorized = payload["roadmap_authorized"]
    reversible = payload["reversible"]
    production_deployment = payload["production_deployment"]
    external_customer_side_effect = payload["external_customer_side_effect"]
    stop_categories = payload["stop_categories"]
    if not isinstance(risk, str):
        raise ValueError("Auto-merge risk must be a string")
    for name, value in (
        ("roadmap_authorized", roadmap_authorized),
        ("reversible", reversible),
        ("production_deployment", production_deployment),
        ("external_customer_side_effect", external_customer_side_effect),
    ):
        if type(value) is not bool:
            raise ValueError(f"Auto-merge {name} must be a boolean")
    if not isinstance(stop_categories, list) or not all(
        isinstance(category, str) for category in stop_categories
    ):
        raise ValueError("Auto-merge stop_categories must be a string list")
    return {
        "risk": risk,
        "roadmap_authorized": roadmap_authorized,
        "reversible": reversible,
        "production_deployment": production_deployment,
        "external_customer_side_effect": external_customer_side_effect,
        "stop_categories": stop_categories,
    }


def _protected_auto_merge_path(path: str) -> bool:
    normalized = path.strip().lower()
    if not normalized or normalized in PROTECTED_AUTO_MERGE_PATHS:
        return True
    file_path = Path(normalized)
    if any(part == "agents.md" for part in file_path.parts):
        return True
    if any(part.startswith(".env") for part in file_path.parts) or (
        file_path.suffix in PROTECTED_AUTO_MERGE_SUFFIXES
    ):
        return True
    path_tokens = [
        token
        for part in file_path.parts
        for token in re.split(r"[^a-z0-9]+", Path(part).stem)
        if token
    ]
    return any(part in PROTECTED_AUTO_MERGE_PARTS for part in file_path.parts) or any(
        token.startswith(PROTECTED_AUTO_MERGE_PREFIXES) for token in path_tokens
    )


def auto_merge_policy_reasons(issue: Issue, changed_paths: list[str]) -> list[str]:
    """Return deterministic stop reasons; an empty result authorizes merge evaluation."""
    reasons: list[str] = []
    try:
        assessment = parse_auto_merge_assessment(issue.get("body") or "")
    except ValueError as exc:
        return [str(exc)]
    if assessment["risk"] not in {"low", "medium"}:
        reasons.append("risk is not low or medium")
    if not assessment["roadmap_authorized"]:
        reasons.append("task is not roadmap authorized")
    if not assessment["reversible"]:
        reasons.append("change is not declared reversible")
    if assessment["production_deployment"]:
        reasons.append("production deployment is declared")
    if assessment["external_customer_side_effect"]:
        reasons.append("external customer-facing side effect is declared")
    if assessment["stop_categories"]:
        reasons.append("one or more mandatory stop categories are declared")
    for path in changed_paths:
        if _protected_auto_merge_path(path):
            reasons.append(f"protected path requires human merge: {path}")
    if not changed_paths:
        reasons.append("no changed paths were found")
    return reasons


def validate_pr_for_merge(
    metadata: dict[str, object], *, expected_branch: str, reviewed_head: str
) -> list[str]:
    """Validate current GitHub PR state against the exact independently reviewed head."""
    reasons: list[str] = []
    expected = {
        "state": "OPEN",
        "baseRefName": "main",
        "headRefName": expected_branch,
        "headRefOid": reviewed_head,
        "mergeable": "MERGEABLE",
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            reasons.append(f"PR {field} does not match required value")
    if metadata.get("reviewDecision") in {"CHANGES_REQUESTED", "REVIEW_REQUIRED"}:
        reasons.append("PR has an unsatisfied blocking review state")
    labels = metadata.get("labels")
    if not isinstance(labels, list) or REVIEWED_LABEL not in {
        label.get("name")
        for label in labels
        if isinstance(label, dict) and isinstance(label.get("name"), str)
    }:
        reasons.append("PR is missing the review-passed marker")
    if type(metadata.get("number")) is not int:
        reasons.append("PR number is invalid")
    return reasons


def _pr_metadata(pr_url: str) -> dict[str, object]:
    payload = json.loads(
        run(
            "gh",
            "pr",
            "view",
            pr_url,
            "--repo",
            REPO,
            "--json",
            "number,url,state,isDraft,mergeable,baseRefName,headRefName,headRefOid,reviewDecision,labels",
        ).stdout
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned invalid PR metadata")
    return cast(dict[str, object], payload)


def _has_unresolved_review_threads(pr_number: int) -> bool:
    owner, name = REPO.split("/", 1)
    query = (
        "query($owner:String!,$name:String!,$number:Int!){"
        "repository(owner:$owner,name:$name){pullRequest(number:$number){"
        "reviewThreads(first:100){nodes{isResolved}pageInfo{hasNextPage}}}}}"
    )
    payload = json.loads(
        run(
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr_number}",
        ).stdout
    )
    try:
        threads = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        nodes = threads["nodes"]
        has_next_page = threads["pageInfo"]["hasNextPage"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError("GitHub returned invalid review-thread metadata") from exc
    if not isinstance(nodes, list) or type(has_next_page) is not bool:
        raise RuntimeError("GitHub returned invalid review-thread nodes")
    return has_next_page or any(
        not isinstance(node, dict) or node.get("isResolved") is not True for node in nodes
    )


def _current_issue_for_merge(issue_number: int) -> Issue:
    """Re-fetch and validate the owner-controlled authorization immediately before merge."""
    payload = json.loads(
        run(
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--repo",
            REPO,
            "--json",
            "number,title,body,author,state,url",
        ).stdout
    )
    if not isinstance(payload, dict) or payload.get("number") != issue_number:
        raise ValueError("current issue metadata is invalid")
    author = payload.get("author")
    login = author.get("login") if isinstance(author, dict) else None
    if not isinstance(login, str) or login.lower() != OWNER.lower():
        raise ValueError("current issue author is not authorized")
    if payload.get("state") != "OPEN":
        raise ValueError("current issue is no longer open")
    if not isinstance(payload.get("title"), str) or not isinstance(payload.get("body"), str):
        raise ValueError("current issue contract is invalid")
    return cast(Issue, payload)


def merge_reviewed_pr(
    issue: Issue,
    branch: str,
    pr_url: str,
    reviewed_head: str,
    status_context: StatusContext,
) -> MergeOutcome:
    """Apply the trusted policy and exact-head merge, or return a safe blocked outcome."""
    changed_paths = [
        path
        for path in run(
            "git", "diff", "--no-renames", "--name-only", "-z", "origin/main...HEAD"
        ).stdout.split("\0")
        if path
    ]
    try:
        current_issue = _current_issue_for_merge(int(issue["number"]))
    except ValueError as exc:
        return {"merged": False, "reasons": [str(exc)], "sha": None}
    reasons = auto_merge_policy_reasons(current_issue, changed_paths)
    if reasons:
        return {"merged": False, "reasons": reasons, "sha": None}

    metadata = _pr_metadata(pr_url)
    reasons.extend(
        validate_pr_for_merge(metadata, expected_branch=branch, reviewed_head=reviewed_head)
    )
    pr_number = metadata.get("number")
    if type(pr_number) is int and _has_unresolved_review_threads(pr_number):
        reasons.append("PR has unresolved review threads")
    if reasons:
        return {"merged": False, "reasons": reasons, "sha": None}

    if metadata.get("isDraft") is True:
        run("gh", "pr", "ready", pr_url, "--repo", REPO)

    try:
        current_issue = _current_issue_for_merge(int(issue["number"]))
    except ValueError as exc:
        return {"merged": False, "reasons": [str(exc)], "sha": None}
    reasons = auto_merge_policy_reasons(current_issue, changed_paths)
    metadata = _pr_metadata(pr_url)
    reasons.extend(
        validate_pr_for_merge(metadata, expected_branch=branch, reviewed_head=reviewed_head)
    )
    if metadata.get("isDraft") is not False:
        reasons.append("PR is still a draft at final validation")
    pr_number = metadata.get("number")
    if type(pr_number) is int and _has_unresolved_review_threads(pr_number):
        reasons.append("PR has unresolved review threads at final validation")
    if reasons:
        return {"merged": False, "reasons": reasons, "sha": None}

    write_status(
        "MERGING",
        detail="Auto-merge policy passed; merging exact reviewed head",
        pr_url=pr_url,
        **status_context,
    )

    try:
        run(
            "gh",
            "pr",
            "merge",
            pr_url,
            "--repo",
            REPO,
            "--squash",
            "--match-head-commit",
            reviewed_head,
        )
    except subprocess.CalledProcessError as merge_error:
        try:
            merged = _merge_status(pr_url)
        except (json.JSONDecodeError, subprocess.SubprocessError):
            raise merge_error from None
        if merged.get("state") == "OPEN":
            return {
                "merged": False,
                "reasons": ["exact-head merge was rejected while the reviewed PR remains open"],
                "sha": None,
            }
        merge_commit = merged.get("mergeCommit")
        merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
        if merged.get("state") == "MERGED" and isinstance(merge_sha, str):
            return {"merged": True, "reasons": [], "sha": merge_sha}
        raise merge_error from None

    merged = _merge_status(pr_url)
    merge_commit = merged.get("mergeCommit") if isinstance(merged, dict) else None
    merge_sha = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    if (
        not isinstance(merged, dict)
        or merged.get("state") != "MERGED"
        or not isinstance(merge_sha, str)
    ):
        raise RuntimeError("GitHub did not confirm the merged PR and merge commit SHA")
    return {"merged": True, "reasons": [], "sha": merge_sha}


def _merge_status(pr_url: str) -> dict[str, object]:
    payload = json.loads(
        run("gh", "pr", "view", pr_url, "--repo", REPO, "--json", "state,mergeCommit,url").stdout
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned invalid merge status")
    return cast(dict[str, object], payload)


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
        paths, snapshot = captured_recovery_scope()
        if paths:
            write_status(
                "RECOVERABLE_CHANGES",
                log_file=log_file,
                detail=f"Fixer exited with {return_code}; preserved changes require recovery",
                recoverable_paths=paths,
                recoverable_snapshot=snapshot,
                **status_context,
            )
            raise RecoverableChangesError(
                f"Fixer exited with {return_code}; preserved task changes require recovery"
            )
        raise RuntimeError(f"Fixer exited with {return_code}:\n{output_tail[-3000:]}")
    if not run("git", "status", "--porcelain").stdout.strip():
        raise RuntimeError("Reviewer fixer produced no changes")


def commit_review_fix(issue: Issue, fix_round: int, status_context: StatusContext) -> None:
    subject = f"codex: address review round {fix_round} for #{issue['number']}"
    commit_sha = commit_with_recovery_checkpoint(
        issue,
        status_context,
        subject=subject,
        detail=f"Review fix round {fix_round}",
    )
    run("git", "push")
    write_status(
        "PUSHED",
        detail=f"Review fix round {fix_round} pushed",
        finalization_checkpoint="PUSHED",
        commit_sha=commit_sha,
        **status_context,
    )


def commit_with_recovery_checkpoint(
    issue: Issue,
    status_context: StatusContext,
    *,
    subject: str,
    detail: str,
    log_file: Path | None = None,
) -> str:
    """Stage and commit with provenance for both adjacent crash windows."""
    pre_commit_sha = run("git", "rev-parse", "HEAD").stdout.strip()
    if not pre_commit_sha:
        raise RuntimeError("Could not record the pre-commit recovery checkpoint")
    recovery_paths = working_tree_paths()
    if not recovery_paths:
        raise RuntimeError("Cannot record an empty pre-staging recovery checkpoint")
    write_status(
        "COMMITTING",
        log_file=log_file,
        detail=f"{detail}: staging changes",
        pre_commit_sha=pre_commit_sha,
        pending_commit_subject=subject,
        finalization_checkpoint="STAGING",
        recoverable_paths=recovery_paths,
        recoverable_content_snapshot=recovery_content_snapshot(recovery_paths),
        recoverable_base_sha=pre_commit_sha,
        **status_context,
    )
    run("git", "add", "-A")
    pending_tree_sha = run("git", "write-tree").stdout.strip()
    if not pending_tree_sha:
        raise RuntimeError("Could not record the staged tree recovery checkpoint")
    write_status(
        "COMMITTING",
        log_file=log_file,
        detail=f"{detail}: committing staged tree",
        finalization_checkpoint="STAGED",
        pending_tree_sha=pending_tree_sha,
        **status_context,
    )
    run("git", "commit", "-m", subject)
    commit_sha = run("git", "rev-parse", "HEAD").stdout.strip()
    if not commit_sha:
        raise RuntimeError("Could not record the commit recovery checkpoint")
    write_status(
        "COMMITTED",
        log_file=log_file,
        detail=f"{detail}: changes committed",
        finalization_checkpoint="COMMITTED",
        commit_sha=commit_sha,
        **status_context,
    )
    return commit_sha


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
        commit_review_fix(issue, review_round, status_context)
    raise AssertionError("unreachable review loop state")


def find_draft_pr(branch: str) -> str | None:
    """Discover the single open draft PR for a task branch, if one exists."""
    payload = gh_json(
        "pr",
        "list",
        "--repo",
        REPO,
        "--state",
        "open",
        "--head",
        branch,
        "--json",
        "url,isDraft",
    )
    if not isinstance(payload, list) or len(payload) > 1:
        raise RuntimeError("Cannot uniquely identify the recovery draft PR")
    if not payload:
        return None
    pr = payload[0]
    if (
        not isinstance(pr, dict)
        or pr.get("isDraft") is not True
        or not isinstance(pr.get("url"), str)
    ):
        raise RuntimeError("Existing recovery PR is not a proven draft PR")
    return cast(str, pr["url"])


def remote_branch_head(branch: str) -> str | None:
    """Resolve exactly one remote task-branch head without updating local refs."""
    output = run("git", "ls-remote", "--heads", "origin", branch).stdout.strip()
    if not output:
        return None
    lines = output.splitlines()
    expected_ref = f"refs/heads/{branch}"
    matches = [line.split() for line in lines]
    if len(matches) != 1 or len(matches[0]) != 2 or matches[0][1] != expected_ref:
        raise RuntimeError("Cannot uniquely prove the remote recovery branch head")
    return matches[0][0]


def validate_committed_recovery_checkpoint(
    status: dict[str, object], branch: str, completed: int
) -> None:
    """Prove local, remote, and PR revisions before executing repository code."""
    commit_sha = status.get("commit_sha")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise RuntimeError("Recovery commit checkpoint is missing")
    if run("git", "rev-parse", "HEAD").stdout.strip() != commit_sha:
        raise RuntimeError("Recovery commit checkpoint does not match the current HEAD")
    if completed >= 2 and remote_branch_head(branch) != commit_sha:
        raise RuntimeError("Recovery push checkpoint does not match the remote branch head")
    if completed >= 3:
        pr_url = status.get("pr_url")
        if not isinstance(pr_url, str) or not pr_url:
            raise RuntimeError("Recovery draft PR checkpoint is missing")
        metadata = _pr_metadata(pr_url)
        expected = {
            "url": pr_url,
            "state": "OPEN",
            "isDraft": True,
            "baseRefName": "main",
            "headRefName": branch,
            "headRefOid": commit_sha,
        }
        if any(metadata.get(field) != value for field, value in expected.items()):
            raise RuntimeError("Recovery draft PR checkpoint does not match its recorded revision")


def finalize_changes(
    issue: Issue,
    status_context: StatusContext,
    log_file: Path,
    *,
    allow_merge: bool,
    recovering: bool = False,
) -> None:
    """Verify preserved changes and complete the normal commit/push/draft-PR workflow."""
    number = int(issue["number"])
    title = issue["title"]
    branch = status_context["branch"]
    status = (
        json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        if recovering and STATUS_FILE.exists()
        else {}
    )
    checkpoint = status.get("finalization_checkpoint") if isinstance(status, dict) else None
    commit_sha = status.get("commit_sha") if isinstance(status, dict) else None
    completed = {"COMMITTED": 1, "PUSHED": 2, "PR_CREATED": 3}.get(str(checkpoint), 0)
    if recovering:
        if completed == 0:
            validate_recovery_scope()
        else:
            if working_tree_paths():
                raise RuntimeError(
                    "Cannot resume finalization with uncommitted working-tree changes"
                )
            validate_committed_recovery_checkpoint(status, branch, completed)
    run_verification(issue, status_context, 1)
    if recovering and completed == 0:
        validate_recovery_scope()
    elif recovering and working_tree_paths():
        raise RuntimeError("Recovery verification dirtied a committed checkpoint")

    if completed == 0:
        commit_sha = commit_with_recovery_checkpoint(
            issue,
            status_context,
            subject=f"codex: resolve issue #{number}",
            detail="Initial implementation",
            log_file=log_file,
        )
        completed = 1
    elif not isinstance(commit_sha, str):
        raise RuntimeError("Recovery commit checkpoint is invalid")

    if completed < 2:
        write_status("PUSHING", log_file=log_file, detail="Pushing task branch", **status_context)
        run("git", "push", "-u", "origin", branch)
        write_status(
            "PUSHED",
            log_file=log_file,
            detail="Task branch pushed",
            finalization_checkpoint="PUSHED",
            commit_sha=commit_sha,
            **status_context,
        )
        completed = 2

    pr_body = (
        f"Automated local Codex handoff for #{number}.\n\nCloses #{number}.\n\n"
        "This PR was created by the self-hosted controller. It is intentionally a draft. "
        "It must pass independent review and the bounded merge policy before merge. "
        "No production deployment is authorized."
    )
    pr_url = find_draft_pr(branch) if recovering else None
    recorded_pr = status.get("pr_url") if isinstance(status, dict) else None
    if completed >= 3 and (not isinstance(recorded_pr, str) or pr_url != recorded_pr):
        raise RuntimeError("Recovery draft PR checkpoint cannot be proven")
    if pr_url is None:
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
            title,
            "--body",
            pr_body,
        ).stdout.strip()
        if not pr_url:
            raise RuntimeError("GitHub did not return the created draft PR URL")

    write_status(
        "PR_CREATED",
        log_file=log_file,
        detail="Draft PR opened",
        pr_url=pr_url,
        finalization_checkpoint="PR_CREATED",
        commit_sha=commit_sha,
        **status_context,
    )
    comment_once(
        number, "draft-pr-opened", f"Codex opened a draft PR for independent review: {pr_url}"
    )
    run_review_fix_loop(issue, status_context)
    mark_pr_review_passed(pr_url)
    write_status(
        "REVIEW_PASSED",
        detail="Independent review passed with zero findings",
        pr_url=pr_url,
        **status_context,
    )
    comment_once(
        number,
        "independent-review-passed",
        f"Independent review passed with zero findings: {pr_url}",
    )
    label(number, add=REVIEWED_LABEL)
    reviewed_head = run("git", "rev-parse", "HEAD").stdout.strip()
    if not reviewed_head:
        raise RuntimeError("Could not resolve the exact reviewed HEAD commit")
    outcome: MergeOutcome
    if allow_merge:
        outcome = merge_reviewed_pr(issue, branch, pr_url, reviewed_head, status_context)
    else:
        outcome = {
            "merged": False,
            "reasons": ["Recovery never auto-merges preserved work"],
            "sha": None,
        }
    if outcome["merged"]:
        merge_sha = outcome["sha"]
        write_status(
            "MERGED",
            detail=f"Eligible reviewed PR merged at {merge_sha}",
            pr_url=pr_url,
            **status_context,
        )
        comment_once(
            number,
            "auto-merge-completed",
            f"Bounded auto-merge completed at `{merge_sha}`: {pr_url}",
        )
        label(number, add=MERGED_LABEL)
    else:
        reason_text = "; ".join(outcome["reasons"])
        write_status("MERGE_BLOCKED", detail=reason_text, pr_url=pr_url, **status_context)
        comment_once(
            number,
            "auto-merge-stopped",
            f"Auto-merge stopped safely; reviewed PR remains open: {reason_text}",
        )
        label(number, add=MERGE_BLOCKED_LABEL)
    label(number, add=DONE_LABEL, remove=RUNNING_LABEL)


def load_recovery_issue(status_context: StatusContext) -> Issue:
    """Reload the exact owner-authored open issue recorded by the interrupted run."""
    number = status_context["issue"]
    payload = gh_json(
        "issue",
        "view",
        str(number),
        "--repo",
        REPO,
        "--json",
        "number,title,body,author,state,url",
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Cannot prove recovery task ownership from GitHub")
    author = payload.get("author")
    if (
        type(payload.get("number")) is not int
        or payload["number"] != number
        or payload.get("title") != status_context["title"]
        or payload.get("state") != "OPEN"
        or not isinstance(author, dict)
        or str(author.get("login", "")).lower() != OWNER.lower()
    ):
        raise RuntimeError("Cannot prove recovery task ownership from GitHub")
    return cast(Issue, payload)


def recover_changes(status_context: StatusContext) -> None:
    """Finalize preserved implementation work without invoking Codex implementation again."""
    issue = load_recovery_issue(status_context)
    number = status_context["issue"]
    log_file = LOG_DIR / f"recovery-{number}.log"
    comment_once(
        number,
        "recovery-started",
        "Recovering preserved task changes without rerunning implementation.",
    )
    try:
        finalize_changes(issue, status_context, log_file, allow_merge=False, recovering=True)
    except Exception as exc:
        write_status(
            "RECOVERABLE_CHANGES",
            detail=f"Recovery stopped; preserved changes remain: {str(exc)[-700:]}",
            **status_context,
        )
        raise RecoverableChangesError(str(exc)) from exc


def confirm_recovery() -> int:
    """Explicitly authorize the current stopped-child scope and finalize it safely."""
    ensure_tools()
    ensure_labels()
    acquire_lock()
    try:
        try:
            status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError("Recovery confirmation status is unreadable") from exc
        if not isinstance(status, dict) or status.get("state") != (
            "RECOVERY_CONFIRMATION_REQUIRED"
        ):
            raise RuntimeError("No recovery is awaiting explicit operator confirmation")
        issue = status.get("issue")
        title = status.get("title")
        branch = status.get("branch")
        started_at = status.get("started_at")
        if type(issue) is not int or not all(
            isinstance(value, str) and value for value in (title, branch, started_at)
        ):
            raise RuntimeError("Cannot prove the recovery confirmation task context")
        context: StatusContext = {
            "issue": issue,
            "title": cast(str, title),
            "branch": cast(str, branch),
            "started_at": cast(str, started_at),
        }
        load_recovery_issue(context)
        pid = status.get("codex_pid")
        group = status.get("child_process_group")
        identity = status.get("child_process_identity")
        instrumented = (
            type(pid) is int and type(group) is int and group == pid and isinstance(identity, str)
        )
        if instrumented:
            if pid_is_running(cast(int, pid)) or process_group_is_running(cast(int, group)):
                raise RuntimeError(
                    "Cannot prove the confirmed Codex child process group is stopped"
                )
        elif (type(pid) is int and pid_is_running(pid)) or (
            type(group) is int and process_group_is_running(group)
        ):
            raise RuntimeError("Legacy recovery still records a live process or process group")
        if run("git", "branch", "--show-current").stdout.strip() != branch:
            raise RuntimeError("Cannot prove the recovery confirmation branch")
        base = status.get("recoverable_base_sha")
        if isinstance(base, str) and run("git", "rev-parse", "HEAD").stdout.strip() != base:
            raise RuntimeError("Cannot prove the recovery confirmation base HEAD")
        paths, snapshot = captured_recovery_scope()
        if not paths or not snapshot:
            raise RuntimeError("Recovery confirmation found no preserved working-tree changes")
        write_status(
            "RECOVERABLE_CHANGES",
            codex_pid=None,
            detail="Operator confirmed the stopped child's current recovery scope",
            recoverable_paths=paths,
            recoverable_snapshot=snapshot,
            **context,
        )
        recover_changes(context)
        return 0
    finally:
        release_lock()


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

    write_status(
        "SYNCING",
        log_file=log_file,
        detail="Preparing task branch",
        reset_recovery=True,
        **status_context,
    )
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

    try:
        return_code, output_tail = run_codex_stream(prompt, log_file, status_context)
    except KeyboardInterrupt as exc:
        paths, snapshot = captured_recovery_scope()
        if paths:
            write_status(
                "RECOVERABLE_CHANGES",
                log_file=log_file,
                detail="Controller interrupted; preserved changes require recovery",
                recoverable_paths=paths,
                recoverable_snapshot=snapshot,
                **status_context,
            )
            raise RecoverableChangesError(
                "Controller interrupted; preserved task changes require recovery"
            ) from exc
        raise
    if return_code != 0:
        paths, snapshot = captured_recovery_scope()
        if paths:
            write_status(
                "RECOVERABLE_CHANGES",
                log_file=log_file,
                detail=f"Codex exited with {return_code}; preserved changes require recovery",
                recoverable_paths=paths,
                recoverable_snapshot=snapshot,
                **status_context,
            )
            raise RecoverableChangesError(
                f"Codex exited with {return_code}; preserved task changes require recovery"
            )
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

    finalize_changes(issue, status_context, log_file, allow_merge=True)


def record_issue_failure(issue: Issue, exc: BaseException) -> None:
    """Persist and publish a terminal failure for the selected issue."""
    number = int(issue["number"])
    detail = str(exc)[-1000:]
    write_status("FAILED", issue=number, title=issue.get("title"), detail=detail)
    label(number, add=FAILED_LABEL, remove=RUNNING_LABEL)
    comment(number, f"Local Codex controller failed:\n\n```text\n{str(exc)[-3000:]}\n```")


def recoverable_finalization_error(
    issue: Issue, exc: BaseException
) -> RecoverableChangesError | None:
    """Preserve resumable finalization state instead of overwriting it with FAILED."""
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(status, dict) or status.get("issue") != int(issue["number"]):
        return None
    state = status.get("state")
    checkpoint = status.get("finalization_checkpoint")
    trusted_paths = status.get("recoverable_paths")
    has_trusted_manifest = (
        isinstance(trusted_paths, list)
        and bool(trusted_paths)
        and (
            isinstance(status.get("recoverable_snapshot"), str)
            or isinstance(status.get("recoverable_content_snapshot"), str)
        )
    )
    recoverable_states = {
        "VERIFYING",
        "COMMITTING",
        "COMMITTED",
        "PUSHING",
        "PUSHED",
        "PR_CREATED",
        "REVIEWING",
        "REVIEW_PASSED",
    }
    if state not in recoverable_states or (
        not has_trusted_manifest and checkpoint not in {"COMMITTED", "PUSHED", "PR_CREATED"}
    ):
        return None
    title = status.get("title")
    branch = status.get("branch")
    started_at = status.get("started_at")
    if not all(isinstance(value, str) and value for value in (title, branch, started_at)):
        return None
    context: StatusContext = {
        "issue": int(issue["number"]),
        "title": cast(str, title),
        "branch": cast(str, branch),
        "started_at": cast(str, started_at),
    }
    detail = f"Finalization stopped; preserved task work requires recovery: {str(exc)[-700:]}"
    write_status(
        "RECOVERABLE_CHANGES",
        detail=detail,
        **context,
    )
    return RecoverableChangesError(detail)


def recoverable_interruption_error(
    status_context: StatusContext, exc: BaseException
) -> RecoverableChangesError | None:
    """Preserve dirty work or a durable checkpoint when the operator interrupts a task."""
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        status = {}
    checkpoint = status.get("finalization_checkpoint") if isinstance(status, dict) else None
    trusted_paths = status.get("recoverable_paths") if isinstance(status, dict) else None
    has_trusted_manifest = (
        isinstance(trusted_paths, list)
        and bool(trusted_paths)
        and (
            isinstance(status.get("recoverable_snapshot"), str)
            or isinstance(status.get("recoverable_content_snapshot"), str)
        )
    )
    if not has_trusted_manifest and checkpoint not in {
        "STAGING",
        "STAGED",
        "COMMITTED",
        "PUSHED",
        "PR_CREATED",
    }:
        return None
    detail = f"Controller interrupted; preserved task work requires recovery: {str(exc)[-700:]}"
    write_status(
        "RECOVERABLE_CHANGES",
        detail=detail,
        **status_context,
    )
    return RecoverableChangesError(detail)


def recorded_status_context(issue: Issue) -> StatusContext | None:
    """Load the exact persisted context for an actively selected issue."""
    try:
        status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(status, dict) or status.get("issue") != int(issue["number"]):
        return None
    title = status.get("title")
    branch = status.get("branch")
    started_at = status.get("started_at")
    if title != issue["title"] or not all(
        isinstance(value, str) and value for value in (title, branch, started_at)
    ):
        return None
    return {
        "issue": int(issue["number"]),
        "title": cast(str, title),
        "branch": cast(str, branch),
        "started_at": cast(str, started_at),
    }


def run_once() -> int:
    ensure_tools()
    ensure_labels()
    acquire_lock()
    try:
        recovery = reconcile_stale_run()
        if recovery is not None:
            recover_changes(recovery)
            return 0
        clean_tree_required()
        issue = next_issue()
        if issue is None:
            write_status("IDLE", detail="No codex-ready issues found")
            print("No codex-ready issues found.")
            return 0
        try:
            process_issue(issue)
            return 0
        except RecoverableChangesError:
            raise
        except Exception as exc:
            recovery_error = recoverable_finalization_error(issue, exc)
            if recovery_error is not None:
                raise recovery_error from exc
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
            try:
                recovery = reconcile_stale_run()
            except ActiveOrphanError:
                time.sleep(interval)
                continue
            if recovery is not None:
                try:
                    recover_changes(recovery)
                except KeyboardInterrupt as exc:
                    recovery_error = recoverable_interruption_error(recovery, exc)
                    if recovery_error is not None:
                        raise recovery_error from exc
                    raise
                continue
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
            except RecoverableChangesError:
                raise
            except KeyboardInterrupt as exc:
                recovery_error = recoverable_finalization_error(issue, exc)
                if recovery_error is None:
                    context = recorded_status_context(issue)
                    if context is not None:
                        recovery_error = recoverable_interruption_error(context, exc)
                if recovery_error is not None:
                    raise recovery_error from exc
                record_issue_failure(
                    issue, RuntimeError("Controller interrupted during task processing")
                )
                return 1
            except Exception as exc:
                recovery_error = recoverable_finalization_error(issue, exc)
                if recovery_error is not None:
                    raise recovery_error from exc
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
    modes.add_argument(
        "--confirm-recovery",
        action="store_true",
        help="Explicitly confirm and finalize a stopped child's uncommitted scope",
    )
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
    if args.confirm_recovery:
        return confirm_recovery()
    if not args.once and not args.watch:
        print("Use --once, --watch, --status, or --confirm-recovery.")
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
