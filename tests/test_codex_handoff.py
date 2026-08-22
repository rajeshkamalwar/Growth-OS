import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "devtools" / "codex_handoff.py"
MODULE_SPEC = importlib.util.spec_from_file_location("codex_handoff", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
codex_handoff = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(codex_handoff)


def test_now_iso_records_an_explicit_utc_offset() -> None:
    timestamp = datetime.fromisoformat(codex_handoff.now_iso())

    assert timestamp.utcoffset() == timedelta(0)


@pytest.fixture
def runtime_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    lock_file = tmp_path / "controller.lock"
    status_file = tmp_path / "status.json"
    monkeypatch.setattr(codex_handoff, "LOCK_FILE", lock_file)
    monkeypatch.setattr(codex_handoff, "STATUS_FILE", status_file)
    yield lock_file, status_file
    codex_handoff.release_lock()


@pytest.mark.parametrize(("value", "expected"), [("5", 5), ("60", 60), ("3600", 3600)])
def test_poll_interval_accepts_bounded_seconds(value: str, expected: int) -> None:
    assert codex_handoff.poll_interval(value) == expected


@pytest.mark.parametrize("value", ["not-a-number", "0", "4", "3601"])
def test_poll_interval_rejects_invalid_or_unbounded_values(value: str) -> None:
    with pytest.raises(ValueError, match="poll interval"):
        codex_handoff.poll_interval(value)


def test_live_controller_lock_blocks_second_controller(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    lock_file, _status_file = runtime_paths
    lock_file.write_text("4242", encoding="utf-8")
    monkeypatch.setattr(codex_handoff, "pid_is_running", lambda pid: pid == 4242)

    with pytest.raises(RuntimeError, match="active controller PID 4242"):
        codex_handoff.acquire_lock()

    assert lock_file.read_text(encoding="utf-8") == "4242"


@pytest.mark.parametrize("contents", ["invalid", "999999"])
def test_stale_or_malformed_controller_lock_is_recovered(
    contents: str,
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths: tuple[Path, Path],
) -> None:
    lock_file, _status_file = runtime_paths
    lock_file.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(codex_handoff, "pid_is_running", lambda _pid: False)

    codex_handoff.acquire_lock()

    assert lock_file.read_text(encoding="utf-8") == str(os.getpid())


def test_dead_implementing_pid_with_changes_becomes_recoverable(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps(
            {
                "state": "IMPLEMENTING",
                "issue": 110,
                "title": "Recover stalled child",
                "branch": "codex/issue-110-recover-stalled-child",
                "started_at": "2026-08-22T00:00:00+00:00",
                "codex_pid": 999999,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_handoff, "pid_is_running", lambda _pid: False)

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        outputs: dict[tuple[str, ...], str] = {
            ("git", "branch", "--show-current"): "codex/issue-110-recover-stalled-child\n",
            ("git", "status", "--porcelain"): " M docs/DEV-HANDOFF.md\n",
        }
        return subprocess.CompletedProcess(args, 0, stdout=outputs.get(args, ""), stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)

    context = codex_handoff.reconcile_stale_run()

    assert context == {
        "issue": 110,
        "title": "Recover stalled child",
        "branch": "codex/issue-110-recover-stalled-child",
        "started_at": "2026-08-22T00:00:00+00:00",
    }
    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "RECOVERABLE_CHANGES"


def test_legacy_recovery_establishes_manifest_after_task_ownership_is_proven(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    _lock_file, status_file = runtime_paths
    context = {
        "issue": 110,
        "title": "Recover stalled child",
        "branch": "codex/issue-110-recover-stalled-child",
        "started_at": "2026-08-22T00:00:00+00:00",
    }
    status_file.write_text(
        json.dumps({"state": "RECOVERABLE_CHANGES", **context}), encoding="utf-8"
    )
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(
        codex_handoff,
        "load_recovery_issue",
        lambda received: (
            {"number": 110, "title": "Recover stalled child", "body": "Contract"}
            if received == context
            else None
        ),
    )
    monkeypatch.setattr(codex_handoff, "working_tree_paths", lambda: ["docs/DEV-HANDOFF.md"])
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout=f"{context['branch']}\n" if args == ("git", "branch", "--show-current") else "",
            stderr="",
        ),
    )
    observed_manifest: list[str] = []

    def observe_manifest(*_args: object, **_kwargs: object) -> None:
        status = json.loads(status_file.read_text(encoding="utf-8"))
        observed_manifest.extend(status["recoverable_paths"])

    monkeypatch.setattr(codex_handoff, "finalize_changes", observe_manifest)
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: None)

    codex_handoff.recover_changes(context)

    assert observed_manifest == ["docs/DEV-HANDOFF.md"]


def test_starting_new_task_clears_previous_finalization_metadata(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps(
            {
                "state": "MERGE_BLOCKED",
                "pr_url": "https://github.com/example/repo/pull/1",
                "recoverable_paths": ["old.py"],
                "finalization_checkpoint": "PR_CREATED",
                "commit_sha": "old-sha",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(codex_handoff, "prepare_task_branch", lambda _branch: None)
    monkeypatch.setattr(codex_handoff, "label", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "run_codex_stream", lambda *_args, **_kwargs: (7, "failed"))
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="Codex exited with 7"):
        codex_handoff.process_issue({"number": 111, "title": "Next task"})

    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["issue"] == 111
    assert status["pr_url"] is None
    assert status["recoverable_paths"] is None
    assert status["finalization_checkpoint"] is None
    assert status["commit_sha"] is None


def test_dead_implementing_pid_without_changes_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps(
            {
                "state": "IMPLEMENTING",
                "issue": 110,
                "title": "Recover stalled child",
                "branch": "codex/issue-110-recover-stalled-child",
                "started_at": "2026-08-22T00:00:00+00:00",
                "codex_pid": 999999,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_handoff, "pid_is_running", lambda _pid: False)

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        output = (
            "codex/issue-110-recover-stalled-child\n"
            if args == ("git", "branch", "--show-current")
            else ""
        )
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)

    with pytest.raises(RuntimeError, match="no working-tree changes"):
        codex_handoff.reconcile_stale_run()

    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "FAILED"


def test_recovery_fails_closed_when_branch_identity_does_not_match(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps(
            {
                "state": "RECOVERABLE_CHANGES",
                "issue": 110,
                "title": "Recover stalled child",
                "branch": "codex/issue-110-recover-stalled-child",
                "started_at": "2026-08-22T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, 0, stdout="codex/different-task\n", stderr=""
        ),
    )

    with pytest.raises(RuntimeError, match="branch identity"):
        codex_handoff.reconcile_stale_run()

    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "RECOVERABLE_CHANGES"


def test_recovery_rejects_dirty_files_outside_child_captured_scope(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps({"recoverable_paths": ["devtools/codex_handoff.py"]}), encoding="utf-8"
    )
    monkeypatch.setattr(
        codex_handoff,
        "working_tree_paths",
        lambda: ["devtools/codex_handoff.py", "operator-notes.txt"],
    )

    with pytest.raises(RuntimeError, match="working-tree scope"):
        codex_handoff.validate_recovery_scope()


@pytest.mark.parametrize(
    ("checkpoint", "expected_absent"),
    [
        ("COMMITTED", "git commit"),
        ("PUSHED", "git push"),
        ("PR_CREATED", "gh pr create"),
    ],
)
def test_recovery_resumes_from_finalization_checkpoint(
    checkpoint: str,
    expected_absent: str,
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _lock_file, status_file = runtime_paths
    pr_url = "https://github.com/example/repo/pull/1"
    status_file.write_text(
        json.dumps(
            {
                "state": "RECOVERABLE_CHANGES",
                "finalization_checkpoint": checkpoint,
                "commit_sha": "task-sha",
                "pr_url": pr_url if checkpoint == "PR_CREATED" else None,
            }
        ),
        encoding="utf-8",
    )
    events: list[str] = []

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        events.append(" ".join(args))
        if args == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="task-sha\n", stderr="")
        if args[:3] == ("gh", "pr", "create"):
            return subprocess.CompletedProcess(args, 0, stdout=f"{pr_url}\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)
    monkeypatch.setattr(codex_handoff, "run_verification", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "validate_recovery_scope", lambda: None)
    monkeypatch.setattr(
        codex_handoff,
        "find_draft_pr",
        lambda _branch: pr_url if checkpoint in {"PUSHED", "PR_CREATED"} else None,
    )
    monkeypatch.setattr(
        codex_handoff,
        "run_review_fix_loop",
        lambda *_args: review_result(verdict="pass", findings=[]),
    )
    monkeypatch.setattr(codex_handoff, "mark_pr_review_passed", lambda *_args: None)
    monkeypatch.setattr(
        codex_handoff,
        "merge_reviewed_pr",
        lambda *_args: {"merged": False, "reasons": ["recovery"], "sha": None},
    )
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "label", lambda *_args, **_kwargs: None)

    codex_handoff.finalize_changes(
        {"number": 110, "title": "Recover stalled child", "body": "Contract"},
        {
            "issue": 110,
            "title": "Recover stalled child",
            "branch": "codex/issue-110-recover-stalled-child",
            "started_at": "now",
        },
        tmp_path / "recovery.log",
        allow_merge=False,
        recovering=True,
    )

    assert all(expected_absent not in event for event in events)


def test_no_output_child_is_terminated_after_bounded_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(codex_handoff, "STATUS_FILE", tmp_path / "status.json")
    command = (
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
    )

    return_code, output = codex_handoff.run_codex_stream(
        "",
        tmp_path / "hung.log",
        {"issue": 110, "title": "Task", "branch": "codex/task", "started_at": "now"},
        command=command,
        inactivity_timeout=0.05,
        termination_grace=0.1,
    )

    assert return_code != 0
    assert "inactivity timeout" in output
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "IMPLEMENTING"
    assert status["codex_pid"] is None


def test_recovery_verifies_and_finalizes_without_rerunning_implementation(
    monkeypatch: pytest.MonkeyPatch,
    runtime_paths: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _lock_file, status_file = runtime_paths
    context = {
        "issue": 110,
        "title": "Recover stalled child",
        "branch": "codex/issue-110-recover-stalled-child",
        "started_at": "2026-08-22T00:00:00+00:00",
    }
    issue = {"number": 110, "title": "Recover stalled child", "body": "Contract"}
    events: list[str] = []
    status_file.write_text(
        json.dumps(
            {
                "state": "RECOVERABLE_CHANGES",
                "recoverable_paths": ["changed.py"],
                **context,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(
        codex_handoff,
        "load_recovery_issue",
        lambda received: issue if received == context else None,
    )
    monkeypatch.setattr(
        codex_handoff,
        "finalize_changes",
        lambda received_issue, received_context, _log, *, allow_merge, recovering: events.append(
            f"finalize:{received_issue['number']}:{received_context['branch']}:{allow_merge}:"
            f"{recovering}"
        ),
    )
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: events.append("comment"))

    codex_handoff.recover_changes(context)

    assert events == [
        "comment",
        "finalize:110:codex/issue-110-recover-stalled-child:False:True",
    ]


def test_failed_child_with_changes_is_recoverable_not_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(codex_handoff, "STATUS_FILE", tmp_path / "status.json")
    monkeypatch.setattr(codex_handoff, "prepare_task_branch", lambda _branch: None)
    monkeypatch.setattr(
        codex_handoff, "run_codex_stream", lambda *_args, **_kwargs: (9, "timed out")
    )
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout=" M docs/DEV-HANDOFF.md\n" if args == ("git", "status", "--porcelain") else "",
            stderr="",
        ),
    )
    monkeypatch.setattr(codex_handoff, "label", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "working_tree_paths", lambda: ["docs/DEV-HANDOFF.md"])

    with pytest.raises(codex_handoff.RecoverableChangesError):
        codex_handoff.process_issue({"number": 110, "title": "Recover stalled child"})

    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["state"] == "RECOVERABLE_CHANGES"
    assert "preserved changes" in status["detail"]


def test_failed_fixer_with_changes_is_recoverable_and_clears_old_checkpoint(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path], tmp_path: Path
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps(
            {
                "state": "PR_CREATED",
                "pr_url": "https://github.com/example/repo/pull/1",
                "finalization_checkpoint": "PR_CREATED",
                "commit_sha": "old-sha",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)

    def fail_fixer(*_args: object, **kwargs: object) -> tuple[int, str]:
        codex_handoff.write_status(
            kwargs["state"],
            reset_recovery=True,
            recoverable_paths=["devtools/codex_handoff.py"],
            issue=16,
            title="Task",
            branch="codex/task",
            started_at="now",
        )
        return 9, "timed out"

    monkeypatch.setattr(codex_handoff, "run_codex_stream", fail_fixer)
    monkeypatch.setattr(codex_handoff, "working_tree_paths", lambda: ["devtools/codex_handoff.py"])
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args,
            0,
            stdout=" M devtools/codex_handoff.py\n"
            if args == ("git", "status", "--porcelain")
            else "",
            stderr="",
        ),
    )

    with pytest.raises(codex_handoff.RecoverableChangesError):
        codex_handoff.run_fixer(
            {"number": 16, "title": "Task", "body": "Contract"},
            [finding()],
            {"issue": 16, "title": "Task", "branch": "codex/task", "started_at": "now"},
            1,
        )

    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["state"] == "RECOVERABLE_CHANGES"
    assert status["recoverable_paths"] == ["devtools/codex_handoff.py"]
    assert status["finalization_checkpoint"] is None
    assert status["commit_sha"] is None


def test_dead_fixing_pid_with_changes_becomes_recoverable(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    _lock_file, status_file = runtime_paths
    status_file.write_text(
        json.dumps(
            {
                "state": "FIXING",
                "issue": 110,
                "title": "Recover stalled child",
                "branch": "codex/issue-110-recover-stalled-child",
                "started_at": "2026-08-22T00:00:00+00:00",
                "codex_pid": 999999,
                "recoverable_paths": ["devtools/codex_handoff.py"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_handoff, "pid_is_running", lambda _pid: False)

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        outputs = {
            ("git", "branch", "--show-current"): "codex/issue-110-recover-stalled-child\n",
            ("git", "status", "--porcelain"): " M devtools/codex_handoff.py\n",
        }
        return subprocess.CompletedProcess(args, 0, stdout=outputs.get(args, ""), stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)

    assert codex_handoff.reconcile_stale_run() is not None
    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "RECOVERABLE_CHANGES"


def test_failed_recovery_releases_controller_lock(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    lock_file, _status_file = runtime_paths
    context = {
        "issue": 110,
        "title": "Recover stalled child",
        "branch": "codex/issue-110-recover-stalled-child",
        "started_at": "2026-08-22T00:00:00+00:00",
    }
    monkeypatch.setattr(codex_handoff, "ensure_tools", lambda: None)
    monkeypatch.setattr(codex_handoff, "ensure_labels", lambda: None)
    monkeypatch.setattr(codex_handoff, "reconcile_stale_run", lambda: context)
    monkeypatch.setattr(
        codex_handoff,
        "recover_changes",
        lambda _context: (_ for _ in ()).throw(
            codex_handoff.RecoverableChangesError("verification failed")
        ),
    )

    with pytest.raises(codex_handoff.RecoverableChangesError, match="verification failed"):
        codex_handoff.run_once()

    assert not lock_file.exists()


def test_watch_polls_while_idle_and_stops_cleanly(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    lock_file, status_file = runtime_paths
    monkeypatch.setattr(codex_handoff, "ensure_tools", lambda: None)
    monkeypatch.setattr(codex_handoff, "ensure_labels", lambda: None)
    monkeypatch.setattr(codex_handoff, "clean_tree_required", lambda: None)
    monkeypatch.setattr(codex_handoff, "next_issue", lambda: None)
    monkeypatch.setattr(
        codex_handoff.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    result = codex_handoff.run_watch(30)

    assert result == 0
    assert not lock_file.exists()
    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "STOPPED"


def test_watch_rechecks_clean_tree_after_idle_poll(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    monkeypatch.setattr(codex_handoff, "ensure_tools", lambda: None)
    monkeypatch.setattr(codex_handoff, "ensure_labels", lambda: None)
    clean_checks = 0

    def check_clean_tree() -> None:
        nonlocal clean_checks
        clean_checks += 1

    issue_checks = 0

    def select_issue() -> None:
        nonlocal issue_checks
        issue_checks += 1
        if issue_checks == 2:
            raise KeyboardInterrupt
        return None

    monkeypatch.setattr(codex_handoff, "clean_tree_required", check_clean_tree)
    monkeypatch.setattr(codex_handoff, "next_issue", select_issue)
    monkeypatch.setattr(codex_handoff.time, "sleep", lambda _seconds: None)

    assert codex_handoff.run_watch(30) == 0
    assert clean_checks == 2


def test_watch_processes_ready_issue_then_continues_polling(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    monkeypatch.setattr(codex_handoff, "ensure_tools", lambda: None)
    monkeypatch.setattr(codex_handoff, "ensure_labels", lambda: None)
    monkeypatch.setattr(codex_handoff, "clean_tree_required", lambda: None)
    issues = iter([{"number": 11, "title": "Task"}, None])
    monkeypatch.setattr(codex_handoff, "next_issue", lambda: next(issues))
    processed: list[int] = []
    monkeypatch.setattr(
        codex_handoff,
        "process_issue",
        lambda issue: processed.append(int(issue["number"])),
    )
    monkeypatch.setattr(
        codex_handoff.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    result = codex_handoff.run_watch(30)

    assert result == 0
    assert processed == [11]


def test_watch_records_issue_failure_and_stops_before_next_task(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    monkeypatch.setattr(codex_handoff, "ensure_tools", lambda: None)
    monkeypatch.setattr(codex_handoff, "ensure_labels", lambda: None)
    monkeypatch.setattr(codex_handoff, "clean_tree_required", lambda: None)
    selected = {"number": 11, "title": "Task"}
    next_calls = 0

    def next_issue() -> dict[str, object]:
        nonlocal next_calls
        next_calls += 1
        return selected

    monkeypatch.setattr(codex_handoff, "next_issue", next_issue)
    monkeypatch.setattr(
        codex_handoff,
        "process_issue",
        lambda _issue: (_ for _ in ()).throw(RuntimeError("implementation failed")),
    )
    labels: list[tuple[int, str | None, str | None]] = []
    comments: list[str] = []
    monkeypatch.setattr(
        codex_handoff,
        "label",
        lambda number, add=None, remove=None: labels.append((number, add, remove)),
    )
    monkeypatch.setattr(
        codex_handoff,
        "comment",
        lambda _number, text: comments.append(text),
    )

    with pytest.raises(RuntimeError, match="implementation failed"):
        codex_handoff.run_watch(30)

    assert next_calls == 1
    assert labels == [(11, codex_handoff.FAILED_LABEL, codex_handoff.RUNNING_LABEL)]
    assert "implementation failed" in comments[0]


def test_run_once_preserves_idle_behavior_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch, runtime_paths: tuple[Path, Path]
) -> None:
    lock_file, status_file = runtime_paths
    monkeypatch.setattr(codex_handoff, "ensure_tools", lambda: None)
    monkeypatch.setattr(codex_handoff, "ensure_labels", lambda: None)
    monkeypatch.setattr(codex_handoff, "clean_tree_required", lambda: None)
    monkeypatch.setattr(codex_handoff, "next_issue", lambda: None)

    assert codex_handoff.run_once() == 0
    assert not lock_file.exists()
    assert json.loads(status_file.read_text(encoding="utf-8"))["state"] == "IDLE"


def review_result(*, verdict: str, findings: list[dict[str, object]]) -> dict[str, object]:
    return {
        "verdict": verdict,
        "summary": "Independent review completed.",
        "findings": findings,
    }


def finding(title: str = "Fix the defect") -> dict[str, object]:
    return {
        "priority": "P1",
        "title": title,
        "detail": "The behavior violates the issue contract.",
        "path": "devtools/codex_handoff.py",
        "line": 100,
    }


def auto_merge_body(**overrides: object) -> str:
    assessment: dict[str, object] = {
        "risk": "low",
        "roadmap_authorized": True,
        "reversible": True,
        "production_deployment": False,
        "external_customer_side_effect": False,
        "stop_categories": [],
    }
    assessment.update(overrides)
    return (
        "## Goal\n\nImplement bounded work.\n\n"
        "## Auto-merge assessment\n\n```json\n"
        f"{json.dumps(assessment)}\n"
        "```\n"
    )


def test_parse_auto_merge_assessment_accepts_exact_contract() -> None:
    assessment = codex_handoff.parse_auto_merge_assessment(auto_merge_body(risk="medium"))

    assert assessment["risk"] == "medium"
    assert assessment["roadmap_authorized"] is True


@pytest.mark.parametrize(
    "body",
    [
        "No assessment",
        auto_merge_body() + auto_merge_body(),
        auto_merge_body(unknown=True),
        auto_merge_body(risk="high"),
        auto_merge_body(roadmap_authorized=False),
        auto_merge_body(reversible=False),
        auto_merge_body(production_deployment=True),
        auto_merge_body(external_customer_side_effect=True),
        auto_merge_body(stop_categories=["billing"]),
    ],
)
def test_auto_merge_policy_blocks_invalid_or_ineligible_assessment(body: str) -> None:
    reasons = codex_handoff.auto_merge_policy_reasons(
        {"number": 18, "title": "Task", "body": body},
        ["devtools/codex_handoff.py", "tests/test_codex_handoff.py"],
    )

    assert reasons


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md",
        "src/growth_os/AGENTS.md",
        ".github/workflows/deploy.yml",
        "alembic/versions/999_destructive.py",
        "src/growth_os/auth/service.py",
        "src/growth_os/billing.py",
        "infra/production.tf",
        "website/index.html",
        ".env.production",
        "config/.env.production",
        "src/growth_os/authz.py",
        "db/migrations/999_drop.py",
        "k8s/api.yaml",
        "scripts/publish.py",
        "email/outreach_service.py",
    ],
)
def test_auto_merge_policy_blocks_protected_paths(path: str) -> None:
    reasons = codex_handoff.auto_merge_policy_reasons(
        {"number": 18, "title": "Task", "body": auto_merge_body()},
        [path],
    )

    assert any("path" in reason.lower() for reason in reasons)


def test_auto_merge_policy_allows_bounded_development_paths() -> None:
    reasons = codex_handoff.auto_merge_policy_reasons(
        {"number": 18, "title": "Task", "body": auto_merge_body(risk="medium")},
        [
            "devtools/codex_handoff.py",
            "tests/test_codex_handoff.py",
            "docs/CURRENT-TASK.md",
            "docs/DECISIONS.md",
            "docs/DEV-HANDOFF.md",
        ],
    )

    assert reasons == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "CLOSED"),
        ("baseRefName", "release"),
        ("headRefName", "codex/other"),
        ("headRefOid", "different"),
        ("mergeable", "CONFLICTING"),
        ("reviewDecision", "CHANGES_REQUESTED"),
        ("reviewDecision", "REVIEW_REQUIRED"),
    ],
)
def test_validate_pr_for_merge_rejects_stale_or_blocking_metadata(
    field: str, value: object
) -> None:
    metadata: dict[str, object] = {
        "number": 19,
        "url": "https://github.com/example/repo/pull/19",
        "state": "OPEN",
        "isDraft": True,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "codex/task",
        "headRefOid": "reviewed-sha",
        "reviewDecision": None,
        "labels": [{"name": "codex-review-passed"}],
    }
    metadata[field] = value

    reasons = codex_handoff.validate_pr_for_merge(
        metadata, expected_branch="codex/task", reviewed_head="reviewed-sha"
    )

    assert reasons


def test_validate_pr_for_merge_accepts_exact_reviewed_head() -> None:
    metadata: dict[str, object] = {
        "number": 19,
        "url": "https://github.com/example/repo/pull/19",
        "state": "OPEN",
        "isDraft": True,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "codex/task",
        "headRefOid": "reviewed-sha",
        "reviewDecision": None,
        "labels": [{"name": "codex-review-passed"}],
    }

    assert (
        codex_handoff.validate_pr_for_merge(
            metadata, expected_branch="codex/task", reviewed_head="reviewed-sha"
        )
        == []
    )


def test_unresolved_review_threads_block_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": True}, {"isResolved": False}],
                        "pageInfo": {"hasNextPage": False},
                    }
                }
            }
        }
    }
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    assert codex_handoff._has_unresolved_review_threads(19) is True


def test_malformed_review_thread_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(args, 0, stdout="{}", stderr=""),
    )

    with pytest.raises(RuntimeError, match="review-thread metadata"):
        codex_handoff._has_unresolved_review_threads(19)


def test_paginated_review_threads_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [{"isResolved": True}],
                        "pageInfo": {"hasNextPage": True},
                    }
                }
            }
        }
    }
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *args, **_kwargs: subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    assert codex_handoff._has_unresolved_review_threads(19) is True


