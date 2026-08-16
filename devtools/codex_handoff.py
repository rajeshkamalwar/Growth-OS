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
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = os.environ.get("GROWTH_OS_REPO", "rajeshkamalwar/Growth-OS")
OWNER = os.environ.get("GROWTH_OS_OWNER", "rajeshkamalwar")
READY_LABEL = "codex-ready"
RUNNING_LABEL = "codex-running"
DONE_LABEL = "codex-pr-open"
FAILED_LABEL = "codex-failed"
LOCK_FILE = Path(".git/codex-handoff.lock")


def run(*args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        capture_output=True,
        check=check,
    )


def gh_json(*args: str):
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
            ["gh", "label", "create", name, "--repo", REPO, "--description", description, "--force"],
            capture_output=True,
            text=True,
        )


def clean_tree_required() -> None:
    status = run("git", "status", "--porcelain").stdout.strip()
    if status:
        raise RuntimeError("Working tree is not clean. Commit/stash changes before running the controller.")


def acquire_lock() -> None:
    if LOCK_FILE.exists():
        raise RuntimeError(f"Controller lock exists: {LOCK_FILE}")
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def next_issue() -> dict | None:
    issues = gh_json(
        "issue", "list", "--repo", REPO,
        "--state", "open", "--label", READY_LABEL,
        "--limit", "1", "--json", "number,title,body,author,url"
    )
    if not issues:
        return None
    issue = issues[0]
    author = ((issue.get("author") or {}).get("login") or "").lower()
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


def process_issue(issue: dict) -> None:
    number = int(issue["number"])
    title = issue["title"]
    body = issue.get("body") or ""
    branch = f"codex/issue-{number}-{slugify(title)}"

    label(number, add=RUNNING_LABEL, remove=READY_LABEL)
    comment(number, f"Local Codex controller started this task on branch `{branch}`.")

    run("git", "fetch", "origin", "main")
    run("git", "checkout", "main")
    run("git", "pull", "--ff-only", "origin", "main")
    run("git", "checkout", "-b", branch)

    prompt = f"""Read AGENTS.md and all repository source-of-truth documents before making changes.

Execute GitHub issue #{number}: {title}

Issue body:
{body}

Hard requirements:
- Obey AGENTS.md and repository safety gates.
- Stay strictly within this issue's scope.
- Do not merge, deploy, modify production, or weaken safety controls.
- Run relevant tests/checks before finishing.
- Leave the working tree containing only justified task changes.
- If the issue conflicts with source-of-truth docs or requires a stop/approval condition, do not bypass it; exit with a clear explanation.
"""

    result = run("codex", "exec", "--sandbox", "workspace-write", input_text=prompt, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Codex exited with {result.returncode}:\n{result.stderr[-3000:]}")

    changed = run("git", "status", "--porcelain").stdout.strip()
    if not changed:
        comment(number, "Codex completed without repository changes. No PR was created.")
        label(number, add=DONE_LABEL, remove=RUNNING_LABEL)
        return

    run("git", "add", "-A")
    run("git", "commit", "-m", f"codex: resolve issue #{number}")
    run("git", "push", "-u", "origin", branch)

    pr_body = (
        f"Automated local Codex handoff for #{number}.\n\n"
        "This PR was created by the self-hosted controller. It is intentionally a draft. "
        "It must be reviewed before merge. No production deployment is authorized."
    )
    pr_url = run(
        "gh", "pr", "create", "--repo", REPO,
        "--base", "main", "--head", branch, "--draft",
        "--title", f"{title}", "--body", pr_body,
    ).stdout.strip()

    comment(number, f"Codex completed and opened draft PR: {pr_url}")
    label(number, add=DONE_LABEL, remove=RUNNING_LABEL)


def run_once() -> int:
    ensure_tools()
    ensure_labels()
    clean_tree_required()
    acquire_lock()
    try:
        issue = next_issue()
        if issue is None:
            print("No codex-ready issues found.")
            return 0
        try:
            process_issue(issue)
            return 0
        except Exception as exc:
            number = int(issue["number"])
            label(number, add=FAILED_LABEL, remove=RUNNING_LABEL)
            comment(number, f"Local Codex controller failed:\n\n```text\n{str(exc)[-3000:]}\n```")
            raise
    finally:
        release_lock()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one ready issue and exit")
    args = parser.parse_args()
    if not args.once:
        print("For safety, this first version only supports --once. Use a scheduler/launchd to invoke it repeatedly.")
        return 2
    try:
        return run_once()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
