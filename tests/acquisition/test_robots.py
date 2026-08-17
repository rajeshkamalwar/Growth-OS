from __future__ import annotations

import ast
import asyncio
import inspect
import socket
import ssl
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any

import pytest

from growth_os.acquisition import (
    FetchedRobots,
    RobotsFetchError,
    RobotsFetchErrorCode,
    fetch_robots,
)
from growth_os.acquisition import robots as robots_module


class FakeHeaders:
    def __init__(self, values: dict[str, list[str]] | None = None) -> None:
        self.values = values or {}

    def getall(self, name: str, default: list[str]) -> list[str]:
        return self.values.get(name, default)


class FakeContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.iterated = False

    async def iter_chunked(self, size: int) -> Any:
        assert size == 64 * 1024
        self.iterated = True
        for chunk in self.chunks:
            yield chunk


class BlockingContent:
    def __init__(self, started: asyncio.Event, *, timeout: bool) -> None:
        self.started = started
        self.timeout = timeout

    async def iter_chunked(self, size: int) -> Any:
        assert size == 64 * 1024
        self.started.set()
        if self.timeout:
            raise TimeoutError("private body timeout detail")
        await asyncio.Future()
        yield b"unreachable"


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        *,
        headers: dict[str, list[str]] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self.headers = FakeHeaders(headers)
        self.content = FakeContent(chunks or [])
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def deny_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def denied(*args: object, **kwargs: object) -> Any:
        raise AssertionError("real network access is forbidden in acquisition tests")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", denied)
    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", denied)


def assert_fetch_error(error: RobotsFetchError, code: RobotsFetchErrorCode) -> None:
    assert error.code is code
    assert str(error) == f"Robots fetch failed: {code.value}"
    assert error.args == (f"Robots fetch failed: {code.value}",)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_public_contract_is_exact_and_immutable() -> None:
    import growth_os.acquisition as acquisition

    assert acquisition.__all__ == [
        "HtmlFetchErrorCode",
        "HtmlFetchError",
        "FetchedHtml",
        "fetch_html",
        "RobotsFetchErrorCode",
        "RobotsFetchError",
        "FetchedRobots",
        "fetch_robots",
    ]
    assert [member.value for member in RobotsFetchErrorCode] == [
        "invalid_url",
        "disallowed_port",
        "dns_failure",
        "disallowed_address",
        "timeout",
        "tls_failure",
        "network_failure",
        "too_many_redirects",
        "invalid_redirect",
        "unsupported_content_type",
        "body_too_large",
        "unsupported_charset",
    ]
    assert [field.name for field in fields(FetchedRobots)] == [
        "requested_site_url",
        "robots_url",
        "final_url",
        "status_code",
        "content_type",
        "body",
        "redirect_chain",
    ]
    result = FetchedRobots("a", "b", "c", 200, "text/plain", b"x", ("b", "c"))
    assert result == FetchedRobots("a", "b", "c", 200, "text/plain", b"x", ("b", "c"))
    with pytest.raises(FrozenInstanceError):
        result.body = b"changed"  # type: ignore[misc]
    assert str(inspect.signature(fetch_robots)) == "(*, site_url: 'str') -> 'FetchedRobots'"


@pytest.mark.asyncio
async def test_non_string_site_url_is_not_coerced() -> None:
    with pytest.raises(TypeError, match="^site_url must be a string$"):
        await fetch_robots(site_url=123)  # type: ignore[arg-type]


def test_errors_are_stable_and_redacted() -> None:
    for code in RobotsFetchErrorCode:
        error = RobotsFetchError(code)
        assert_fetch_error(error, code)
        assert "example.com" not in str(error)
        assert "secret" not in str(error)


