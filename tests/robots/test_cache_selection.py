import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone, tzinfo
from enum import StrEnum
from pathlib import Path

import pytest

from growth_os import robots as robots_package
from growth_os.acquisition import FetchedRobots
from growth_os.robots import (
    CachedRobotsOutcome,
    RobotsCacheDecision,
    RobotsCacheError,
    RobotsCacheErrorCode,
    RobotsCacheReason,
    RobotsCacheSelectionDecision,
    RobotsCacheSelectionError,
    RobotsCacheSelectionErrorCode,
    RobotsCacheSelectionReason,
    select_cached_robots,
)
from growth_os.robots import cache_selection as selection_module

UTC = timezone.utc  # noqa: UP017
STORED_AT = datetime(2026, 8, 17, 12, tzinfo=UTC)
NOW = STORED_AT + timedelta(hours=1)


def fetched() -> FetchedRobots:
    return FetchedRobots(
        "https://example.com/",
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
        200,
        "text/plain",
        b"User-agent: *\nDisallow: /private\n",
        ("https://example.com/robots.txt",),
    )


def outcome() -> CachedRobotsOutcome:
    return CachedRobotsOutcome(STORED_AT, fetched())


def assert_invalid(**kwargs: object) -> RobotsCacheSelectionError:
    with pytest.raises(RobotsCacheSelectionError) as caught:
        select_cached_robots(**kwargs)  # type: ignore[arg-type]
    assert caught.value.code is RobotsCacheSelectionErrorCode.INVALID_INPUT
    assert str(caught.value) == "Robots cache selection failed: invalid_input"
    assert caught.value.args == ("Robots cache selection failed: invalid_input",)
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
    assert issubclass(RobotsCacheSelectionReason, StrEnum)
    assert list(RobotsCacheSelectionReason) == [
        RobotsCacheSelectionReason.FRESH,
        RobotsCacheSelectionReason.REFRESH_REQUIRED,
    ]
    assert list(RobotsCacheSelectionErrorCode) == [RobotsCacheSelectionErrorCode.INVALID_INPUT]
    assert [field.name for field in fields(CachedRobotsOutcome)] == [
        "stored_at",
        "fetched_robots",
    ]
    assert [field.name for field in fields(RobotsCacheSelectionDecision)] == [
        "reusable",
        "reason",
        "cache_decision",
        "fetched_robots",
    ]
    assert str(inspect.signature(select_cached_robots)) == (
        "(*, cached_outcome: 'CachedRobotsOutcome | None', "
        "now: 'datetime') -> 'RobotsCacheSelectionDecision'"
    )
    value = outcome()
    assert value == CachedRobotsOutcome(STORED_AT, value.fetched_robots)
    with pytest.raises(FrozenInstanceError):
        value.stored_at = NOW  # type: ignore[misc]
    decision = select_cached_robots(cached_outcome=value, now=NOW)
    assert decision == select_cached_robots(cached_outcome=value, now=NOW)
    with pytest.raises(FrozenInstanceError):
        decision.reusable = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        select_cached_robots(value, NOW)  # type: ignore[misc]


class OutcomeSubclass(CachedRobotsOutcome):
    pass


class DatetimeSubclass(datetime):
    pass


class FetchedSubclass(FetchedRobots):
    pass


class ZeroOffsetTimezone(tzinfo):
    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def dst(self, dt: datetime | None) -> timedelta:
        return timedelta(0)

    def tzname(self, dt: datetime | None) -> str:
        return "UTC"


class OutcomeDuck:
    stored_at = STORED_AT
    fetched_robots = fetched()


@pytest.mark.parametrize(
    "cached_outcome",
    [
        1,
        object(),
        OutcomeDuck(),
        OutcomeSubclass(STORED_AT, fetched()),
        CachedRobotsOutcome(DatetimeSubclass(2026, 8, 17, 12, tzinfo=UTC), fetched()),
        CachedRobotsOutcome(
            STORED_AT,
            FetchedSubclass(*tuple(getattr(fetched(), field.name) for field in fields(fetched()))),
        ),
    ],
)
def test_invalid_outcome_shape_is_rejected_before_cache_policy(
    monkeypatch: pytest.MonkeyPatch, cached_outcome: object
) -> None:
    monkeypatch.setattr(
        selection_module,
        "evaluate_robots_cache",
        lambda **kwargs: pytest.fail("cache policy called"),
    )
    assert_invalid(cached_outcome=cached_outcome, now=NOW)


