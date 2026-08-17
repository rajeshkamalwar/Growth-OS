from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from yarl import URL

from growth_os.acquisition import FetchedRobots, RobotsFetchErrorCode, _transport
from growth_os.robots.gate import RobotsGateDecision, evaluate_robots_gate


class RobotsBindingErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    INVALID_URL = "invalid_url"
    DISALLOWED_PORT = "disallowed_port"
    CROSS_ORIGIN = "cross_origin"
    PROVENANCE_MISMATCH = "provenance_mismatch"


class RobotsBindingError(ValueError):
    code: RobotsBindingErrorCode

    def __init__(self, code: RobotsBindingErrorCode) -> None:
        self.code = code
        super().__init__(f"Robots binding failed: {code.value}")


@dataclass(frozen=True, slots=True)
class BoundRobotsDecision:
    site_url: str
    target_url: str
    target_path: str
    gate_decision: RobotsGateDecision


def _error(code: RobotsBindingErrorCode) -> RobotsBindingError:
    return RobotsBindingError(code)


def _normalize(raw_url: str) -> URL:
    try:
        return _transport.normalize_url(raw_url)
    except _transport.TransportError as exc:
        code = (
            RobotsBindingErrorCode.DISALLOWED_PORT
            if exc.code == "disallowed_port"
            else RobotsBindingErrorCode.INVALID_URL
        )
        raise _error(code) from None


def evaluate_bound_robots(
    *,
    site_url: str,
    target_url: str,
    fetched_robots: FetchedRobots | None,
    fetch_error_code: RobotsFetchErrorCode | None,
) -> BoundRobotsDecision:
    if (
        type(site_url) is not str
        or not site_url
        or type(target_url) is not str
        or not target_url
        or (fetched_robots is None) == (fetch_error_code is None)
        or (fetched_robots is not None and type(fetched_robots) is not FetchedRobots)
        or (fetch_error_code is not None and type(fetch_error_code) is not RobotsFetchErrorCode)
    ):
        raise _error(RobotsBindingErrorCode.INVALID_INPUT)

    site = _normalize(site_url)
    target = _normalize(target_url)
    if (site.scheme, site.host, site.port) != (target.scheme, target.host, target.port):
        raise _error(RobotsBindingErrorCode.CROSS_ORIGIN)

    normalized_site = str(site)
    normalized_target = str(target)
    if fetched_robots is not None and fetched_robots.requested_site_url != normalized_site:
        raise _error(RobotsBindingErrorCode.PROVENANCE_MISMATCH)

    target_path = target.raw_path
    if target.raw_query_string:
        target_path = f"{target_path}?{target.raw_query_string}"
    gate_decision = evaluate_robots_gate(
        fetched_robots=fetched_robots,
        fetch_error_code=fetch_error_code,
        target_path=target_path,
    )
    return BoundRobotsDecision(
        normalized_site,
        normalized_target,
        target_path,
        gate_decision,
    )


__all__ = [
    "BoundRobotsDecision",
    "RobotsBindingError",
    "RobotsBindingErrorCode",
    "evaluate_bound_robots",
]