def test_merge_reviewed_pr_blocks_without_calling_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ("git", "diff", "--no-renames", "--name-only", "-z", "origin/main...HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="AGENTS.md\0", stderr="")
        if args[:3] == ("gh", "issue", "view"):
            payload = {
                "number": 18,
                "title": "Task",
                "body": auto_merge_body(),
                "author": {"login": codex_handoff.OWNER},
                "state": "OPEN",
                "url": "https://github.com/example/repo/issues/18",
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)

    outcome = codex_handoff.merge_reviewed_pr(
        {"number": 18, "title": "Task", "body": auto_merge_body()},
        "codex/task",
        "https://github.com/example/repo/pull/19",
        "reviewed-sha",
        {"issue": 18, "title": "Task", "branch": "codex/task", "started_at": "now"},
    )

    assert outcome["merged"] is False
    assert (
        "git",
        "diff",
        "--no-renames",
        "--name-only",
        "-z",
        "origin/main...HEAD",
    ) in commands
    assert not any(command[:3] == ("gh", "pr", "merge") for command in commands)


def test_merge_reviewed_pr_uses_exact_head_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    ready = False
    metadata = {
        "number": 19,
        "url": "https://github.com/example/repo/pull/19",
        "state": "OPEN",
        "isDraft": True,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "codex/task",
        "headRefOid": "reviewed-sha",
        "reviewDecision": None,
        "labels": [{"name": "codex-review-passed"}],
    }

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal ready
        commands.append(args)
        if args == ("git", "diff", "--no-renames", "--name-only", "-z", "origin/main...HEAD"):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="devtools/codex_handoff.py\0tests/test_codex_handoff.py\0",
                stderr="",
            )
        if args[:3] == ("gh", "issue", "view"):
            payload = {
                "number": 18,
                "title": "Task",
                "body": auto_merge_body(risk="medium"),
                "author": {"login": codex_handoff.OWNER},
                "state": "OPEN",
                "url": "https://github.com/example/repo/issues/18",
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "pr", "view"):
            if args[-1] == "state,mergeCommit,url":
                payload = {
                    "state": "MERGED",
                    "mergeCommit": {"oid": "merge-sha"},
                    "url": metadata["url"],
                }
            else:
                payload = {**metadata, "isDraft": not ready}
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "api", "graphql"):
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=json.dumps(
                    {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "reviewThreads": {
                                        "nodes": [],
                                        "pageInfo": {"hasNextPage": False},
                                    }
                                }
                            }
                        }
                    }
                ),
                stderr="",
            )
        if args[:3] == ("gh", "pr", "merge"):
            return subprocess.CompletedProcess(args, 0, stdout="merged", stderr="")
        if args[:3] == ("gh", "pr", "ready"):
            ready = True
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)
    monkeypatch.setattr(codex_handoff, "write_status", lambda *_args, **_kwargs: None)

    outcome = codex_handoff.merge_reviewed_pr(
        {"number": 18, "title": "Task", "body": auto_merge_body(risk="medium")},
        "codex/task",
        "https://github.com/example/repo/pull/19",
        "reviewed-sha",
        {"issue": 18, "title": "Task", "branch": "codex/task", "started_at": "now"},
    )

    merge_command = next(command for command in commands if command[:3] == ("gh", "pr", "merge"))
    assert outcome["merged"] is True
    assert "--squash" in merge_command
    assert merge_command[merge_command.index("--match-head-commit") + 1] == "reviewed-sha"
    assert "--admin" not in merge_command
    assert "--force" not in merge_command


