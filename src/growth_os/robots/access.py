from dataclasses import dataclass
from enum import StrEnum

from growth_os.robots.policy import (
    RobotsDecision,
    RobotsPolicyError,
    RobotsPolicyErrorCode,
    evaluate_robots,
)


class RobotsAccessReason(StrEnum):
    POLICY = "policy"
    UNAVAILABLE = "unavailable"
    UNREACHABLE = "unreachable"
    INDETERMINATE = "indeterminate"
    INVALID_POLICY = "invalid_policy"


@dataclass(frozen=True, slots=True)
class RobotsAccessDecision:
    allowed: bool
    reason: RobotsAccessReason
    status_code: int | None
    policy_decision: RobotsDecision | None
    policy_error_code: RobotsPolicyErrorCode | None


def _invalid_input() -> RobotsPolicyError:
    return RobotsPolicyError(RobotsPolicyErrorCode.INVALID_INPUT, "Invalid robots policy input.")


def evaluate_robots_access(
    *,
    status_code: int | None,
    robots_txt: bytes | None,
    target_path: str,
) -> RobotsAccessDecision:
    if (
        (status_code is not None and type(status_code) is not int)
        or type(robots_txt) not in {bytes, type(None)}
        or type(target_path) is not str
        or (status_code is not None and not 100 <= status_code <= 599)
        or (status_code == 200) != (robots_txt is not None)
    ):
        raise _invalid_input()

    evaluate_robots(robots_txt=b"", target_path=target_path)

    if status_code == 200:
        assert robots_txt is not None
        try:
            policy_decision = evaluate_robots(robots_txt=robots_txt, target_path=target_path)
        except RobotsPolicyError as error:
            if error.code is RobotsPolicyErrorCode.INVALID_INPUT:
                raise
            return RobotsAccessDecision(
                False, RobotsAccessReason.INVALID_POLICY, 200, None, error.code
            )
        return RobotsAccessDecision(
            policy_decision.allowed,
            RobotsAccessReason.POLICY,
            200,
            policy_decision,
            None,
        )
    if status_code is None or status_code >= 500:
        return RobotsAccessDecision(False, RobotsAccessReason.UNREACHABLE, status_code, None, None)
    if status_code >= 400:
        return RobotsAccessDecision(True, RobotsAccessReason.UNAVAILABLE, status_code, None, None)
    return RobotsAccessDecision(False, RobotsAccessReason.INDETERMINATE, status_code, None, None)


__all__ = ["RobotsAccessDecision", "RobotsAccessReason", "evaluate_robots_access"]
