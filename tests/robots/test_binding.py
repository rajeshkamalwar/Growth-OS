import ast
import inspect
from dataclasses import FrozenInstanceError, fields
from enum import StrEnum
from pathlib import Path

import pytest

from growth_os import robots as robots_package
from growth_os.acquisition import FetchedRobots, RobotsFetchErrorCode
from growth_os.robots import (
    BoundRobotsDecision,
    RobotsAccessDecision,
    RobotsAccessReason,
    RobotsBindingError,
    RobotsBindingErrorCode,
    RobotsGateDecision,
    RobotsGateError,
    RobotsGateReason,
    RobotsPolicyError,
    RobotsPolicyErrorCode,
    evaluate_bound_robots,
)
from growth_os.robots import binding as binding_module


def fetched(*, requested_site_url: str = "https://example.com/") -> FetchedRobots:
    return FetchedRobots(
        requested_site_url,
        "https://example.com/robots.txt",
        "https://example.com/robots.txt",
        200,
        "text/plain",
        b"User-agent: *\nDisallow: /private\n",
        ("https://example.com/robots.txt",),
    )


def fields_tuple(value: FetchedRobots) -> tuple[object, ...]:
    return tuple(getattr(value, field.name) for field in fields(value))


def evaluate(
    *,
    site_url: str = "https://example.com/",
    target_url: str = "https://example.com/public",
    fetched_robots: FetchedRobots | None = None,
    fetch_error_code: RobotsFetchErrorCode | None = RobotsFetchErrorCode.TIMEOUT,
) -> BoundRobotsDecision:
    return evaluate_bound_robots(
        site_url=site_url,
        target_url=target_url,
        fetched_robots=fetched_robots,
        fetch_error_code=fetch_error_code,
    )


def assert_binding_error(code: RobotsBindingErrorCode, **kwargs: object) -> RobotsBindingError:
    with pytest.raises(RobotsBindingError) as caught:
        evaluate_bound_robots(**kwargs)  # type: ignore[arg-type]
    assert caught.value.code is code
    assert str(caught.value) == f"Robots binding failed: {code.value}"
    assert caught.value.args == (f"Robots binding failed: {code.value}",)
    return caught.value


def test_public_contract_is_exact_exported_immutable_and_equality_comparable() -> None:
    assert robots_package.__all__ == [
        "BoundRobotsDecision",
        "RobotsAccessDecision",
        "RobotsAccessReason",
        "RobotsBindingError",
        "RobotsBindingErrorCode",
        "RobotsCacheDecision",
        "RobotsCacheError",
        "RobotsCacheErrorCode",
        "RobotsCacheReason",
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
    ]
    assert issubclass(RobotsBindingErrorCode, StrEnum)
    assert [member.value for member in RobotsBindingErrorCode] == [
        "invalid_input",
        "invalid_url",
        "disallowed_port",
        "cross_origin",
        "provenance_mismatch",
    ]
    assert [field.name for field in fields(BoundRobotsDecision)] == [
        "site_url",
        "target_url",
        "target_path",
        "gate_decision",
    ]
    assert str(inspect.signature(evaluate_bound_robots)) == (
        "(*, site_url: 'str', target_url: 'str', "
        "fetched_robots: 'FetchedRobots | None', "
        "fetch_error_code: 'RobotsFetchErrorCode | None') -> 'BoundRobotsDecision'"
    )
    result = evaluate()
    assert result == evaluate()
    with pytest.raises(FrozenInstanceError):
        result.target_path = "/changed"  # type: ignore[misc]


class StringSubclass(str):
    pass


class FetchedSubclass(FetchedRobots):
    pass