def test_merge_reviewed_pr_uses_fresh_issue_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ("git", "diff", "--no-renames", "--name-only", "-z", "origin/main...HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="devtools/tool.py\0", stderr="")
        if args[:3] == ("gh", "issue", "view"):
            payload = {
                "number": 18,
                "title": "Task",
                "body": "Authorization removed",
                "author": {"login": codex_handoff.OWNER},
                "state": "OPEN",
                "url": "https://github.com/example/repo/issues/18",
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)

    outcome = codex_handoff.merge_reviewed_pr(
        {"number": 18, "title": "Task", "body": auto_merge_body()},
        "codex/task",
        "https://github.com/example/repo/pull/19",
        "reviewed-sha",
        {"issue": 18, "title": "Task", "branch": "codex/task", "started_at": "now"},
    )

    assert outcome["merged"] is False
    assert not any(command[:3] == ("gh", "pr", "merge") for command in commands)


def test_merge_reviewed_pr_blocks_review_race_after_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = False
    thread_checks = 0
    commands: list[tuple[str, ...]] = []
    metadata = {
        "number": 19,
        "url": "https://github.com/example/repo/pull/19",
        "state": "OPEN",
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "codex/task",
        "headRefOid": "reviewed-sha",
        "reviewDecision": None,
        "labels": [{"name": "codex-review-passed"}],
    }

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal ready, thread_checks
        commands.append(args)
        if args == ("git", "diff", "--no-renames", "--name-only", "-z", "origin/main...HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="devtools/tool.py\0", stderr="")
        if args[:3] == ("gh", "issue", "view"):
            payload = {
                "number": 18,
                "title": "Task",
                "body": auto_merge_body(),
                "author": {"login": codex_handoff.OWNER},
                "state": "OPEN",
                "url": "https://github.com/example/repo/issues/18",
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "pr", "view"):
            return subprocess.CompletedProcess(
                args, 0, stdout=json.dumps({**metadata, "isDraft": not ready}), stderr=""
            )
        if args[:3] == ("gh", "api", "graphql"):
            thread_checks += 1
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [{"isResolved": thread_checks == 1}],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "pr", "ready"):
            ready = True
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)

    outcome = codex_handoff.merge_reviewed_pr(
        {"number": 18, "title": "Task", "body": auto_merge_body()},
        "codex/task",
        "https://github.com/example/repo/pull/19",
        "reviewed-sha",
        {"issue": 18, "title": "Task", "branch": "codex/task", "started_at": "now"},
    )

    assert outcome["merged"] is False
    assert any("final validation" in reason for reason in outcome["reasons"])
    assert not any(command[:3] == ("gh", "pr", "merge") for command in commands)


