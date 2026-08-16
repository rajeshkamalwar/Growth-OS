import importlib.util
import json
import os
import subprocess
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
        lambda _issue, fix_round: events.append(("commit", fix_round)),
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