@pytest.mark.parametrize(
    ("site_url", "target_url", "fetched_robots", "fetch_error_code"),
    [
        (None, "https://example.com/", None, RobotsFetchErrorCode.TIMEOUT),
        (1, "https://example.com/", None, RobotsFetchErrorCode.TIMEOUT),
        (
            StringSubclass("https://example.com/"),
            "https://example.com/",
            None,
            RobotsFetchErrorCode.TIMEOUT,
        ),
        ("", "https://example.com/", None, RobotsFetchErrorCode.TIMEOUT),
        ("https://example.com/", None, None, RobotsFetchErrorCode.TIMEOUT),
        ("https://example.com/", 1, None, RobotsFetchErrorCode.TIMEOUT),
        (
            "https://example.com/",
            StringSubclass("https://example.com/"),
            None,
            RobotsFetchErrorCode.TIMEOUT,
        ),
        ("https://example.com/", "", None, RobotsFetchErrorCode.TIMEOUT),
        ("not a URL", "also not a URL", None, None),
        ("not a URL", "also not a URL", fetched(), RobotsFetchErrorCode.TIMEOUT),
        ("not a URL", "also not a URL", object(), None),
        ("not a URL", "also not a URL", None, "timeout"),
        ("not a URL", "also not a URL", FetchedSubclass(*fields_tuple(fetched())), None),
    ],
)
def test_strict_input_and_one_of_validation_precedes_url_work_and_delegation(
    monkeypatch: pytest.MonkeyPatch,
    site_url: object,
    target_url: object,
    fetched_robots: object,
    fetch_error_code: object,
) -> None:
    monkeypatch.setattr(
        binding_module._transport,
        "normalize_url",
        lambda *args, **kwargs: pytest.fail("URL normalization called"),
    )
    monkeypatch.setattr(
        binding_module,
        "evaluate_robots_gate",
        lambda **kwargs: pytest.fail("gate called"),
    )
    assert_binding_error(
        RobotsBindingErrorCode.INVALID_INPUT,
        site_url=site_url,
        target_url=target_url,
        fetched_robots=fetched_robots,
        fetch_error_code=fetch_error_code,
    )


@pytest.mark.parametrize(
    ("site_url", "target_url", "expected_site", "expected_target"),
    [
        (
            "HTTPS://EXAMPLE.COM:00443/a#x",
            "https://example.com:443/B?q=1#frag",
            "https://example.com/a",
            "https://example.com/B?q=1",
        ),
        (
            "https://b\u00fccher.example/",
            "https://xn--bcher-kva.example/%E2%98%83?q=%2F",
            "https://xn--bcher-kva.example/",
            "https://xn--bcher-kva.example/%E2%98%83?q=/",
        ),
        (
            "http://[2001:db8::1]:80/",
            "http://[2001:0db8:0:0:0:0:0:1]/x",
            "http://[2001:db8::1]/",
            "http://[2001:db8::1]/x",
        ),
        ("https://192.0.2.1/", "https://192.0.2.1/a", "https://192.0.2.1/", "https://192.0.2.1/a"),
    ],
)
def test_normalization_parity_and_same_origin_acceptance(
    site_url: str, target_url: str, expected_site: str, expected_target: str
) -> None:
    result = evaluate(site_url=site_url, target_url=target_url)
    assert result.site_url == expected_site
    assert result.target_url == expected_target


@pytest.mark.parametrize(
    "value",
    [
        "example.com",
        "ftp://example.com/",
        "https:///missing-host",
        "https://user@example.com/",
        "https://example.com:password@other.example/",
        "https://bad_host.example/",
        "https://[not-ip]/",
    ],
)
def test_invalid_urls_are_mapped_to_redacted_invalid_url(value: str) -> None:
    error = assert_binding_error(
        RobotsBindingErrorCode.INVALID_URL,
        site_url=value,
        target_url="https://example.com/secret?q=data",
        fetched_robots=None,
        fetch_error_code=RobotsFetchErrorCode.TIMEOUT,
    )
    assert value not in str(error)


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com:80/",
        "http://example.com:443/",
        "https://example.com:65536/",
        "https://example.com:+443/",
    ],
)
def test_nondefault_or_malformed_ports_are_mapped_to_disallowed_port(value: str) -> None:
    assert_binding_error(
        RobotsBindingErrorCode.DISALLOWED_PORT,
        site_url=value,
        target_url="https://example.com/",
        fetched_robots=None,
        fetch_error_code=RobotsFetchErrorCode.TIMEOUT,
    )


@pytest.mark.parametrize(
    "target_url",
    [
        "http://example.com/path",
        "https://sub.example.com/path",
        "https://otherexample.com/path",
        "https://example.com.evil.test/path",
        "https://evil-example.com/path",
        "https://192.0.2.2/path",
        "https://[2001:db8::2]/path",
    ],
)
def test_cross_origin_variants_fail_closed(target_url: str) -> None:
    assert_binding_error(
        RobotsBindingErrorCode.CROSS_ORIGIN,
        site_url="https://example.com/",
        target_url=target_url,
        fetched_robots=None,
        fetch_error_code=RobotsFetchErrorCode.TIMEOUT,
    )