def test_merge_rejection_for_open_pr_is_policy_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []
    metadata = {
        "number": 19,
        "url": "https://github.com/example/repo/pull/19",
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefName": "codex/task",
        "headRefOid": "reviewed-sha",
        "reviewDecision": None,
        "labels": [{"name": "codex-review-passed"}],
    }

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        if args == ("git", "diff", "--no-renames", "--name-only", "-z", "origin/main...HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="devtools/tool.py\0", stderr="")
        if args[:3] == ("gh", "issue", "view"):
            payload = {
                "number": 18,
                "title": "Task",
                "body": auto_merge_body(),
                "author": {"login": codex_handoff.OWNER},
                "state": "OPEN",
                "url": "https://github.com/example/repo/issues/18",
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "api", "graphql"):
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": False},
                            }
                        }
                    }
                }
            }
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "pr", "merge"):
            raise subprocess.CalledProcessError(1, args, stderr="head changed")
        if args[:3] == ("gh", "pr", "view") and args[-1] == "state,mergeCommit,url":
            payload = {"state": "OPEN", "mergeCommit": None, "url": metadata["url"]}
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")
        if args[:3] == ("gh", "pr", "view"):
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(metadata), stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)
    monkeypatch.setattr(codex_handoff, "write_status", lambda *_args, **_kwargs: None)

    outcome = codex_handoff.merge_reviewed_pr(
        {"number": 18, "title": "Task", "body": auto_merge_body()},
        "codex/task",
        "https://github.com/example/repo/pull/19",
        "reviewed-sha",
        {"issue": 18, "title": "Task", "branch": "codex/task", "started_at": "now"},
    )

    assert outcome["merged"] is False
    assert any("rejected" in reason for reason in outcome["reasons"])


