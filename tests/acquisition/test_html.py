from __future__ import annotations

import asyncio
import inspect
import socket
import ssl
from dataclasses import FrozenInstanceError, fields
from typing import Any

import pytest

from growth_os.acquisition import (
    FetchedHtml,
    HtmlFetchError,
    HtmlFetchErrorCode,
    fetch_html,
)
from growth_os.acquisition import html as html_module


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


def assert_fetch_error(error: HtmlFetchError, code: HtmlFetchErrorCode) -> None:
    assert error.code is code
    assert error.status_code is None
    assert str(error) == f"HTML fetch failed: {code.value}"


def test_public_contract_is_exact_and_immutable() -> None:
    import growth_os.acquisition as acquisition

    assert acquisition.__all__ == [
        "HtmlFetchErrorCode",
        "HtmlFetchError",
        "FetchedHtml",
        "fetch_html",
    ]
    assert list(acquisition.HtmlFetchErrorCode) == [
        acquisition.HtmlFetchErrorCode.INVALID_URL,
        acquisition.HtmlFetchErrorCode.DISALLOWED_PORT,
        acquisition.HtmlFetchErrorCode.DNS_FAILURE,
        acquisition.HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        acquisition.HtmlFetchErrorCode.TIMEOUT,
        acquisition.HtmlFetchErrorCode.TLS_FAILURE,
        acquisition.HtmlFetchErrorCode.NETWORK_FAILURE,
        acquisition.HtmlFetchErrorCode.TOO_MANY_REDIRECTS,
        acquisition.HtmlFetchErrorCode.INVALID_REDIRECT,
        acquisition.HtmlFetchErrorCode.HTTP_STATUS,
        acquisition.HtmlFetchErrorCode.UNSUPPORTED_CONTENT_TYPE,
        acquisition.HtmlFetchErrorCode.BODY_TOO_LARGE,
        acquisition.HtmlFetchErrorCode.UNSUPPORTED_CHARSET,
    ]
    assert [member.value for member in acquisition.HtmlFetchErrorCode] == [
        "invalid_url",
        "disallowed_port",
        "dns_failure",
        "disallowed_address",
        "timeout",
        "tls_failure",
        "network_failure",
        "too_many_redirects",
        "invalid_redirect",
        "http_status",
        "unsupported_content_type",
        "body_too_large",
        "unsupported_charset",
    ]
    assert [field.name for field in fields(acquisition.FetchedHtml)] == [
        "requested_url",
        "final_url",
        "status_code",
        "content_type",
        "body",
        "redirect_chain",
    ]
    fetched = acquisition.FetchedHtml(
        "https://example.com/",
        "https://example.com/",
        200,
        "text/html",
        "ok",
        ("https://example.com/",),
    )
    assert fetched == acquisition.FetchedHtml(
        "https://example.com/",
        "https://example.com/",
        200,
        "text/html",
        "ok",
        ("https://example.com/",),
    )
    with pytest.raises(FrozenInstanceError):
        fetched.body = "changed"  # type: ignore[misc]
    assert str(inspect.signature(acquisition.fetch_html)) == "(*, url: 'str') -> 'FetchedHtml'"


@pytest.mark.asyncio
async def test_non_string_url_is_not_coerced() -> None:
    with pytest.raises(TypeError):
        await fetch_html(url=123)  # type: ignore[arg-type]


def test_error_is_stable_redacted_and_status_is_only_exposed_for_http_status() -> None:
    secret_values = (
        "?token=secret#fragment admin:password private-dns cert-detail socket-detail "
        "private-body Header-Value"
    )
    for code in HtmlFetchErrorCode:
        error = HtmlFetchError(code, status_code=418)
        assert error.status_code == (418 if code is HtmlFetchErrorCode.HTTP_STATUS else None)
        assert str(error) == f"HTML fetch failed: {code.value}"
        assert all(value not in str(error) for value in secret_values.split())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTP://Example.COM:80/path?q=One#private", "http://example.com/path?q=One"),
        ("https://Example.COM:443/", "https://example.com/"),
        ("https://[2606:4700:4700::1111]:443/a", "https://[2606:4700:4700::1111]/a"),
        ("https://bücher.example/a", "https://xn--bcher-kva.example/a"),
    ],
)
def test_url_normalization(raw: str, expected: str) -> None:
    assert str(html_module._normalize_url(raw)) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "example.com",
        "ftp://example.com/",
        "http:///missing-host",
        "https://user@example.com/",
        "https://:password@example.com/",
        "https://user:@example.com/",
        "https://@example.com/",
        "https://exa mple.com/",
        "https://exa mple.com:443/",
        "https://[not-ip]/",
        "https://[not-ip]:443/",
        "https://\ud800:443/",
    ],
)
def test_invalid_urls_are_rejected(raw: str) -> None:
    with pytest.raises(HtmlFetchError) as caught:
        html_module._normalize_url(raw)
    assert_fetch_error(caught.value, HtmlFetchErrorCode.INVALID_URL)


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
        "https://example.com:0443/",
        "https://example.com:\t443/",
        "https://[2606:4700:4700::1111]:bad/",
    ],
)
def test_invalid_or_non_default_ports_are_rejected(raw: str) -> None:
    with pytest.raises(HtmlFetchError) as caught:
        html_module._normalize_url(raw)
    assert_fetch_error(caught.value, HtmlFetchErrorCode.DISALLOWED_PORT)


