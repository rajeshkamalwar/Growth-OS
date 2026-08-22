from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


def _valid_cache_decision(decision: object) -> bool:
    if type(decision) is not RobotsCacheDecision or type(decision.reusable) is not bool:
        return False
    if decision.reason is RobotsCacheReason.FRESH:
        return (
            decision.reusable
            and type(decision.stored_at) is datetime
            and type(decision.expires_at) is datetime
        )
    if decision.reason is RobotsCacheReason.MISSING:
        return not decision.reusable and decision.stored_at is None and decision.expires_at is None
    if decision.reason is RobotsCacheReason.EXPIRED:
        return (
            not decision.reusable
            and type(decision.stored_at) is datetime
            and type(decision.expires_at) is datetime
        )
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
    if not _valid_cache_decision(cache_decision):
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
