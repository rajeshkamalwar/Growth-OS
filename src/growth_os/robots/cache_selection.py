from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from growth_os.acquisition.robots import FetchedRobots
from growth_os.robots.cache import (
    RobotsCacheDecision,
    RobotsCacheReason,
    evaluate_robots_cache,
)


@dataclass(frozen=True, slots=True)
class CachedRobotsOutcome:
    stored_at: datetime
    fetched_robots: FetchedRobots


class RobotsCacheSelectionReason(StrEnum):
    FRESH = "fresh"
    REFRESH_REQUIRED = "refresh_required"


class RobotsCacheSelectionErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"


class RobotsCacheSelectionError(ValueError):
    code: RobotsCacheSelectionErrorCode

    def __init__(self, code: RobotsCacheSelectionErrorCode) -> None:
        self.code = code
        super().__init__(f"Robots cache selection failed: {code.value}")


@dataclass(frozen=True, slots=True)
class RobotsCacheSelectionDecision:
    reusable: bool
    reason: RobotsCacheSelectionReason
    cache_decision: RobotsCacheDecision
    fetched_robots: FetchedRobots | None


def _invalid_input() -> RobotsCacheSelectionError:
    return RobotsCacheSelectionError(RobotsCacheSelectionErrorCode.INVALID_INPUT)


def _is_canonical_utc(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is timezone.utc  # noqa: UP017


def _valid_cache_decision(decision: object, *, stored_at: datetime | None, now: datetime) -> bool:
    if type(decision) is not RobotsCacheDecision or type(decision.reusable) is not bool:
        return False
    if not _is_canonical_utc(now):
        return False
    if decision.reason is RobotsCacheReason.MISSING:
        return (
            stored_at is None
            and not decision.reusable
            and decision.stored_at is None
            and decision.expires_at is None
        )
    if not _is_canonical_utc(stored_at) or decision.stored_at is not stored_at:
        return False
    assert type(stored_at) is datetime
    expires_at = decision.expires_at
    if not _is_canonical_utc(expires_at):
        return False
    assert type(expires_at) is datetime
    try:
        expected_expires_at = stored_at + timedelta(hours=24)
    except OverflowError:
        return False
    if expires_at != expected_expires_at:
        return False
    if decision.reason is RobotsCacheReason.FRESH:
        return decision.reusable and now < expires_at
    if decision.reason is RobotsCacheReason.EXPIRED:
        return not decision.reusable and now >= expires_at
    return False


def select_cached_robots(
    *,
    cached_outcome: CachedRobotsOutcome | None,
    now: datetime,
) -> RobotsCacheSelectionDecision:
    if cached_outcome is not None and type(cached_outcome) is not CachedRobotsOutcome:
        raise _invalid_input()
    if cached_outcome is not None and (
        type(cached_outcome.stored_at) is not datetime
        or type(cached_outcome.fetched_robots) is not FetchedRobots
    ):
        raise _invalid_input()

    stored_at = None if cached_outcome is None else cached_outcome.stored_at
    cache_decision = evaluate_robots_cache(stored_at=stored_at, now=now)
    if not _valid_cache_decision(cache_decision, stored_at=stored_at, now=now):
        raise _invalid_input()

    if (cached_outcome is None) is not (cache_decision.reason is RobotsCacheReason.MISSING):
        raise _invalid_input()

    if cache_decision.reason is RobotsCacheReason.FRESH:
        assert cached_outcome is not None
        return RobotsCacheSelectionDecision(
            True,
            RobotsCacheSelectionReason.FRESH,
            cache_decision,
            cached_outcome.fetched_robots,
        )
    return RobotsCacheSelectionDecision(
        False,
        RobotsCacheSelectionReason.REFRESH_REQUIRED,
        cache_decision,
        None,
    )


__all__ = [
    "CachedRobotsOutcome",
    "RobotsCacheSelectionDecision",
    "RobotsCacheSelectionError",
    "RobotsCacheSelectionErrorCode",
    "RobotsCacheSelectionReason",
    "select_cached_robots",
]