def test_scheme_relative_redirect_port_is_validated_before_normalization() -> None:
    base = html_module._normalize_url("https://example.com/start")
    with pytest.raises(HtmlFetchError) as caught:
        html_module._normalize_url("//other.example:+443/final", redirect=True, base=base)
    assert_fetch_error(caught.value, HtmlFetchErrorCode.DISALLOWED_PORT)


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "192.0.2.1",
        "198.18.0.1",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "2001:db8::1",
        "::ffff:127.0.0.1",
        "fe80::1%lo0",
    ],
)
def test_non_global_addresses_are_rejected(value: str) -> None:
    with pytest.raises(HtmlFetchError) as caught:
        html_module._admit_ip(value)
    assert_fetch_error(caught.value, HtmlFetchErrorCode.DISALLOWED_ADDRESS)


def test_global_addresses_are_admitted() -> None:
    assert html_module._admit_ip("8.8.8.8").value == "8.8.8.8"
    assert html_module._admit_ip("2606:4700:4700::1111").family == socket.AF_INET6


@pytest.mark.asyncio
async def test_dns_answers_are_all_global_deduplicated_and_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 443, 0, 0)),
    ]

    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        assert args == ("example.com", 443)
        assert kwargs == {"family": socket.AF_UNSPEC, "type": socket.SOCK_STREAM}
        return answers

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    addresses = await html_module._resolve(html_module._normalize_url("https://example.com"))
    assert [(item.value, item.family) for item in addresses] == [
        ("8.8.8.8", socket.AF_INET),
        ("2606:4700:4700::1111", socket.AF_INET6),
    ]
    resolver = html_module._PinnedResolver(addresses)
    assert await resolver.resolve("example.com", 443) == [
        {
            "hostname": "example.com",
            "host": "8.8.8.8",
            "port": 443,
            "family": socket.AF_INET,
            "proto": socket.IPPROTO_TCP,
            "flags": 0,
        },
        {
            "hostname": "example.com",
            "host": "2606:4700:4700::1111",
            "port": 443,
            "family": socket.AF_INET6,
            "proto": socket.IPPROTO_TCP,
            "flags": 0,
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answers", "code"),
    [
        ([], HtmlFetchErrorCode.DNS_FAILURE),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
            ],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_UNIX, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_UDP, "", ("8.8.8.8", 443))],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM)],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
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
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
        (
            [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("malformed", 443))],
            HtmlFetchErrorCode.DISALLOWED_ADDRESS,
        ),
    ],
)
async def test_dns_fails_closed_for_empty_mixed_or_malformed_answers(
    monkeypatch: pytest.MonkeyPatch,
    answers: list[tuple[Any, ...]],
    code: HtmlFetchErrorCode,
) -> None:
    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        return answers

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(HtmlFetchError) as caught:
        await html_module._resolve(html_module._normalize_url("https://example.com"))
    assert_fetch_error(caught.value, code)


@pytest.mark.asyncio
async def test_dns_failure_is_mapped_without_upstream_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[Any, ...]]:
        raise socket.gaierror("secret resolver detail")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", failing_getaddrinfo)
    with pytest.raises(HtmlFetchError) as caught:
        await html_module._resolve(html_module._normalize_url("https://example.com"))
    assert_fetch_error(caught.value, HtmlFetchErrorCode.DNS_FAILURE)
    assert "secret" not in str(caught.value)


def fake_html_response(
    *, status: int = 200, content_type: str = "text/html", chunks: list[bytes] | None = None
) -> FakeResponse:
    return FakeResponse(
        status,
        headers={"Content-Type": [content_type]},
        chunks=[b"ok"] if chunks is None else chunks,
    )