def test_load_review_result_accepts_clean_pass(tmp_path: Path) -> None:
    result_file = tmp_path / "review.json"
    result_file.write_text(json.dumps(review_result(verdict="pass", findings=[])), encoding="utf-8")

    result = codex_handoff.load_review_result(result_file)

    assert result["verdict"] == "pass"
    assert result["findings"] == []


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"verdict": "pass", "summary": "ok"}),
        json.dumps(review_result(verdict="pass", findings=[finding()])),
        json.dumps(review_result(verdict="changes_requested", findings=[])),
        json.dumps(review_result(verdict="approve", findings=[])),
        json.dumps(review_result(verdict=[], findings=[])),
        json.dumps(
            review_result(
                verdict="changes_requested",
                findings=[{**finding(), "priority": "P4"}],
            )
        ),
        json.dumps(
            review_result(
                verdict="changes_requested",
                findings=[{**finding(), "priority": []}],
            )
        ),
    ],
)
def test_load_review_result_rejects_invalid_contract(payload: str, tmp_path: Path) -> None:
    result_file = tmp_path / "review.json"
    result_file.write_text(payload, encoding="utf-8")

    with pytest.raises(RuntimeError, match="review result"):
        codex_handoff.load_review_result(result_file)


def test_load_review_result_rejects_oversized_output(tmp_path: Path) -> None:
    result_file = tmp_path / "review.json"
    result_file.write_text("x" * 65_537, encoding="utf-8")

    with pytest.raises(RuntimeError, match="review result.*large"):
        codex_handoff.load_review_result(result_file)


