import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from enum import StrEnum
from pathlib import Path

import pytest

from growth_os import robots as robots_package
from growth_os.acquisition import FetchedRobots, RobotsFetchErrorCode
from growth_os.robots import (
    RobotsAccessDecision,
    RobotsAccessReason,
    RobotsGateDecision,
    RobotsGateError,
    RobotsGateErrorCode,
    RobotsGateReason,
    RobotsPolicyError,
    RobotsPolicyErrorCode,
    evaluate_robots_gate,
)
from growth_os.robots import gate as gate_module


def fetched(
    *,
    status_code: int = 200,
    content_type: str | None = "text/plain",
    body: bytes | None = b"User-agent: *\nDisallow: /private\n",
) -> FetchedRobots:
    return FetchedRobots(
        "https://example.com/",
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
        status_code,
        content_type,
        body,
        ("https://example.com/robots.txt",),
    )


def test_public_contract_is_exact_exported_and_immutable() -> None:
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
    assert issubclass(RobotsGateReason, StrEnum)
    assert list(RobotsGateReason) == [
        RobotsGateReason.ACCESS,
        RobotsGateReason.FETCH_UNREACHABLE,
        RobotsGateReason.FETCH_REJECTED,
    ]
    assert list(RobotsGateErrorCode) == [RobotsGateErrorCode.INVALID_INPUT]
    assert [field.name for field in fields(RobotsGateDecision)] == [
        "allowed",
        "reason",
        "fetched_robots",
        "access_decision",
        "fetch_error_code",
    ]
    assert str(inspect.signature(evaluate_robots_gate)) == (
        "(*, fetched_robots: 'FetchedRobots | None', "
        "fetch_error_code: 'RobotsFetchErrorCode | None', "
        "target_path: 'str') -> 'RobotsGateDecision'"
    )
    result = evaluate_robots_gate(
        fetched_robots=fetched(), fetch_error_code=None, target_path="/public"
    )
    with pytest.raises(FrozenInstanceError):
        result.allowed = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("fetched_robots", "fetch_error_code"),
    [
        (None, None),
        (fetched(), RobotsFetchErrorCode.TIMEOUT),
        (object(), None),
        ({"status_code": 404}, None),
        (None, "timeout"),
        (None, object()),
    ],
)
def test_invalid_one_of_and_types_raise_stable_redacted_error(
    fetched_robots: object, fetch_error_code: object
) -> None:
    with pytest.raises(RobotsGateError) as caught:
        evaluate_robots_gate(
            fetched_robots=fetched_robots,  # type: ignore[arg-type]
            fetch_error_code=fetch_error_code,  # type: ignore[arg-type]
            target_path="/secret-path",
        )
    assert caught.value.code is RobotsGateErrorCode.INVALID_INPUT
    assert str(caught.value) == "Robots gate failed: invalid_input"
    assert caught.value.args == ("Robots gate failed: invalid_input",)


@pytest.mark.parametrize(
    "value",
    [
        FetchedRobots("", "r", "r", 200, "text/plain", b"", ("r",)),
        FetchedRobots(1, "r", "r", 200, "text/plain", b"", ("r",)),  # type: ignore[arg-type]
        FetchedRobots("s", "", "r", 200, "text/plain", b"", ("",)),
        FetchedRobots("s", "r", "", 200, "text/plain", b"", ("r",)),
        FetchedRobots("s", "r", "r", True, None, None, ("r",)),
        FetchedRobots("s", "r", "r", 99, None, None, ("r",)),
        FetchedRobots("s", "r", "r", 600, None, None, ("r",)),
        FetchedRobots("s", "r", "r", 200, None, b"", ("r",)),
        FetchedRobots("s", "r", "r", 200, "text/html", b"", ("r",)),
        FetchedRobots("s", "r", "r", 200, "text/plain", bytearray(), ("r",)),  # type: ignore[arg-type]
        FetchedRobots("s", "r", "r", 404, "text/plain", None, ("r",)),
        FetchedRobots("s", "r", "r", 404, None, b"", ("r",)),
        FetchedRobots("s", "r", "r", 404, None, None, ()),
        FetchedRobots("s", "r", "r", 404, None, None, ["r"]),  # type: ignore[arg-type]
        FetchedRobots("s", "r", "r", 404, None, None, ("",)),
        FetchedRobots("s", "r", "r", 404, None, None, (1,)),  # type: ignore[arg-type]
        FetchedRobots("s", "r", "final", 404, None, None, ("wrong", "final")),
        FetchedRobots("s", "r", "final", 404, None, None, ("r", "wrong")),
    ],
)
def test_malformed_fetched_provenance_is_rejected_before_access(value: FetchedRobots) -> None:
    with pytest.raises(RobotsGateError):
        evaluate_robots_gate(fetched_robots=value, fetch_error_code=None, target_path="/")


@pytest.mark.parametrize(
    ("value", "target_path"),
    [
        (fetched(), "/public"),
        (fetched(), "/private"),
        (fetched(status_code=404, content_type=None, body=None), "/private"),
        (fetched(status_code=503, content_type=None, body=None), "/private"),
        (fetched(status_code=304, content_type=None, body=None), "/private"),
        (fetched(body=b"\xff"), "/private"),
    ],
)
def test_fetched_outcomes_preserve_exact_provenance_and_access_mapping(
    value: FetchedRobots, target_path: str
) -> None:
    result = evaluate_robots_gate(
        fetched_robots=value, fetch_error_code=None, target_path=target_path
    )
    assert result.reason is RobotsGateReason.ACCESS
    assert result.fetched_robots is value
    assert result.access_decision is not None
    assert result.allowed is result.access_decision.allowed
    assert result.fetch_error_code is None