@pytest.mark.asyncio
async def test_derives_root_url_and_preserves_normalized_requested_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(
        headers={"Content-Type": ["Text/Plain; charset=UTF-8"]}, chunks=[b"\xef\xbb\xbfraw\n"]
    )
    session = FakeSession()
    requested: list[str] = []

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        requested.append(str(url))
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, session

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    result = await fetch_robots(
        site_url="HTTPS://BÜCHER.example:443/some/path;params?q=One#private"
    )
    assert result == FetchedRobots(
        requested_site_url="https://xn--bcher-kva.example/some/path;params?q=One",
        robots_url="https://xn--bcher-kva.example/robots.txt",
        final_url="https://xn--bcher-kva.example/robots.txt",
        status_code=200,
        content_type="text/plain",
        body=b"\xef\xbb\xbfraw\n",
        redirect_chain=("https://xn--bcher-kva.example/robots.txt",),
    )
    assert requested == [result.robots_url]
    assert response.closed and session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "requested", "robots_url"),
    [
        (
            "HTTP://Example.COM:80/path?q=One#private",
            "http://example.com/path?q=One",
            "http://example.com/robots.txt",
        ),
        ("https://Example.COM:0443/", "https://example.com/", "https://example.com/robots.txt"),
        (
            "https://[2606:4700:4700::1111]:443/a?x=1#drop",
            "https://[2606:4700:4700::1111]/a?x=1",
            "https://[2606:4700:4700::1111]/robots.txt",
        ),
        (
            "https://bücher.example/a;b?x=1#drop",
            "https://xn--bcher-kva.example/a;b?x=1",
            "https://xn--bcher-kva.example/robots.txt",
        ),
    ],
)
async def test_initial_url_normalization_matrix_and_root_derivation(
    monkeypatch: pytest.MonkeyPatch, raw: str, requested: str, robots_url: str
) -> None:
    response = FakeResponse(404)

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        assert str(url) == robots_url
        return response, FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    result = await fetch_robots(site_url=raw)
    assert result.requested_site_url == requested
    assert result.robots_url == robots_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "example.com",
        "//example.com/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "http:///missing-host",
        "https://user@example.com/",
        "https://:password@example.com/",
        "https://user:@example.com/",
        "https://@example.com/",
        "https://exa mple.com/",
        "https://exa mple.com:443/",
        "https://foo_bar.example/",
        "https://%65xample.com/",
        "https://example.com%2e/",
        "https://a..example/",
        "https://-foo.example/",
        "https://foo-.example/",
        "https://[not-ip]/",
        "https://[not-ip]:443/",
        "https://\ud800:443/",
    ],
)
async def test_complete_invalid_initial_url_matrix_fails_before_io(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid URL must fail before I/O")

    monkeypatch.setattr(robots_module, "_resolve", forbidden)
    monkeypatch.setattr(robots_module, "_request_hop", forbidden)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url=raw)
    assert_fetch_error(caught.value, RobotsFetchErrorCode.INVALID_URL)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com:443/",
        "https://example.com:80/",
        "https://example.com:0/",
        "https://example.com:65536/",
        "https://example.com:not-a-port/",
        "https://example.com:/",
        "https://example.com:+443/",
        "https://example.com:0080/",
        "https://example.com:\t443/",
        "https://[2606:4700:4700::1111]:bad/",
    ],
)
async def test_complete_disallowed_initial_port_matrix_fails_before_io(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    async def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid port must fail before I/O")

    monkeypatch.setattr(robots_module, "_resolve", forbidden)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url=raw)
    assert_fetch_error(caught.value, RobotsFetchErrorCode.DISALLOWED_PORT)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ([], RobotsFetchErrorCode.DNS_FAILURE),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_UDP, "", ("8.8.8.8", 443))],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM)],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [
                (
                    socket.AF_INET6,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    ("2606:4700:4700::1111", 443, 0, 7),
                )
            ],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("malformed", 443))],
            RobotsFetchErrorCode.DISALLOWED_ADDRESS,
        ),
    ],
)
async def test_fetch_robots_rejects_empty_private_mixed_and_malformed_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
    answers: list[tuple[Any, ...]],
    code: RobotsFetchErrorCode,
) -> None:
    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return answers

    async def forbidden_request(*args: object, **kwargs: object) -> Any:
        raise AssertionError("unadmitted DNS answers must never be requested")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(robots_module, "_request_hop", forbidden_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/")
    assert_fetch_error(caught.value, code)


@pytest.mark.asyncio
async def test_fetch_robots_maps_dns_failure_without_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_getaddrinfo(*args: object, **kwargs: object) -> Any:
        raise socket.gaierror("secret resolver detail")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", failing_getaddrinfo)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.DNS_FAILURE)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [204, 301 + 3, 400, 404, 500])
async def test_terminal_non_200_is_returned_without_reading_body(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    response = FakeResponse(status, chunks=[b"private body"])

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    result = await fetch_robots(site_url="https://example.com/path")
    assert result.status_code == status
    assert result.content_type is None and result.body is None
    assert not response.content.iterated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("../next?q=1#drop", "https://example.com/next?q=1"),
        ("https://example.com/absolute", "https://example.com/absolute"),
        ("//other.example/cross", "https://other.example/cross"),
    ],
)
async def test_redirect_variants_are_revalidated_and_track_only_requested_urls(
    monkeypatch: pytest.MonkeyPatch, location: str, expected: str
) -> None:
    responses = [
        FakeResponse(302, headers={"Location": [location]}),
        FakeResponse(headers={"Content-Type": ["text/plain"]}, chunks=[b"done"]),
    ]
    all_responses = list(responses)
    resolved: list[str] = []
    sessions: list[FakeSession] = []

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        resolved.append(str(url))
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        session = FakeSession()
        sessions.append(session)
        return responses.pop(0), session

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    result = await fetch_robots(site_url="https://example.com/start?q=1")
    assert result.robots_url == "https://example.com/robots.txt"
    assert result.redirect_chain == (
        "https://example.com/robots.txt",
        expected,
    )
    assert resolved == list(result.redirect_chain)
    assert all(response.closed for response in all_responses)
    assert all(session.closed for session in sessions)


