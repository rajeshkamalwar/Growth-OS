from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum


class RobotsCacheReason(StrEnum):
    MISSING = "missing"
    FRESH = "fresh"
    EXPIRED = "expired"


class RobotsCacheErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"


class RobotsCacheError(ValueError):
    code: RobotsCacheErrorCode

    def __init__(self, code: RobotsCacheErrorCode) -> None:
        self.code = code
        super().__init__(f"Robots cache policy failed: {code.value}")


@dataclass(frozen=True, slots=True)
class RobotsCacheDecision:
    reusable: bool
    reason: RobotsCacheReason
    stored_at: datetime | None
    expires_at: datetime | None


def _invalid_input() -> RobotsCacheError:
    return RobotsCacheError(RobotsCacheErrorCode.INVALID_INPUT)


def _is_canonical_utc(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is timezone.utc  # noqa: UP017


def evaluate_robots_cache(
    *,
    stored_at: datetime | None,
    now: datetime,
) -> RobotsCacheDecision:
    if not _is_canonical_utc(now):
        raise _invalid_input()
    if stored_at is None:
        return RobotsCacheDecision(False, RobotsCacheReason.MISSING, None, None)
    if not _is_canonical_utc(stored_at) or stored_at > now:
        raise _invalid_input()
    try:
        expires_at = stored_at + timedelta(hours=24)
    except OverflowError:
        raise _invalid_input() from None
    if now < expires_at:
        return RobotsCacheDecision(True, RobotsCacheReason.FRESH, stored_at, expires_at)
    return RobotsCacheDecision(False, RobotsCacheReason.EXPIRED, stored_at, expires_at)


__all__ = [
    "RobotsCacheDecision",
    "RobotsCacheError",
    "RobotsCacheErrorCode",
    "RobotsCacheReason",
    "evaluate_robots_cache",
]