@pytest.mark.asyncio
async def test_success_and_per_hop_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    response = fake_html_response(content_type="Text/HTML; charset=utf-8", chunks=[b"h\xffi"])
    session = FakeSession()

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        assert str(url) == "https://example.com/path?q=1"
        return response, session

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    result = await fetch_html(url="https://EXAMPLE.com:443/path?q=1#secret")
    assert result == FetchedHtml(
        requested_url="https://example.com/path?q=1",
        final_url="https://example.com/path?q=1",
        status_code=200,
        content_type="text/html",
        body="h�i",
        redirect_chain=("https://example.com/path?q=1",),
    )
    assert response.closed and session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_redirect_codes_resolve_and_revalidate_each_hop(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    responses = [
        FakeResponse(status, headers={"Location": ["//other.example/final#fragment"]}),
        fake_html_response(chunks=[b"done"]),
    ]
    sessions: list[FakeSession] = []
    resolved: list[str] = []

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        resolved.append(str(url))
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        session = FakeSession()
        sessions.append(session)
        return responses.pop(0), session

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    result = await fetch_html(url="https://example.com/start")
    assert result.redirect_chain == (
        "https://example.com/start",
        "https://other.example/final",
    )
    assert resolved == list(result.redirect_chain)
    assert all(session.closed for session in sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("locations", [[], [""], ["   "], ["/one", "/two"]])
async def test_invalid_redirect_does_not_read_body(
    monkeypatch: pytest.MonkeyPatch, locations: list[str]
) -> None:
    response = FakeResponse(302, headers={"Location": locations}, chunks=[b"secret body"])
    session = FakeSession()

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, session

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.INVALID_REDIRECT)
    assert not response.content.iterated
    assert response.closed and session.closed


@pytest.mark.asyncio
async def test_sixth_redirect_fails_without_requesting_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [FakeResponse(302, headers={"Location": [f"/{index + 1}"]}) for index in range(6)]
    requests = 0

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        nonlocal requests
        requests += 1
        return responses.pop(0), FakeSession()

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/0")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.TOO_MANY_REDIRECTS)
    assert requests == 6


@pytest.mark.asyncio
async def test_http_failure_body_is_unread_and_only_status_is_exposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(418, chunks=[b"private failure body"])

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, FakeSession()

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/")
    assert caught.value.code is HtmlFetchErrorCode.HTTP_STATUS
    assert caught.value.status_code == 418
    assert str(caught.value) == "HTML fetch failed: http_status"
    assert not response.content.iterated


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ["", "text/plain", "text/htmlish", "application/json"])
async def test_unsupported_content_type_is_rejected_before_body(
    monkeypatch: pytest.MonkeyPatch, content_type: str
) -> None:
    headers = {} if not content_type else {"Content-Type": [content_type]}
    response = FakeResponse(200, headers=headers, chunks=[b"private body"])

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return response, FakeSession()

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.UNSUPPORTED_CONTENT_TYPE)
    assert not response.content.iterated


@pytest.mark.asyncio
async def test_body_limit_accepts_exact_limit_and_rejects_first_extra_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        fake_html_response(chunks=[b"a" * 1_000_000, b"b" * 1_000_000]),
        fake_html_response(chunks=[b"a" * 2_000_000, b"x"]),
    ]

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return responses.pop(0), FakeSession()

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    accepted = await fetch_html(url="https://example.com/exact")
    assert len(accepted.body) == 2_000_000
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/extra")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.BODY_TOO_LARGE)


@pytest.mark.asyncio
async def test_charset_default_declared_unknown_and_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        fake_html_response(chunks=["café".encode()]),
        fake_html_response(
            content_type="application/xhtml+xml; charset=latin-1", chunks=[b"caf\xe9"]
        ),
        fake_html_response(content_type='text/html; charset = "latin-1"', chunks=[b"caf\xe9"]),
        fake_html_response(content_type="text/html; charset=no-such-codec"),
    ]

    async def fake_resolve(url: object) -> tuple[Any, ...]:
        return (html_module._admit_ip("8.8.8.8"),)

    async def fake_request(url: object, addresses: object) -> tuple[Any, Any]:
        return responses.pop(0), FakeSession()

    monkeypatch.setattr(html_module, "_resolve", fake_resolve)
    monkeypatch.setattr(html_module, "_request_hop", fake_request)
    assert (await fetch_html(url="https://example.com/default")).body == "café"
    declared = await fetch_html(url="https://example.com/declared")
    assert declared.body == "café"
    assert declared.content_type == "application/xhtml+xml"
    assert (await fetch_html(url="https://example.com/spaced")).body == "café"
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/unknown")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.UNSUPPORTED_CHARSET)