@pytest.mark.parametrize(
    ("cached_outcome", "now", "expected_stored_at", "cache_decision"),
    [
        (None, NOW, None, RobotsCacheDecision(False, RobotsCacheReason.MISSING, None, None)),
        (
            outcome(),
            NOW,
            STORED_AT,
            RobotsCacheDecision(
                True,
                RobotsCacheReason.FRESH,
                STORED_AT,
                STORED_AT + timedelta(hours=24),
            ),
        ),
        (
            outcome(),
            STORED_AT + timedelta(hours=24),
            STORED_AT,
            RobotsCacheDecision(
                False,
                RobotsCacheReason.EXPIRED,
                STORED_AT,
                STORED_AT + timedelta(hours=24),
            ),
        ),
    ],
)
def test_delegates_exactly_once_with_exact_input_identity(
    monkeypatch: pytest.MonkeyPatch,
    cached_outcome: CachedRobotsOutcome | None,
    now: datetime,
    expected_stored_at: datetime | None,
    cache_decision: RobotsCacheDecision,
) -> None:
    calls: list[dict[str, object]] = []

    def evaluate(**kwargs: object) -> RobotsCacheDecision:
        calls.append(kwargs)
        return cache_decision

    monkeypatch.setattr(selection_module, "evaluate_robots_cache", evaluate)
    result = select_cached_robots(cached_outcome=cached_outcome, now=now)
    assert calls == [{"stored_at": expected_stored_at, "now": now}]
    assert calls[0]["stored_at"] is expected_stored_at
    assert calls[0]["now"] is now
    assert result.cache_decision is cache_decision


def test_cache_policy_errors_propagate_unchanged() -> None:
    invalid_now = datetime(2026, 8, 17, 13)
    with pytest.raises(RobotsCacheError) as direct:
        selection_module.evaluate_robots_cache(stored_at=STORED_AT, now=invalid_now)
    with pytest.raises(RobotsCacheError) as selected:
        select_cached_robots(cached_outcome=outcome(), now=invalid_now)
    assert selected.value is not direct.value
    assert type(selected.value) is type(direct.value)
    assert selected.value.code is direct.value.code
    assert selected.value.args == direct.value.args


def test_cache_policy_error_object_is_not_caught_or_rewritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = RobotsCacheError(RobotsCacheErrorCode.INVALID_INPUT)

    def fail(**kwargs: object) -> RobotsCacheDecision:
        raise error

    monkeypatch.setattr(selection_module, "evaluate_robots_cache", fail)
    with pytest.raises(RobotsCacheError) as caught:
        select_cached_robots(cached_outcome=outcome(), now=NOW)
    assert caught.value is error


def test_fresh_returns_exact_fetched_and_cache_decision_objects() -> None:
    cached = outcome()
    result = select_cached_robots(cached_outcome=cached, now=NOW)
    assert result.reusable is True
    assert result.reason is RobotsCacheSelectionReason.FRESH
    assert result.fetched_robots is cached.fetched_robots
    assert result.cache_decision.reason is RobotsCacheReason.FRESH


@pytest.mark.parametrize(
    ("cached_outcome", "now", "cache_reason"),
    [
        (None, NOW, RobotsCacheReason.MISSING),
        (outcome(), STORED_AT + timedelta(hours=24), RobotsCacheReason.EXPIRED),
        (
            outcome(),
            STORED_AT + timedelta(hours=24, microseconds=1),
            RobotsCacheReason.EXPIRED,
        ),
    ],
)
def test_missing_and_expired_drop_fetched_object(
    cached_outcome: CachedRobotsOutcome | None,
    now: datetime,
    cache_reason: RobotsCacheReason,
) -> None:
    result = select_cached_robots(cached_outcome=cached_outcome, now=now)
    assert result.reusable is False
    assert result.reason is RobotsCacheSelectionReason.REFRESH_REQUIRED
    assert result.fetched_robots is None
    assert result.cache_decision.reason is cache_reason


@pytest.mark.parametrize(
    "forged",
    [
        object(),
        RobotsCacheDecision(1, RobotsCacheReason.FRESH, STORED_AT, NOW),
        RobotsCacheDecision(False, RobotsCacheReason.FRESH, STORED_AT, NOW),
        RobotsCacheDecision(True, RobotsCacheReason.FRESH, None, NOW),
        RobotsCacheDecision(True, RobotsCacheReason.FRESH, STORED_AT, None),
        RobotsCacheDecision(True, RobotsCacheReason.MISSING, None, None),
        RobotsCacheDecision(False, RobotsCacheReason.MISSING, STORED_AT, None),
        RobotsCacheDecision(False, RobotsCacheReason.MISSING, None, NOW),
        RobotsCacheDecision(True, RobotsCacheReason.EXPIRED, STORED_AT, NOW),
        RobotsCacheDecision(False, RobotsCacheReason.EXPIRED, None, NOW),
        RobotsCacheDecision(False, RobotsCacheReason.EXPIRED, STORED_AT, None),
        RobotsCacheDecision(False, "missing", None, None),  # type: ignore[arg-type]
    ],
)
def test_forged_cache_decisions_fail_closed(
    monkeypatch: pytest.MonkeyPatch, forged: object
) -> None:
    monkeypatch.setattr(selection_module, "evaluate_robots_cache", lambda **kwargs: forged)
    assert_invalid(cached_outcome=outcome(), now=NOW)


