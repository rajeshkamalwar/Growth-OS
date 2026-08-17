from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from growth_os.acquisition import FetchedRobots, RobotsFetchErrorCode
from growth_os.robots.access import RobotsAccessDecision, evaluate_robots_access


class RobotsGateReason(StrEnum):
    ACCESS = "access"
    FETCH_UNREACHABLE = "fetch_unreachable"
    FETCH_REJECTED = "fetch_rejected"


class RobotsGateErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"


class RobotsGateError(ValueError):
    code: RobotsGateErrorCode

    def __init__(self, code: RobotsGateErrorCode) -> None:
        self.code = code
        super().__init__(f"Robots gate failed: {code.value}")


@dataclass(frozen=True, slots=True)
class RobotsGateDecision:
    allowed: bool
    reason: RobotsGateReason
    fetched_robots: FetchedRobots | None
    access_decision: RobotsAccessDecision | None
    fetch_error_code: RobotsFetchErrorCode | None


_UNREACHABLE: Final = frozenset(
    {
        RobotsFetchErrorCode.DNS_FAILURE,
        RobotsFetchErrorCode.TIMEOUT,
        RobotsFetchErrorCode.TLS_FAILURE,
        RobotsFetchErrorCode.NETWORK_FAILURE,
    }
)


def _invalid_input() -> RobotsGateError:
    return RobotsGateError(RobotsGateErrorCode.INVALID_INPUT)


def _validate_fetched_robots(value: FetchedRobots) -> None:
    if (
        type(value.requested_site_url) is not str
        or not value.requested_site_url
        or type(value.robots_url) is not str
        or not value.robots_url
        or type(value.final_url) is not str
        or not value.final_url
        or type(value.redirect_chain) is not tuple
        or not value.redirect_chain
        or any(type(item) is not str or not item for item in value.redirect_chain)
        or value.robots_url != value.redirect_chain[0]
        or value.final_url != value.redirect_chain[-1]
        or type(value.status_code) is not int
        or not 100 <= value.status_code <= 599
        or (
            value.status_code == 200
            and (value.content_type != "text/plain" or type(value.body) is not bytes)
        )
        or (value.status_code != 200 and (value.content_type is not None or value.body is not None))
    ):
        raise _invalid_input()


def evaluate_robots_gate(
    *,
    fetched_robots: FetchedRobots | None,
    fetch_error_code: RobotsFetchErrorCode | None,
    target_path: str,
) -> RobotsGateDecision:
    if (fetched_robots is None) == (fetch_error_code is None):
        raise _invalid_input()
    if fetched_robots is not None:
        if type(fetched_robots) is not FetchedRobots:
            raise _invalid_input()
        _validate_fetched_robots(fetched_robots)
        access_decision = evaluate_robots_access(
            status_code=fetched_robots.status_code,
            robots_txt=fetched_robots.body,
            target_path=target_path,
        )
        return RobotsGateDecision(
            access_decision.allowed,
            RobotsGateReason.ACCESS,
            fetched_robots,
            access_decision,
            None,
        )
    if type(fetch_error_code) is not RobotsFetchErrorCode:
        raise _invalid_input()
    access_decision = evaluate_robots_access(
        status_code=None, robots_txt=None, target_path=target_path
    )
    if fetch_error_code in _UNREACHABLE:
        return RobotsGateDecision(
            False,
            RobotsGateReason.FETCH_UNREACHABLE,
            None,
            access_decision,
            fetch_error_code,
        )
    return RobotsGateDecision(False, RobotsGateReason.FETCH_REJECTED, None, None, fetch_error_code)


__all__ = [
    "RobotsGateDecision",
    "RobotsGateError",
    "RobotsGateErrorCode",
    "RobotsGateReason",
    "evaluate_robots_gate",
]