def test_review_fix_loop_passes_without_starting_fixer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = {"number": 16, "title": "Task", "body": "Contract"}
    status_context = {
        "issue": 16,
        "title": "Task",
        "branch": "codex/task",
        "started_at": "now",
    }
    monkeypatch.setattr(
        codex_handoff,
        "run_reviewer",
        lambda _issue, _context, _round: review_result(verdict="pass", findings=[]),
    )
    fixer_rounds: list[int] = []
    monkeypatch.setattr(
        codex_handoff,
        "run_fixer",
        lambda _issue, _findings, _context, fix_round: fixer_rounds.append(fix_round),
    )

    result = codex_handoff.run_review_fix_loop(issue, status_context)

    assert result["verdict"] == "pass"
    assert fixer_rounds == []


def test_review_fix_loop_fixes_verifies_commits_and_reviews_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = {"number": 16, "title": "Task", "body": "Contract"}
    status_context = {
        "issue": 16,
        "title": "Task",
        "branch": "codex/task",
        "started_at": "now",
    }
    results = iter(
        [
            review_result(verdict="changes_requested", findings=[finding()]),
            review_result(verdict="pass", findings=[]),
        ]
    )
    monkeypatch.setattr(
        codex_handoff, "run_reviewer", lambda _issue, _context, _round: next(results)
    )
    events: list[tuple[str, int]] = []
    monkeypatch.setattr(
        codex_handoff,
        "run_fixer",
        lambda _issue, _findings, _context, fix_round: events.append(("fix", fix_round)),
    )
    monkeypatch.setattr(
        codex_handoff,
        "run_verification",
        lambda _issue, _context, pass_number: events.append(("verify", pass_number)),
    )
    monkeypatch.setattr(
        codex_handoff,
        "commit_review_fix",
        lambda _issue, fix_round, _context: events.append(("commit", fix_round)),
    )

    result = codex_handoff.run_review_fix_loop(issue, status_context)

    assert result["verdict"] == "pass"
    assert events == [("fix", 1), ("verify", 2), ("commit", 1)]