@pytest.mark.asyncio
async def test_timeout_is_mapped_and_cancellation_is_never_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(url: object) -> FetchedHtml:
        raise TimeoutError("private timeout detail")

    monkeypatch.setattr(html_module, "_fetch", fake_fetch)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/?secret=yes")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.TIMEOUT)

    async def cancelled_fetch(url: object) -> FetchedHtml:
        raise asyncio.CancelledError

    monkeypatch.setattr(html_module, "_fetch", cancelled_fetch)
    with pytest.raises(asyncio.CancelledError):
        await fetch_html(url="https://example.com/")


@pytest.mark.asyncio
async def test_tls_and_network_failures_are_redacted_and_mapped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def tls_failure(url: object) -> FetchedHtml:
        raise ssl.SSLError("private certificate detail")

    monkeypatch.setattr(html_module, "_fetch", tls_failure)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/?secret=yes")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.TLS_FAILURE)

    async def network_failure(url: object) -> FetchedHtml:
        raise html_module.aiohttp.ClientError("private socket detail")

    monkeypatch.setattr(html_module, "_fetch", network_failure)
    with pytest.raises(HtmlFetchError) as caught:
        await fetch_html(url="https://example.com/?secret=yes")
    assert_fetch_error(caught.value, HtmlFetchErrorCode.NETWORK_FAILURE)
    assert caplog.records == []


@pytest.mark.asyncio
async def test_request_hop_uses_exact_fail_closed_transport_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector_kwargs: dict[str, Any] = {}
    session_kwargs: dict[str, Any] = {}
    get_calls: list[tuple[object, dict[str, Any]]] = []
    response = fake_html_response()

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

    monkeypatch.setattr(html_module.aiohttp, "TCPConnector", CapturingConnector)
    monkeypatch.setattr(html_module.aiohttp, "ClientSession", CapturingSession)
    monkeypatch.setattr(html_module.aiohttp, "DummyCookieJar", DummyJar)
    address = html_module._admit_ip("8.8.8.8")
    url = html_module._normalize_url("https://Original.Example/path")
    returned_response, session = await html_module._request_hop(url, (address,))
    assert returned_response is response
    assert get_calls == [(url, {"allow_redirects": False})]
    assert str(get_calls[0][0]) == "https://original.example/path"
    assert connector_kwargs.keys() == {"resolver", "use_dns_cache"}
    assert connector_kwargs["use_dns_cache"] is False
    assert isinstance(connector_kwargs["resolver"], html_module._PinnedResolver)
    assert await connector_kwargs["resolver"].resolve("original.example", 443) == [
        {
            "hostname": "original.example",
            "host": "8.8.8.8",
            "port": 443,
            "family": socket.AF_INET,
            "proto": socket.IPPROTO_TCP,
            "flags": 0,
        }
    ]
    assert session_kwargs["connector"] is not None
    assert session_kwargs["connector_owner"] is True
    assert isinstance(session_kwargs["cookie_jar"], DummyJar)
    assert session_kwargs["trust_env"] is False
    assert session_kwargs["headers"] == {
        "User-Agent": "GrowthOSBot/0.1",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
    }
    assert session_kwargs["auto_decompress"] is True
    timeout = session_kwargs["timeout"]
    assert timeout.total is None
    assert timeout.connect == 5
    assert timeout.sock_connect == 5
    assert timeout.sock_read == 10
    assert not {"auth", "proxy", "proxy_auth", "ssl", "server_hostname"} & session_kwargs.keys()
    await session.close()


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

    monkeypatch.setattr(html_module.aiohttp, "TCPConnector", CapturingConnector)
    monkeypatch.setattr(html_module.aiohttp, "ClientSession", FailingConstructor)
    with pytest.raises(RuntimeError):
        await html_module._request_hop(
            html_module._normalize_url("https://example.com/"),
            (html_module._admit_ip("8.8.8.8"),),
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

    monkeypatch.setattr(html_module.aiohttp, "ClientSession", FailingGetSession)
    with pytest.raises(OSError):
        await html_module._request_hop(
            html_module._normalize_url("https://example.com/"),
            (html_module._admit_ip("8.8.8.8"),),
        )
    assert sessions[-1].closed
    assert connectors[-1].closed
