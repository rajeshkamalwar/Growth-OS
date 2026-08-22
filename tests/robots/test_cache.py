import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone, tzinfo
from enum import StrEnum
from pathlib import Path

import pytest

from growth_os import robots as robots_package
from growth_os.robots import (
    RobotsCacheDecision,
    RobotsCacheError,
    RobotsCacheErrorCode,
    RobotsCacheReason,
    evaluate_robots_cache,
)
from growth_os.robots import cache as cache_module

UTC = timezone.utc  # noqa: UP017
BASE = datetime(2026, 8, 17, 12, tzinfo=UTC)


class DatetimeSubclass(datetime):
    pass


class ZeroOffsetTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)


def assert_invalid(**kwargs: object) -> RobotsCacheError:
    with pytest.raises(RobotsCacheError) as caught:
        evaluate_robots_cache(**kwargs)  # type: ignore[arg-type]
    assert caught.value.code is RobotsCacheErrorCode.INVALID_INPUT
    assert str(caught.value) == "Robots cache policy failed: invalid_input"
    assert caught.value.args == ("Robots cache policy failed: invalid_input",)
    return caught.value


def test_public_contract_is_exact_exported_immutable_and_equality_comparable() -> None:
    assert robots_package.__all__ == [
        "BoundRobotsDecision",
        "CachedRobotsOutcome",
        "RobotsAccessDecision",
        "RobotsAccessReason",
        "RobotsBindingError",
        "RobotsBindingErrorCode",
        "RobotsCacheDecision",
        "RobotsCacheError",
        "RobotsCacheErrorCode",
        "RobotsCacheReason",
        "RobotsCacheSelectionDecision",
        "RobotsCacheSelectionError",
        "RobotsCacheSelectionErrorCode",
        "RobotsCacheSelectionReason",
        "RobotsDecision",
        "RobotsDecisionReason",
        "RobotsGateDecision",
        "RobotsGateError",
        "RobotsGateErrorCode",
        "RobotsGateReason",
        "RobotsPolicyError",
        "RobotsPolicyErrorCode",
        "evaluate_bound_robots",
        "evaluate_robots",
        "evaluate_robots_access",
        "evaluate_robots_cache",
        "evaluate_robots_gate",
        "select_cached_robots",
    ]
    assert issubclass(RobotsCacheReason, StrEnum)
    assert list(RobotsCacheReason) == [
        RobotsCacheReason.MISSING,
        RobotsCacheReason.FRESH,
        RobotsCacheReason.EXPIRED,
    ]
    assert list(RobotsCacheErrorCode) == [RobotsCacheErrorCode.INVALID_INPUT]
    assert [field.name for field in fields(RobotsCacheDecision)] == [
        "reusable",
        "reason",
        "stored_at",
        "expires_at",
    ]
    assert str(inspect.signature(evaluate_robots_cache)) == (
        "(*, stored_at: 'datetime | None', now: 'datetime') -> 'RobotsCacheDecision'"
    )
    result = evaluate_robots_cache(stored_at=BASE, now=BASE)
    assert result == RobotsCacheDecision(
        True, RobotsCacheReason.FRESH, BASE, BASE + timedelta(hours=24)
    )
    with pytest.raises(FrozenInstanceError):
        result.reusable = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        evaluate_robots_cache(BASE, BASE)  # type: ignore[misc]


@pytest.mark.parametrize("now", [None, 1, "2026-08-17", object()])
def test_now_rejects_non_datetimes(now: object) -> None:
    assert_invalid(stored_at=None, now=now)


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 17, 12),
        datetime(2026, 8, 17, 12, tzinfo=ZeroOffsetTimezone()),
        DatetimeSubclass(2026, 8, 17, 12, tzinfo=UTC),
    ],
)
def test_now_requires_an_exact_canonical_utc_datetime(value: datetime) -> None:
    assert_invalid(stored_at=None, now=value)


@pytest.mark.parametrize(
    "stored_at",
    [
        1,
        "2026-08-17",
        datetime(2026, 8, 17, 12),
        datetime(2026, 8, 17, 12, tzinfo=ZeroOffsetTimezone()),
        DatetimeSubclass(2026, 8, 17, 12, tzinfo=UTC),
    ],
)
def test_stored_at_requires_null_or_an_exact_canonical_utc_datetime(stored_at: object) -> None:
    assert_invalid(stored_at=stored_at, now=BASE)


def test_missing_is_fail_closed_after_now_validation() -> None:
    assert evaluate_robots_cache(stored_at=None, now=BASE) == RobotsCacheDecision(
        False, RobotsCacheReason.MISSING, None, None
    )


@pytest.mark.parametrize(
    ("now", "reusable", "reason"),
    [
        (BASE, True, RobotsCacheReason.FRESH),
        (BASE + timedelta(hours=24) - timedelta(microseconds=1), True, RobotsCacheReason.FRESH),
        (BASE + timedelta(hours=24), False, RobotsCacheReason.EXPIRED),
        (BASE + timedelta(hours=24, microseconds=1), False, RobotsCacheReason.EXPIRED),
    ],
)
def test_fixed_24_hour_boundary(now: datetime, reusable: bool, reason: RobotsCacheReason) -> None:
    decision = evaluate_robots_cache(stored_at=BASE, now=now)
    assert decision == RobotsCacheDecision(reusable, reason, BASE, BASE + timedelta(hours=24))


def test_future_dated_and_overflow_inputs_fail_closed() -> None:
    assert_invalid(stored_at=BASE + timedelta(microseconds=1), now=BASE)
    maximum = datetime.max.replace(tzinfo=UTC)
    assert_invalid(stored_at=maximum, now=maximum)


def test_preserves_stored_identity_is_deterministic_and_does_not_mutate_inputs() -> None:
    stored_at = datetime(2026, 8, 17, 12, 34, 56, 789, tzinfo=UTC)
    now = stored_at + timedelta(hours=1)
    first = evaluate_robots_cache(stored_at=stored_at, now=now)
    second = evaluate_robots_cache(stored_at=stored_at, now=now)
    assert first == second
    assert first.stored_at is stored_at
    assert stored_at == datetime(2026, 8, 17, 12, 34, 56, 789, tzinfo=UTC)
    assert now == stored_at + timedelta(hours=1)


def test_module_is_stdlib_only_and_isolated_from_runtime_paths() -> None:
    source = Path(cache_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert imported_modules <= {"__future__", "dataclasses", "datetime", "enum"}
    forbidden = {
        "now",
        "sleep",
        "open",
        "evaluate_robots",
        "evaluate_robots_access",
        "evaluate_robots_gate",
        "evaluate_bound_robots",
        "fetch_robots",
        "getLogger",
    }
    assert (
        not {
            node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
        }
        & forbidden
    )