def test_review_fix_loop_stops_after_two_fix_rounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = {"number": 16, "title": "Task", "body": "Contract"}
    status_context = {
        "issue": 16,
        "title": "Task",
        "branch": "codex/task",
        "started_at": "now",
    }
    review_rounds: list[int] = []

    def request_changes(
        _issue: dict[str, object], _context: dict[str, object], review_round: int
    ) -> dict[str, object]:
        review_rounds.append(review_round)
        return review_result(verdict="changes_requested", findings=[finding()])

    fixer_rounds: list[int] = []
    monkeypatch.setattr(codex_handoff, "run_reviewer", request_changes)
    monkeypatch.setattr(
        codex_handoff,
        "run_fixer",
        lambda _issue, _findings, _context, fix_round: fixer_rounds.append(fix_round),
    )
    monkeypatch.setattr(codex_handoff, "run_verification", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "commit_review_fix", lambda *_args: None)

    with pytest.raises(RuntimeError, match="two fix rounds"):
        codex_handoff.run_review_fix_loop(issue, status_context)

    assert review_rounds == [1, 2, 3]
    assert fixer_rounds == [1, 2]


def test_run_reviewer_stops_on_command_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(codex_handoff, "REVIEW_SCHEMA_RUNTIME", tmp_path / "review.schema.json")
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []

    def fail_reviewer(*_args: object, **kwargs: object) -> tuple[int, str]:
        commands.append(kwargs["command"])
        environments.append(kwargs["env"])
        return 7, "review process failed"

    monkeypatch.setattr(
        codex_handoff,
        "run_codex_stream",
        fail_reviewer,
    )

    with pytest.raises(RuntimeError, match="Reviewer exited with 7"):
        codex_handoff.run_reviewer(
            {"number": 16, "title": "Task", "body": "Contract"},
            {"issue": 16, "title": "Task", "branch": "codex/task", "started_at": "now"},
            1,
        )

    assert commands[0][:4] == ("codex", "exec", "--sandbox", "read-only")
    assert "review" not in commands[0]
    assert "--add-dir" in commands[0]
    assert not Path(environments[0]["TMPDIR"]).exists()