@pytest.mark.parametrize(
    ("target_url", "expected"),
    [
        ("https://example.com", "/"),
        ("https://example.com/\u2603?q=\u2713", "/%E2%98%83?q=%E2%9C%93"),
        ("https://example.com/a%2Fb?q=%2F", "/a%2Fb?q=/"),
        ("https://example.com/a;b/@c?x=a:b/c", "/a;b/@c?x=a:b/c"),
        ("https://example.com/path?", "/path"),
        ("https://example.com/path?q=1#discard", "/path?q=1"),
    ],
)
def test_derives_exact_encoded_absolute_path_plus_optional_query(
    target_url: str, expected: str
) -> None:
    assert evaluate(target_url=target_url).target_path == expected


def test_exact_requested_site_provenance_is_required_before_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        binding_module,
        "evaluate_robots_gate",
        lambda **kwargs: pytest.fail("gate called"),
    )
    assert_binding_error(
        RobotsBindingErrorCode.PROVENANCE_MISMATCH,
        site_url="https://EXAMPLE.com:443/path#fragment",
        target_url="https://example.com/target",
        fetched_robots=fetched(requested_site_url="https://example.com/path#fragment"),
        fetch_error_code=None,
    )


@pytest.mark.parametrize(
    ("fetched_robots", "fetch_error_code"),
    [
        (fetched(), None),
        (None, RobotsFetchErrorCode.TIMEOUT),
        (None, RobotsFetchErrorCode.INVALID_URL),
    ],
)
def test_delegates_exactly_once_and_preserves_gate_identity(
    monkeypatch: pytest.MonkeyPatch,
    fetched_robots: FetchedRobots | None,
    fetch_error_code: RobotsFetchErrorCode | None,
) -> None:
    access = RobotsAccessDecision(False, RobotsAccessReason.POLICY, 200, None, None)
    decision = RobotsGateDecision(
        False,
        RobotsGateReason.ACCESS,
        fetched_robots,
        access,
        fetch_error_code,
    )
    calls: list[dict[str, object]] = []

    def fake_gate(**kwargs: object) -> RobotsGateDecision:
        calls.append(kwargs)
        return decision

    monkeypatch.setattr(binding_module, "evaluate_robots_gate", fake_gate)
    result = evaluate(
        target_url="https://example.com/private?q=1#x",
        fetched_robots=fetched_robots,
        fetch_error_code=fetch_error_code,
    )
    assert calls == [
        {
            "fetched_robots": fetched_robots,
            "fetch_error_code": fetch_error_code,
            "target_path": "/private?q=1",
        }
    ]
    assert result.gate_decision is decision


def test_malformed_fetched_value_is_left_for_gate_unchanged() -> None:
    value = FetchedRobots("https://example.com/", "", "", 200, "text/plain", b"", ())
    with pytest.raises(RobotsGateError):
        evaluate(fetched_robots=value, fetch_error_code=None)


def test_product_policy_error_is_not_rewritten(monkeypatch: pytest.MonkeyPatch) -> None:
    error = RobotsPolicyError(RobotsPolicyErrorCode.INVALID_INPUT, "Invalid robots policy input.")

    def fail(**kwargs: object) -> RobotsGateDecision:
        raise error

    monkeypatch.setattr(binding_module, "evaluate_robots_gate", fail)
    with pytest.raises(RobotsPolicyError) as caught:
        evaluate()
    assert caught.value is error


def test_repeated_calls_are_deterministic_and_inputs_are_unchanged() -> None:
    value = fetched()
    before = fields_tuple(value)
    first = evaluate(fetched_robots=value, fetch_error_code=None)
    second = evaluate(fetched_robots=value, fetch_error_code=None)
    assert first == second
    assert fields_tuple(value) == before


def test_binding_is_statically_and_runtime_isolated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    imports: set[str] = set()
    source = inspect.getsource(binding_module)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    assert imports <= {
        "__future__",
        "dataclasses",
        "enum",
        "growth_os.acquisition",
        "growth_os.acquisition._transport",
        "growth_os.robots.gate",
        "yarl",
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
    evaluate()
    assert caplog.records == []


def test_binding_has_no_active_runtime_integration() -> None:
    package_root = Path(binding_module.__file__).parents[1]
    allowed = {Path(binding_module.__file__), Path(robots_package.__file__)}
    for path in package_root.rglob("*.py"):
        if path not in allowed:
            assert "growth_os.robots.binding" not in path.read_text()