@pytest.mark.asyncio
async def test_redirect_hop_is_reresolved_and_rebinding_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = iter(
        [
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
        ]
    )
    requested: list[str] = []
    response = FakeResponse(302, headers={"Location": ["/next"]})
    session = FakeSession()

    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return next(answers)

    async def fake_request(url: object, addresses: tuple[Any, ...]) -> tuple[Any, Any]:
        requested.append(str(url))
        assert [address.value for address in addresses] == ["8.8.8.8"]
        return response, session

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/start")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.DISALLOWED_ADDRESS)
    assert requested == ["https://example.com/robots.txt"]
    assert response.closed and session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("locations", [[], [""], ["   "], ["/one", "/two"], ["https://[bad"]])
async def test_invalid_redirect_is_redacted_and_unread(
    monkeypatch: pytest.MonkeyPatch, locations: list[str]
) -> None:
    response = FakeResponse(302, headers={"Location": locations}, chunks=[b"secret"])
    session = FakeSession()

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, session

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.INVALID_REDIRECT)
    assert not response.content.iterated
    assert response.closed and session.closed


@pytest.mark.asyncio
async def test_sixth_redirect_fails_before_next_target_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [FakeResponse(302, headers={"Location": [f"/{i + 1}"]}) for i in range(6)]
    all_responses = list(responses)
    requested: list[str] = []
    sessions: list[FakeSession] = []

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        requested.append(str(url))
        session = FakeSession()
        sessions.append(session)
        return responses.pop(0), session

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/start")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.TOO_MANY_REDIRECTS)
    assert len(requested) == 6
    assert all(response.closed for response in all_responses)
    assert all(session.closed for session in sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header", "code"),
    [
        (None, RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (["text/plain", "text/plain"], RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (["text/html"], RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (["text/plain, text/plain"], RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (["text/plain; garbage"], RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (["text/plain; =x"], RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (['text/plain; x="unterminated'], RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE),
        (["text/plain; charset="], RobotsFetchErrorCode.UNSUPPORTED_CHARSET),
        (["text/plain; charset=utf-8; charset=utf-8"], RobotsFetchErrorCode.UNSUPPORTED_CHARSET),
        (["text/plain; charset=latin-1"], RobotsFetchErrorCode.UNSUPPORTED_CHARSET),
        (["text/plain; charset*=utf-8''utf-8"], RobotsFetchErrorCode.UNSUPPORTED_CHARSET),
        (
            ["text/plain; charset*0*=utf-8''utf; charset*1*=-8"],
            RobotsFetchErrorCode.UNSUPPORTED_CHARSET,
        ),
    ],
)
async def test_content_type_and_charset_are_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    header: list[str] | None,
    code: RobotsFetchErrorCode,
) -> None:
    response = FakeResponse(
        headers={} if header is None else {"Content-Type": header}, chunks=[b"x"]
    )
    session = FakeSession()

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, session

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/")
    assert_fetch_error(caught.value, code)
    assert not response.content.iterated
    assert response.closed and session.closed


@pytest.mark.asyncio
async def test_body_limit_accepts_512000_and_rejects_byte_512001(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        FakeResponse(headers={"Content-Type": ["text/plain"]}, chunks=[b"a" * 512_000]),
        FakeResponse(headers={"Content-Type": ["text/plain"]}, chunks=[b"a" * 512_000, b"x"]),
    ]

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    sessions: list[FakeSession] = []

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        session = FakeSession()
        sessions.append(session)
        return responses.pop(0), session

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    assert len((await fetch_robots(site_url="https://example.com/exact")).body or b"") == 512_000
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/extra")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.BODY_TOO_LARGE)
    assert all(session.closed for session in sessions)


@pytest.mark.asyncio
async def test_request_hop_uses_exact_fail_closed_transport_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector_kwargs: dict[str, Any] = {}
    session_kwargs: dict[str, Any] = {}
    get_calls: list[tuple[object, dict[str, Any]]] = []
    response = FakeResponse()

    class CapturingConnector:
        def __init__(self, **kwargs: Any) -> None:
            connector_kwargs.update(kwargs)

        async def close(self) -> None:
            return None

    class CapturingSession(FakeSession):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            session_kwargs.update(kwargs)

        async def get(self, url: object, **kwargs: Any) -> FakeResponse:
            get_calls.append((url, kwargs))
            return response

    class DummyJar:
        pass

    monkeypatch.setattr(robots_module.aiohttp, "TCPConnector", CapturingConnector)
    monkeypatch.setattr(robots_module.aiohttp, "ClientSession", CapturingSession)
    monkeypatch.setattr(robots_module.aiohttp, "DummyCookieJar", DummyJar)
    address = robots_module._admit_ip("8.8.8.8")
    url = robots_module._normalize_url("https://Original.Example/robots.txt")
    returned, session = await robots_module._request_hop(url, (address,))
    assert returned is response
    assert get_calls == [(url, {"allow_redirects": False})]
    assert connector_kwargs.keys() == {"resolver", "use_dns_cache"}
    assert connector_kwargs["use_dns_cache"] is False
    resolver = connector_kwargs["resolver"]
    assert isinstance(resolver, robots_module._PinnedResolver)
    assert await resolver.resolve("original.example", 443) == [
        {
            "hostname": "original.example",
            "host": "8.8.8.8",
            "port": 443,
            "family": address.family,
            "proto": 6,
            "flags": 0,
        }
    ]
    assert session_kwargs["connector_owner"] is True
    assert isinstance(session_kwargs["cookie_jar"], DummyJar)
    assert session_kwargs["trust_env"] is False
    assert session_kwargs["headers"] == {
        "User-Agent": "GrowthOSBot/0.1",
        "Accept": "text/plain",
        "Accept-Encoding": "identity",
    }
    timeout = session_kwargs["timeout"]
    assert timeout.total is None
    assert timeout.connect == timeout.sock_connect == 5
    assert timeout.sock_read == 10
    assert session_kwargs["auto_decompress"] is True
    assert "ssl" not in connector_kwargs and "ssl" not in get_calls[0][1]
    await session.close()


@pytest.mark.asyncio
async def test_timeout_tls_network_and_cancellation_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(error: BaseException) -> FetchedRobots:
        raise error

    for error, code in (
        (TimeoutError("secret"), RobotsFetchErrorCode.TIMEOUT),
        (ssl.SSLError("secret"), RobotsFetchErrorCode.TLS_FAILURE),
        (robots_module.aiohttp.ClientError("secret"), RobotsFetchErrorCode.NETWORK_FAILURE),
    ):
        monkeypatch.setattr(robots_module, "_fetch", lambda *args, error=error: fail(error))
        with pytest.raises(RobotsFetchError) as caught:
            await fetch_robots(site_url="https://example.com/")
        assert_fetch_error(caught.value, code)

    monkeypatch.setattr(robots_module, "_fetch", lambda *args: fail(asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await fetch_robots(site_url="https://example.com/")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancellation"])
async def test_active_body_timeout_and_cancellation_close_all_hop_resources(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    started = asyncio.Event()
    connectors: list[Any] = []
    sessions: list[Any] = []
    responses: list[FakeResponse] = []

    class CapturingConnector:
        def __init__(self, **kwargs: Any) -> None:
            self.closed = False
            connectors.append(self)

        async def close(self) -> None:
            self.closed = True

    class ActiveSession(FakeSession):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            self.connector = kwargs["connector"]
            sessions.append(self)

        async def get(self, url: object, **kwargs: Any) -> FakeResponse:
            response = FakeResponse(headers={"Content-Type": ["text/plain"]})
            response.content = BlockingContent(started, timeout=not cancel)  # type: ignore[assignment]
            responses.append(response)
            return response

        async def close(self) -> None:
            await super().close()
            await self.connector.close()

    class DummyJar:
        pass

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module.aiohttp, "TCPConnector", CapturingConnector)
    monkeypatch.setattr(robots_module.aiohttp, "ClientSession", ActiveSession)
    monkeypatch.setattr(robots_module.aiohttp, "DummyCookieJar", DummyJar)

    task = asyncio.create_task(fetch_robots(site_url="https://example.com/"))
    await started.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RobotsFetchError) as caught:
            await task
        assert_fetch_error(caught.value, RobotsFetchErrorCode.TIMEOUT)
    assert responses[0].closed
    assert sessions[0].closed
    assert connectors[0].closed


@pytest.mark.asyncio
async def test_request_hop_closes_connector_and_session_on_construction_or_get_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connectors: list[Any] = []

    class CapturingConnector:
        def __init__(self, **kwargs: Any) -> None:
            self.closed = False
            connectors.append(self)

        async def close(self) -> None:
            self.closed = True

    class FailingConstructor:
        def __init__(self, **kwargs: Any) -> None:
            raise RuntimeError("private constructor detail")

    monkeypatch.setattr(robots_module.aiohttp, "TCPConnector", CapturingConnector)
    monkeypatch.setattr(robots_module.aiohttp, "ClientSession", FailingConstructor)
    with pytest.raises(RuntimeError):
        await robots_module._request_hop(
            robots_module._normalize_url("https://example.com/robots.txt"),
            (robots_module._admit_ip("8.8.8.8"),),
        )
    assert connectors[-1].closed

    sessions: list[FakeSession] = []

    class FailingGetSession(FakeSession):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__()
            self.connector = kwargs["connector"]
            sessions.append(self)

        async def get(self, url: object, **kwargs: Any) -> FakeResponse:
            raise OSError("private socket detail")

        async def close(self) -> None:
            await super().close()
            await self.connector.close()

    monkeypatch.setattr(robots_module.aiohttp, "ClientSession", FailingGetSession)
    with pytest.raises(OSError):
        await robots_module._request_hop(
            robots_module._normalize_url("https://example.com/robots.txt"),
            (robots_module._admit_ip("8.8.8.8"),),
        )
    assert sessions[-1].closed
    assert connectors[-1].closed


def test_robots_acquisition_is_statically_isolated_from_forbidden_layers() -> None:
    acquisition_dir = Path(robots_module.__file__).parent
    imports: set[str] = set()
    for path in acquisition_dir.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.add(node.module)
    forbidden = {
        "fastapi",
        "sqlalchemy",
        "growth_os.api",
        "growth_os.db",
        "growth_os.evidence",
        "growth_os.execution",
        "growth_os.repositories",
        "growth_os.robots",
        "growth_os.services",
    }
    assert not any(
        imported == boundary or imported.startswith(f"{boundary}.")
        for imported in imports
        for boundary in forbidden
    )

    for path in acquisition_dir.parent.rglob("*.py"):
        if acquisition_dir not in path.parents:
            source = path.read_text()
            if path.parent.name != "robots" or path.name not in {"binding.py", "gate.py"}:
                assert "growth_os.acquisition" not in source
            assert "fetch_robots" not in source


@pytest.mark.asyncio
async def test_fetch_robots_has_no_logging_or_policy_runtime_integration(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    response = FakeResponse(404, chunks=[b"must remain unread"])

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    result = await fetch_robots(site_url="https://example.com/private?q=secret")
    assert result.status_code == 404
    assert not response.content.iterated
    assert caplog.records == []