@pytest.mark.parametrize(
    "forged",
    [
        RobotsCacheDecision(
            True,
            RobotsCacheReason.FRESH,
            datetime(2026, 8, 17, 12, tzinfo=UTC),
            STORED_AT + timedelta(hours=24),
        ),
        RobotsCacheDecision(
            True,
            RobotsCacheReason.FRESH,
            datetime(2026, 8, 17, 12),
            STORED_AT + timedelta(hours=24),
        ),
        RobotsCacheDecision(
            True,
            RobotsCacheReason.FRESH,
            datetime(2026, 8, 17, 12, tzinfo=ZeroOffsetTimezone()),
            STORED_AT + timedelta(hours=24),
        ),
        RobotsCacheDecision(
            True,
            RobotsCacheReason.FRESH,
            STORED_AT,
            STORED_AT + timedelta(hours=23),
        ),
        RobotsCacheDecision(
            True,
            RobotsCacheReason.FRESH,
            STORED_AT,
            datetime(2026, 8, 18, 12),
        ),
        RobotsCacheDecision(
            False,
            RobotsCacheReason.EXPIRED,
            STORED_AT,
            STORED_AT + timedelta(hours=24),
        ),
    ],
)
def test_forged_cache_timestamp_invariants_fail_closed(
    monkeypatch: pytest.MonkeyPatch, forged: RobotsCacheDecision
) -> None:
    monkeypatch.setattr(selection_module, "evaluate_robots_cache", lambda **kwargs: forged)
    assert_invalid(cached_outcome=outcome(), now=NOW)


def test_cache_decision_subclass_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class DecisionSubclass(RobotsCacheDecision):
        pass

    forged = DecisionSubclass(True, RobotsCacheReason.FRESH, STORED_AT, NOW)
    monkeypatch.setattr(selection_module, "evaluate_robots_cache", lambda **kwargs: forged)
    assert_invalid(cached_outcome=outcome(), now=NOW)


@pytest.mark.parametrize(
    ("cached_outcome", "forged"),
    [
        (
            outcome(),
            RobotsCacheDecision(False, RobotsCacheReason.MISSING, None, None),
        ),
        (
            None,
            RobotsCacheDecision(False, RobotsCacheReason.EXPIRED, STORED_AT, NOW),
        ),
        (
            None,
            RobotsCacheDecision(True, RobotsCacheReason.FRESH, STORED_AT, NOW),
        ),
    ],
)
def test_cache_reason_must_match_outcome_presence(
    monkeypatch: pytest.MonkeyPatch,
    cached_outcome: CachedRobotsOutcome | None,
    forged: RobotsCacheDecision,
) -> None:
    monkeypatch.setattr(selection_module, "evaluate_robots_cache", lambda **kwargs: forged)
    assert_invalid(cached_outcome=cached_outcome, now=NOW)


def test_repeated_calls_are_deterministic_and_do_not_copy_or_mutate_inputs() -> None:
    cached = outcome()
    original_fields = tuple(getattr(cached.fetched_robots, f.name) for f in fields(FetchedRobots))
    first = select_cached_robots(cached_outcome=cached, now=NOW)
    second = select_cached_robots(cached_outcome=cached, now=NOW)
    assert first == second
    assert first.fetched_robots is second.fetched_robots is cached.fetched_robots
    assert (
        tuple(getattr(cached.fetched_robots, f.name) for f in fields(FetchedRobots))
        == original_fields
    )
    assert cached.stored_at is STORED_AT


def test_module_is_isolated_from_forbidden_runtime_paths() -> None:
    source = Path(selection_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert imports <= {
        "__future__",
        "dataclasses",
        "datetime",
        "enum",
        "growth_os.acquisition.robots",
        "growth_os.robots.cache",
    }
    forbidden_fragments = {
        "access",
        "binding",
        "gate",
        "policy",
        "transport",
        "socket",
        "filesystem",
        "database",
        "repository",
        "service",
        "connector",
        "logging",
        "audit",
        "execution",
        "worker",
        "scheduler",
    }
    assert not any(fragment in imported for imported in imports for fragment in forbidden_fragments)
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    ]
    assert (
        set(calls)
        & {
            "now",
            "utcnow",
            "open",
            "fetch_robots",
            "evaluate_robots",
            "evaluate_robots_access",
            "evaluate_bound_robots",
            "evaluate_robots_gate",
            "getLogger",
        }
        == set()
    )
    assert calls.count("evaluate_robots_cache") == 1
