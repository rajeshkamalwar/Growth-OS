from __future__ import annotations

import asyncio
import inspect
import ssl
from dataclasses import FrozenInstanceError, fields
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
async def test_redirects_are_revalidated_and_chain_tracks_only_requested_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        FakeResponse(302, headers={"Location": ["//other.example/next#drop"]}),
        FakeResponse(headers={"Content-Type": ["text/plain"]}, chunks=[b"done"]),
    ]
    resolved: list[str] = []

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        resolved.append(str(url))
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return responses.pop(0), FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    result = await fetch_robots(site_url="https://example.com/start?q=1")
    assert result.robots_url == "https://example.com/robots.txt"
    assert result.redirect_chain == (
        "https://example.com/robots.txt",
        "https://other.example/next",
    )
    assert resolved == list(result.redirect_chain)


@pytest.mark.asyncio
@pytest.mark.parametrize("locations", [[], [""], ["/one", "/two"], ["https://[bad"]])
async def test_invalid_redirect_is_redacted_and_unread(
    monkeypatch: pytest.MonkeyPatch, locations: list[str]
) -> None:
    response = FakeResponse(302, headers={"Location": locations}, chunks=[b"secret"])

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.INVALID_REDIRECT)
    assert not response.content.iterated


@pytest.mark.asyncio
async def test_sixth_redirect_fails_before_next_target_is_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [FakeResponse(302, headers={"Location": [f"/{i + 1}"]}) for i in range(6)]
    requested: list[str] = []

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        requested.append(str(url))
        return responses.pop(0), FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/start")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.TOO_MANY_REDIRECTS)
    assert len(requested) == 6


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

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (robots_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/")
    assert_fetch_error(caught.value, code)
    assert not response.content.iterated


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

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return responses.pop(0), FakeSession()

    monkeypatch.setattr(robots_module, "_resolve", fake_resolve)
    monkeypatch.setattr(robots_module, "_request_hop", fake_request)
    assert len((await fetch_robots(site_url="https://example.com/exact")).body or b"") == 512_000
    with pytest.raises(RobotsFetchError) as caught:
        await fetch_robots(site_url="https://example.com/extra")
    assert_fetch_error(caught.value, RobotsFetchErrorCode.BODY_TOO_LARGE)


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