def test_fetched_outcome_calls_access_exactly_once_and_retains_decision_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = fetched(status_code=404, content_type=None, body=None)
    decision = RobotsAccessDecision(True, RobotsAccessReason.UNAVAILABLE, 404, None, None)
    calls: list[tuple[int | None, bytes | None, str]] = []

    def fake_access(
        *, status_code: int | None, robots_txt: bytes | None, target_path: str
    ) -> RobotsAccessDecision:
        calls.append((status_code, robots_txt, target_path))
        return decision

    monkeypatch.setattr(gate_module, "evaluate_robots_access", fake_access)
    result = evaluate_robots_gate(
        fetched_robots=value, fetch_error_code=None, target_path="/private"
    )
    assert calls == [(404, None, "/private")]
    assert result.fetched_robots is value
    assert result.access_decision is decision
    assert result.allowed is decision.allowed


UNREACHABLE = [
    RobotsFetchErrorCode.DNS_FAILURE,
    RobotsFetchErrorCode.TIMEOUT,
    RobotsFetchErrorCode.TLS_FAILURE,
    RobotsFetchErrorCode.NETWORK_FAILURE,
]
REJECTED = [code for code in RobotsFetchErrorCode if code not in UNREACHABLE]


@pytest.mark.parametrize("code", UNREACHABLE)
def test_unreachable_errors_map_once_and_preserve_exact_provenance(
    monkeypatch: pytest.MonkeyPatch, code: RobotsFetchErrorCode
) -> None:
    decision = RobotsAccessDecision(False, RobotsAccessReason.UNREACHABLE, None, None, None)
    calls: list[tuple[int | None, bytes | None, str]] = []

    def fake_access(*, status_code: int | None, robots_txt: bytes | None, target_path: str):
        calls.append((status_code, robots_txt, target_path))
        return decision

    monkeypatch.setattr(gate_module, "evaluate_robots_access", fake_access)
    result = evaluate_robots_gate(
        fetched_robots=None, fetch_error_code=code, target_path="/private"
    )
    assert calls == [(None, None, "/private")]
    assert result == RobotsGateDecision(
        False, RobotsGateReason.FETCH_UNREACHABLE, None, decision, code
    )
    assert result.access_decision is decision
    assert result.fetch_error_code is code


@pytest.mark.parametrize("code", REJECTED)
def test_rejected_errors_validate_once_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch, code: RobotsFetchErrorCode
) -> None:
    calls: list[tuple[int | None, bytes | None, str]] = []

    def fake_access(*, status_code: int | None, robots_txt: bytes | None, target_path: str):
        calls.append((status_code, robots_txt, target_path))
        return RobotsAccessDecision(False, RobotsAccessReason.UNREACHABLE, None, None, None)

    monkeypatch.setattr(gate_module, "evaluate_robots_access", fake_access)
    result = evaluate_robots_gate(
        fetched_robots=None, fetch_error_code=code, target_path="/private"
    )
    assert calls == [(None, None, "/private")]
    assert result == RobotsGateDecision(False, RobotsGateReason.FETCH_REJECTED, None, None, code)


@pytest.mark.parametrize(
    ("fetched_robots", "fetch_error_code"),
    [
        (fetched(), None),
        (None, RobotsFetchErrorCode.TIMEOUT),
        (None, RobotsFetchErrorCode.INVALID_URL),
    ],
)
def test_invalid_target_preserves_product_010_error(
    fetched_robots: FetchedRobots | None, fetch_error_code: RobotsFetchErrorCode | None
) -> None:
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate_robots_gate(
            fetched_robots=fetched_robots,
            fetch_error_code=fetch_error_code,
            target_path="relative/secret",
        )
    assert caught.value.code is RobotsPolicyErrorCode.INVALID_INPUT
    assert str(caught.value) == "Invalid robots policy input."


def test_repeated_calls_are_deterministic_and_do_not_mutate_input() -> None:
    value = fetched()
    before = tuple(getattr(value, field.name) for field in fields(value))
    first = evaluate_robots_gate(fetched_robots=value, fetch_error_code=None, target_path="/public")
    second = evaluate_robots_gate(
        fetched_robots=value, fetch_error_code=None, target_path="/public"
    )
    assert first == second
    assert tuple(getattr(value, field.name) for field in fields(value)) == before


def test_gate_is_statically_and_runtime_isolated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    imports: set[str] = set()
    source = inspect.getsource(gate_module)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    assert imports <= {
        "__future__",
        "dataclasses",
        "enum",
        "typing",
        "growth_os.acquisition",
        "growth_os.robots.access",
    }
    for boundary in (
        "builtins.open",
        "logging.Logger._log",
        "socket.getaddrinfo",
        "socket.socket",
        "subprocess.Popen",
        "subprocess.run",
        "urllib.request.urlopen",
    ):
        monkeypatch.setattr(boundary, lambda *args, **kwargs: pytest.fail("side effect"))
    evaluate_robots_gate(fetched_robots=fetched(), fetch_error_code=None, target_path="/")
    evaluate_robots_gate(
        fetched_robots=None, fetch_error_code=RobotsFetchErrorCode.TIMEOUT, target_path="/"
    )
    assert caplog.records == []


def test_gate_has_no_active_runtime_integration() -> None:
    package_root = Path(gate_module.__file__).parents[1]
    allowed = {
        Path(gate_module.__file__),
        Path(robots_package.__file__),
        Path(gate_module.__file__).with_name("binding.py"),
    }
    for path in package_root.rglob("*.py"):
        if path not in allowed:
            assert "growth_os.robots.gate" not in path.read_text()
