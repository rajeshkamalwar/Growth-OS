from __future__ import annotations

import asyncio
import re
import ssl
from dataclasses import dataclass
from email.message import Message
from enum import StrEnum
from typing import Final

import aiohttp
from yarl import URL

from growth_os.acquisition import _transport

_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_HEADERS: Final = {
    "User-Agent": "GrowthOSBot/0.1",
    "Accept": "text/plain",
    "Accept-Encoding": "identity",
}
_BODY_LIMIT: Final = 512_000
_CHUNK_SIZE: Final = 64 * 1024
_MAX_REDIRECTS: Final = 5
_TOKEN: Final = r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_QUOTED: Final = r'"(?:[\t !#-\[\]-~]|\\[\t -~])*"'
_CONTENT_TYPE_PATTERN: Final = re.compile(
    rf"{_TOKEN}/{_TOKEN}(?:\s*;\s*{_TOKEN}\s*=\s*(?:{_TOKEN}|{_QUOTED}))*\s*"
)


class RobotsFetchErrorCode(StrEnum):
    INVALID_URL = "invalid_url"
    DISALLOWED_PORT = "disallowed_port"
    DNS_FAILURE = "dns_failure"
    DISALLOWED_ADDRESS = "disallowed_address"
    TIMEOUT = "timeout"
    TLS_FAILURE = "tls_failure"
    NETWORK_FAILURE = "network_failure"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    INVALID_REDIRECT = "invalid_redirect"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    BODY_TOO_LARGE = "body_too_large"
    UNSUPPORTED_CHARSET = "unsupported_charset"


class RobotsFetchError(RuntimeError):
    code: RobotsFetchErrorCode

    def __init__(self, code: RobotsFetchErrorCode) -> None:
        self.code = code
        super().__init__(f"Robots fetch failed: {code.value}")


@dataclass(frozen=True, slots=True)
class FetchedRobots:
    requested_site_url: str
    robots_url: str
    final_url: str
    status_code: int
    content_type: str | None
    body: bytes | None
    redirect_chain: tuple[str, ...]


_Address = _transport.Address
_PinnedResolver = _transport.PinnedResolver


def _map_transport_error(error: _transport.TransportError) -> RobotsFetchError:
    return RobotsFetchError(RobotsFetchErrorCode(error.code))


def _normalize_url(raw_url: str, *, redirect: bool = False, base: URL | None = None) -> URL:
    try:
        return _transport.normalize_url(raw_url, redirect=redirect, base=base)
    except _transport.TransportError as exc:
        error = _map_transport_error(exc)
    raise error


def _admit_ip(value: str) -> _Address:
    try:
        return _transport.admit_ip(value)
    except _transport.TransportError as exc:
        error = _map_transport_error(exc)
    raise error


async def _resolve(url: URL) -> tuple[_Address, ...]:
    try:
        return await _transport.resolve(url)
    except _transport.TransportError as exc:
        error = _map_transport_error(exc)
    raise error


async def _request_hop(
    url: URL, addresses: tuple[_Address, ...]
) -> tuple[aiohttp.ClientResponse, aiohttp.ClientSession]:
    return await _transport.request_hop(url, addresses, _HEADERS)


def _content_type(response: aiohttp.ClientResponse) -> str:
    values = response.headers.getall("Content-Type", [])
    if len(values) != 1:
        raise RobotsFetchError(RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE)
    if re.search(r"(?:^|;)\s*charset\s*=\s*(?:;|$)", values[0], re.IGNORECASE):
        raise RobotsFetchError(RobotsFetchErrorCode.UNSUPPORTED_CHARSET)
    if re.search(r"(?:^|;)\s*charset\*", values[0], re.IGNORECASE):
        raise RobotsFetchError(RobotsFetchErrorCode.UNSUPPORTED_CHARSET)
    if _CONTENT_TYPE_PATTERN.fullmatch(values[0]) is None:
        raise RobotsFetchError(RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE)
    message = Message()
    message["Content-Type"] = values[0]
    if message.get_content_type().lower() != "text/plain":
        raise RobotsFetchError(RobotsFetchErrorCode.UNSUPPORTED_CONTENT_TYPE)
    declared = [
        value for name, value in message.get_params(failobj=[])[1:] if name.lower() == "charset"
    ]
    if (
        len(declared) > 1
        or (declared and not isinstance(declared[0], str))
        or (declared and isinstance(declared[0], str) and not declared[0].isascii())
        or (declared and isinstance(declared[0], str) and declared[0].lower() != "utf-8")
    ):
        raise RobotsFetchError(RobotsFetchErrorCode.UNSUPPORTED_CHARSET)
    return "text/plain"


async def _read_body(response: aiohttp.ClientResponse) -> bytes:
    body = bytearray()
    async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
        if len(body) + len(chunk) > _BODY_LIMIT:
            raise RobotsFetchError(RobotsFetchErrorCode.BODY_TOO_LARGE)
        body.extend(chunk)
    return bytes(body)


async def _fetch(site: URL, robots_url: URL) -> FetchedRobots:
    chain: list[str] = []
    redirect_count = 0
    current = robots_url
    while True:
        chain.append(str(current))
        addresses = await _resolve(current)
        response: aiohttp.ClientResponse | None = None
        session: aiohttp.ClientSession | None = None
        try:
            response, session = await _request_hop(current, addresses)
            if response.status in _REDIRECT_STATUSES:
                if redirect_count >= _MAX_REDIRECTS:
                    raise RobotsFetchError(RobotsFetchErrorCode.TOO_MANY_REDIRECTS)
                locations = response.headers.getall("Location", [])
                if len(locations) != 1 or not locations[0].strip():
                    raise RobotsFetchError(RobotsFetchErrorCode.INVALID_REDIRECT)
                current = _normalize_url(locations[0], redirect=True, base=current)
                redirect_count += 1
                continue
            if response.status != 200:
                return FetchedRobots(
                    str(site),
                    str(robots_url),
                    str(current),
                    response.status,
                    None,
                    None,
                    tuple(chain),
                )
            content_type = _content_type(response)
            body = await _read_body(response)
            return FetchedRobots(
                str(site),
                str(robots_url),
                str(current),
                200,
                content_type,
                body,
                tuple(chain),
            )
        finally:
            if response is not None:
                response.close()
            if session is not None:
                await session.close()


async def fetch_robots(*, site_url: str) -> FetchedRobots:
    if not isinstance(site_url, str):
        raise TypeError("site_url must be a string")
    error_code: RobotsFetchErrorCode | None = None
    try:
        site = _normalize_url(site_url)
        robots_url = site.with_path("/robots.txt").with_query(None)
        async with asyncio.timeout(30):
            return await _fetch(site, robots_url)
    except asyncio.CancelledError:
        raise
    except RobotsFetchError:
        raise
    except TimeoutError:
        error_code = RobotsFetchErrorCode.TIMEOUT
    except (
        aiohttp.ClientConnectorCertificateError,
        aiohttp.ClientConnectorSSLError,
        aiohttp.ClientSSLError,
        aiohttp.ServerFingerprintMismatch,
        ssl.SSLError,
    ):
        error_code = RobotsFetchErrorCode.TLS_FAILURE
    except aiohttp.ClientError:
        error_code = RobotsFetchErrorCode.NETWORK_FAILURE
    except (OSError, UnicodeError, ValueError):
        error_code = RobotsFetchErrorCode.NETWORK_FAILURE
    assert error_code is not None
    raise RobotsFetchError(error_code)