def test_run_fixer_stops_when_no_changes_are_produced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(
        codex_handoff,
        "run_codex_stream",
        lambda *_args, **_kwargs: (0, "fixer completed"),
    )
    monkeypatch.setattr(
        codex_handoff,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="fixer produced no changes"):
        codex_handoff.run_fixer(
            {"number": 16, "title": "Task", "body": "Contract"},
            [finding()],
            {"issue": 16, "title": "Task", "branch": "codex/task", "started_at": "now"},
            1,
        )


def test_run_verification_fails_closed_on_first_failed_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, runtime_paths: tuple[Path, Path]
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setenv("GROWTH_OS_DATABASE_URL", "postgresql://production.example/growth_os")
    commands: list[tuple[str, ...]] = []
    environments: list[dict[str, str]] = []

    def fail_pytest(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(args)
        environments.append(kwargs["env"])
        return subprocess.CompletedProcess(
            args,
            1 if args[:2] == (".venv/bin/python", "-m") and "pytest" in args else 0,
            stdout="verification output",
            stderr="verification error",
        )

    monkeypatch.setattr(codex_handoff, "run", fail_pytest)

    with pytest.raises(RuntimeError, match="Local verification failed.*pytest"):
        codex_handoff.run_verification(
            {"number": 16, "title": "Task", "body": "Contract"},
            {"issue": 16, "title": "Task", "branch": "codex/task", "started_at": "now"},
            1,
        )

    assert all(isinstance(argument, str) for command in commands for argument in command)
    assert all(
        environment["GROWTH_OS_DATABASE_URL"] == codex_handoff.LOCAL_DATABASE_URL
        for environment in environments
    )


def test_process_issue_verifies_before_pr_then_completes_independent_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(codex_handoff, "prepare_task_branch", lambda _branch: None)
    monkeypatch.setattr(
        codex_handoff,
        "run_codex_stream",
        lambda *_args, **_kwargs: (0, "implementation completed"),
    )
    events: list[str] = []

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args == ("git", "status", "--porcelain"):
            return subprocess.CompletedProcess(args, 0, stdout=" M changed.py\n", stderr="")
        if args[:3] == ("git", "commit", "-m"):
            events.append("commit")
        if args[:3] == ("gh", "pr", "create"):
            events.append("pr")
            return subprocess.CompletedProcess(
                args, 0, stdout="https://github.com/example/repo/pull/1\n", stderr=""
            )
        if args[:3] == ("gh", "pr", "edit"):
            events.append("mark-pr")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)
    monkeypatch.setattr(
        codex_handoff,
        "run_verification",
        lambda _issue, _context, _pass_number: events.append("verify"),
    )
    monkeypatch.setattr(
        codex_handoff,
        "run_review_fix_loop",
        lambda _issue, _context: (
            events.append("review") or review_result(verdict="pass", findings=[])
        ),
    )
    labels: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(
        codex_handoff,
        "label",
        lambda _number, add=None, remove=None: labels.append((add, remove)),
    )
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "write_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        codex_handoff,
        "merge_reviewed_pr",
        lambda *_args: {"merged": False, "reasons": ["human merge"], "sha": None},
    )

    original_run = codex_handoff.run

    def run_with_head(*args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="reviewed-sha\n", stderr="")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(codex_handoff, "run", run_with_head)

    codex_handoff.process_issue({"number": 16, "title": "Task", "body": "Contract"})

    assert events == ["verify", "commit", "pr", "review", "mark-pr"]
    assert (codex_handoff.REVIEWED_LABEL, None) in labels
    assert labels[-1] == (codex_handoff.DONE_LABEL, codex_handoff.RUNNING_LABEL)


def test_process_issue_does_not_mark_pr_when_review_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(codex_handoff, "LOG_DIR", tmp_path)
    monkeypatch.setattr(codex_handoff, "prepare_task_branch", lambda _branch: None)
    monkeypatch.setattr(
        codex_handoff,
        "run_codex_stream",
        lambda *_args, **_kwargs: (0, "implementation completed"),
    )
    pr_marked = False

    def fake_run(*args: str, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal pr_marked
        if args == ("git", "status", "--porcelain"):
            return subprocess.CompletedProcess(args, 0, stdout=" M changed.py\n", stderr="")
        if args[:3] == ("gh", "pr", "create"):
            return subprocess.CompletedProcess(
                args, 0, stdout="https://github.com/example/repo/pull/1\n", stderr=""
            )
        if args[:3] == ("gh", "pr", "edit"):
            pr_marked = True
        if args == ("git", "rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, stdout="task-sha\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_handoff, "run", fake_run)
    monkeypatch.setattr(codex_handoff, "run_verification", lambda *_args: None)
    monkeypatch.setattr(
        codex_handoff,
        "run_review_fix_loop",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("review failed")),
    )
    labels: list[tuple[str | None, str | None]] = []
    monkeypatch.setattr(
        codex_handoff,
        "label",
        lambda _number, add=None, remove=None: labels.append((add, remove)),
    )
    monkeypatch.setattr(codex_handoff, "comment", lambda *_args: None)
    monkeypatch.setattr(codex_handoff, "write_status", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="review failed"):
        codex_handoff.process_issue({"number": 16, "title": "Task", "body": "Contract"})

    assert not pr_marked
    assert all(add != codex_handoff.DONE_LABEL for add, _remove in labels)
    assert all(add != codex_handoff.REVIEWED_LABEL for add, _remove in labels)
