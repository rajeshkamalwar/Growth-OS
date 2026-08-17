import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from enum import StrEnum

import pytest

from growth_os import robots as robots_package
from growth_os.robots import (
    RobotsAccessDecision,
    RobotsAccessReason,
    RobotsDecisionReason,
    RobotsPolicyError,
    RobotsPolicyErrorCode,
    evaluate_robots,
    evaluate_robots_access,
)
from growth_os.robots import access as access_module


def test_public_contract_is_exported_value_backed_and_immutable() -> None:
    assert robots_package.__all__ == [
        "BoundRobotsDecision",
        "RobotsAccessDecision",
        "RobotsAccessReason",
        "RobotsBindingError",
        "RobotsBindingErrorCode",
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
        "evaluate_robots_gate",
    ]
    assert issubclass(RobotsAccessReason, StrEnum)
    assert list(RobotsAccessReason) == [
        RobotsAccessReason.POLICY,
        RobotsAccessReason.UNAVAILABLE,
        RobotsAccessReason.UNREACHABLE,
        RobotsAccessReason.INDETERMINATE,
        RobotsAccessReason.INVALID_POLICY,
    ]
    assert [field.name for field in fields(RobotsAccessDecision)] == [
        "allowed",
        "reason",
        "status_code",
        "policy_decision",
        "policy_error_code",
    ]
    result = evaluate_robots_access(status_code=404, robots_txt=None, target_path="/")
    assert result == RobotsAccessDecision(True, RobotsAccessReason.UNAVAILABLE, 404, None, None)
    with pytest.raises(FrozenInstanceError):
        result.allowed = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        evaluate_robots_access(404, None, "/")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("status_code", "robots_txt", "target_path"),
    [
        (True, None, "/"),
        (200.0, b"", "/"),
        (type("Status", (int,), {})(200), b"", "/"),
        (404, b"", "/"),
        (None, b"", "/"),
        (200, None, "/"),
        (200, bytearray(), "/"),
        (200, type("Body", (bytes,), {})(b""), "/"),
        (404, None, b"/"),
        (404, None, type("Target", (str,), {})("/")),
        (99, None, "/"),
        (600, None, "/"),
    ],
)
def test_invalid_arguments_raise_stable_redacted_input_errors(
    status_code: object, robots_txt: object, target_path: object
) -> None:
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots_access(
            status_code=status_code,  # type: ignore[arg-type]
            robots_txt=robots_txt,  # type: ignore[arg-type]
            target_path=target_path,  # type: ignore[arg-type]
        )
    assert caught.value.code is RobotsPolicyErrorCode.INVALID_INPUT
    assert str(caught.value) == "Invalid robots policy input."
    assert caught.value.args == ("Invalid robots policy input.",)


@pytest.mark.parametrize(
    "status_code", [100, 199, 201, 204, 206, 301, 304, 399, 400, 499, 500, 599, None]
)
@pytest.mark.parametrize("target_path", ["relative", "//host/path", "/bad%", "/path#fragment"])
def test_target_path_is_validated_for_every_outcome(
    status_code: int | None, target_path: str
) -> None:
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots_access(status_code=status_code, robots_txt=None, target_path=target_path)
    assert caught.value.code is RobotsPolicyErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    ("robots_txt", "target_path", "allowed", "reason"),
    [
        (
            b"User-agent: GrowthOSBot\nAllow: /public\n",
            "/public",
            True,
            RobotsDecisionReason.MATCHED_ALLOW,
        ),
        (
            b"User-agent: GrowthOSBot\nDisallow: /private\n",
            "/private",
            False,
            RobotsDecisionReason.MATCHED_DISALLOW,
        ),
        (b"User-agent: Other\nDisallow: /\n", "/", True, RobotsDecisionReason.NO_MATCHING_GROUP),
        (
            b"User-agent: GrowthOSBot\nDisallow: /private\n",
            "/public",
            True,
            RobotsDecisionReason.NO_MATCHING_RULE,
        ),
        (b"User-agent: *\nDisallow: /\n", "/robots.txt", True, RobotsDecisionReason.ROBOTS_URI),
    ],
)
def test_200_preserves_exact_nested_policy_decision(
    robots_txt: bytes,
    target_path: str,
    allowed: bool,
    reason: RobotsDecisionReason,
) -> None:
    result = evaluate_robots_access(status_code=200, robots_txt=robots_txt, target_path=target_path)
    expected_policy_decision = evaluate_robots(robots_txt=robots_txt, target_path=target_path)
    assert result.allowed is allowed
    assert result.reason is RobotsAccessReason.POLICY
    assert result.status_code == 200
    assert result.policy_decision == expected_policy_decision
    assert result.policy_decision.reason is reason
    assert result.policy_error_code is None


