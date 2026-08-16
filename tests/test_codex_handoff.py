import importlib.util
import json
import os
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
