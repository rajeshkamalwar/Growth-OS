from __future__ import annotations

import asyncio
import codecs
import ssl
from dataclasses import dataclass
from email.message import Message
from enum import StrEnum
from typing import Final

import aiohttp
from yarl import URL

from growth_os.acquisition import _transport

_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_ALLOWED_CONTENT_TYPES: Final = frozenset({"text/html", "application/xhtml+xml"})
_HEADERS: Final = {
    "User-Agent": "GrowthOSBot/0.1",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "identity",
}
_BODY_LIMIT: Final = 2_000_000
_CHUNK_SIZE: Final = 64 * 1024
_MAX_REDIRECTS: Final = 5


class HtmlFetchErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    DISALLOWED_PORT = "disallowed_port"
    DNS_FAILURE = "dns_failure"
    DISALLOWED_ADDRESS = "disallowed_address"
    TIMEOUT = "timeout"
    TLS_FAILURE = "tls_failure"
    NETWORK_FAILURE = "network_failure"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    INVALID_REDIRECT = "invalid_redirect"
    HTTP_STATUS = "http_status"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    BODY_TOO_LARGE = "body_too_large"
    UNSUPPORTED_CHARSET = "unsupported_charset"


class HtmlFetchError(RuntimeError):
    code: HtmlFetchErrorCode
    status_code: int | None

    def __init__(self, code: HtmlFetchErrorCode, *, status_code: int | None = None) -> None:
        self.code = code
        self.status_code = status_code if code is HtmlFetchErrorCode.HTTP_STATUS else None
        super().__init__(f"HTML fetch failed: {code.value}")


@dataclass(frozen=True, slots=True)
class FetchedHtml:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: str
    redirect_chain: tuple[str, ...]


_Address = _transport.Address
_PinnedResolver = _transport.PinnedResolver


def _normalize_url(raw_url: str, *, redirect: bool = False, base: URL | None = None) -> URL:
    try:
        return _transport.normalize_url(raw_url, redirect=redirect, base=base)
    except _transport.TransportError as exc:
        raise HtmlFetchError(HtmlFetchErrorCode(exc.code)) from exc


def _admit_ip(value: str) -> _Address:
    try:
        return _transport.admit_ip(value)
    except _transport.TransportError as exc:
        raise HtmlFetchError(HtmlFetchErrorCode(exc.code)) from exc


async def _resolve(url: URL) -> tuple[_Address, ...]:
    try:
        return await _transport.resolve(url)
    except _transport.TransportError as exc:
        raise HtmlFetchError(HtmlFetchErrorCode(exc.code)) from exc


def _content_type_and_charset(response: aiohttp.ClientResponse) -> tuple[str, str]:
    values = response.headers.getall("Content-Type", [])
    if len(values) != 1:
        raise HtmlFetchError(HtmlFetchErrorCode.UNSUPPORTED_CONTENT_TYPE)
    message = Message()
    message["Content-Type"] = values[0]
    media_type = message.get_content_type().lower()
    if media_type not in _ALLOWED_CONTENT_TYPES:
        raise HtmlFetchError(HtmlFetchErrorCode.UNSUPPORTED_CONTENT_TYPE)
    charset = "utf-8"
    declared = [
        value for name, value in message.get_params(failobj=[])[1:] if name.lower() == "charset"
    ]
    if len(declared) > 1 or (declared and not declared[0]):
        raise HtmlFetchError(HtmlFetchErrorCode.UNSUPPORTED_CHARSET)
    if declared:
        charset = declared[0]
    try:
        codecs.lookup(charset)
    except (LookupError, ValueError) as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.UNSUPPORTED_CHARSET) from exc
    return media_type, charset


async def _read_body(response: aiohttp.ClientResponse, charset: str) -> str:
    body = bytearray()
    async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
        if len(body) + len(chunk) > _BODY_LIMIT:
            raise HtmlFetchError(HtmlFetchErrorCode.BODY_TOO_LARGE)
        body.extend(chunk)
    try:
        return body.decode(charset, errors="replace")
    except (LookupError, UnicodeError) as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.UNSUPPORTED_CHARSET) from exc


async def _request_hop(
    url: URL, addresses: tuple[_Address, ...]
) -> tuple[aiohttp.ClientResponse, aiohttp.ClientSession]:
    return await _transport.request_hop(url, addresses, _HEADERS)


async def _fetch(url: URL) -> FetchedHtml:
    requested_url = str(url)
    chain: list[str] = []
    redirect_count = 0
    current = url
    while True:
        chain.append(str(current))
        addresses = await _resolve(current)
        response: aiohttp.ClientResponse | None = None
        session: aiohttp.ClientSession | None = None
        try:
            response, session = await _request_hop(current, addresses)
            if response.status in _REDIRECT_STATUSES:
                if redirect_count >= _MAX_REDIRECTS:
                    raise HtmlFetchError(HtmlFetchErrorCode.TOO_MANY_REDIRECTS)
                locations = response.headers.getall("Location", [])
                if len(locations) != 1 or not locations[0].strip():
                    raise HtmlFetchError(HtmlFetchErrorCode.INVALID_REDIRECT)
                current = _normalize_url(locations[0], redirect=True, base=current)
                redirect_count += 1
                continue
            if response.status != 200:
                raise HtmlFetchError(HtmlFetchErrorCode.HTTP_STATUS, status_code=response.status)
            content_type, charset = _content_type_and_charset(response)
            body = await _read_body(response, charset)
            return FetchedHtml(
                requested_url=requested_url,
                final_url=str(current),
                status_code=200,
                content_type=content_type,
                body=body,
                redirect_chain=tuple(chain),
            )
        finally:
            if response is not None:
                response.close()
            if session is not None:
                await session.close()


async def fetch_html(*, url: str) -> FetchedHtml:
    if not isinstance(url, str):
        raise TypeError("url must be a string")
    try:
        normalized = _normalize_url(url)
        async with asyncio.timeout(30):
            return await _fetch(normalized)
    except asyncio.CancelledError:
        raise
    except HtmlFetchError:
        raise
    except TimeoutError as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.TIMEOUT) from exc
    except (
        aiohttp.ClientConnectorCertificateError,
        aiohttp.ClientConnectorSSLError,
        aiohttp.ClientSSLError,
        aiohttp.ServerFingerprintMismatch,
        ssl.SSLError,
    ) as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.TLS_FAILURE) from exc
    except aiohttp.ClientError as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.NETWORK_FAILURE) from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.NETWORK_FAILURE) from exc