@pytest.mark.parametrize(
    ("robots_txt", "error_code"),
    [
        (b" " * 512_001, RobotsPolicyErrorCode.TOO_LARGE),
        (b"\xff", RobotsPolicyErrorCode.INVALID_ENCODING),
    ],
)
def test_invalid_200_policy_fails_closed_with_error_provenance(
    robots_txt: bytes, error_code: RobotsPolicyErrorCode
) -> None:
    assert evaluate_robots_access(
        status_code=200, robots_txt=robots_txt, target_path="/private"
    ) == RobotsAccessDecision(False, RobotsAccessReason.INVALID_POLICY, 200, None, error_code)


def test_invalid_target_is_not_converted_to_invalid_policy() -> None:
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots_access(status_code=200, robots_txt=b"\xff", target_path="relative")
    assert caught.value.code is RobotsPolicyErrorCode.INVALID_INPUT


def test_every_4xx_is_allowed_and_unavailable() -> None:
    for status_code in range(400, 500):
        assert evaluate_robots_access(
            status_code=status_code, robots_txt=None, target_path="/private"
        ) == RobotsAccessDecision(True, RobotsAccessReason.UNAVAILABLE, status_code, None, None)


@pytest.mark.parametrize("status_code", [500, 503, 599, None])
def test_unreachable_outcomes_fail_closed(status_code: int | None) -> None:
    assert evaluate_robots_access(
        status_code=status_code, robots_txt=None, target_path="/private"
    ) == RobotsAccessDecision(False, RobotsAccessReason.UNREACHABLE, status_code, None, None)


@pytest.mark.parametrize("status_code", [100, 103, 199, 201, 204, 206, 301, 304, 399])
def test_incomplete_terminal_outcomes_are_indeterminate(status_code: int) -> None:
    assert evaluate_robots_access(
        status_code=status_code, robots_txt=None, target_path="/private"
    ) == RobotsAccessDecision(False, RobotsAccessReason.INDETERMINATE, status_code, None, None)


def test_repeated_non_policy_calls_are_deterministic_without_cache_or_fallback() -> None:
    first = evaluate_robots_access(status_code=None, robots_txt=None, target_path="/private")
    second = evaluate_robots_access(status_code=None, robots_txt=None, target_path="/private")
    assert first == second
    assert first.policy_decision is None
    assert first.policy_error_code is None


def test_access_module_has_only_offline_policy_dependencies() -> None:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(access_module))):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module.split(".", 1)[0])
    assert imports <= {"dataclasses", "enum", "growth_os"}


def test_access_evaluation_crosses_no_prohibited_runtime_boundary(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def reject_side_effect(*args: object, **kwargs: object) -> None:
        pytest.fail("robots access evaluation crossed a prohibited runtime boundary")

    for boundary in (
        "builtins.open",
        "logging.Logger._log",
        "socket.getaddrinfo",
        "socket.socket",
        "subprocess.Popen",
        "subprocess.run",
        "urllib.request.urlopen",
    ):
        monkeypatch.setattr(boundary, reject_side_effect)

    for status_code, robots_txt in (
        (200, b"User-agent: *\nDisallow: /\n"),
        (404, None),
        (503, None),
        (304, None),
        (None, None),
    ):
        evaluate_robots_access(
            status_code=status_code, robots_txt=robots_txt, target_path="/private"
        )
    assert caplog.records == []
