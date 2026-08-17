from __future__ import annotations

import asyncio
import codecs
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from email.message import Message
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

if TYPE_CHECKING:
    from aiohttp.abc import ResolveResult

_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}
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


@dataclass(frozen=True, slots=True)
class _Address:
    value: str
    family: socket.AddressFamily


class _PinnedResolver(AbstractResolver):
    def __init__(self, addresses: tuple[_Address, ...]) -> None:
        self._addresses = addresses

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        del family
        return [
            {
                "hostname": host,
                "host": address.value,
                "port": port,
                "family": address.family,
                "proto": socket.IPPROTO_TCP,
                "flags": 0,
            }
            for address in self._addresses
        ]

    async def close(self) -> None:
        return None


def _raw_authority(raw_url: str) -> str | None:
    if raw_url.startswith("//"):
        authority_start = 2
    else:
        scheme_separator = raw_url.find("://")
        if scheme_separator < 0:
            return None
        authority_start = scheme_separator + 3
    authority_end = len(raw_url)
    for separator in "/?#":
        position = raw_url.find(separator, authority_start)
        if position >= 0:
            authority_end = min(authority_end, position)
    return raw_url[authority_start:authority_end]


def _raw_explicit_port(authority: str) -> str | None:
    host_port = authority.rsplit("@", 1)[-1]
    if host_port.startswith("["):
        closing = host_port.find("]")
        if closing >= 0 and host_port[closing + 1 :].startswith(":"):
            return host_port[closing + 2 :]
        return None
    if ":" not in host_port:
        return None
    return host_port.rsplit(":", 1)[1]


def _is_dns_hostname(host: str) -> bool:
    hostname = host.removesuffix(".")
    if not hostname or len(hostname) > 253:
        return False
    for label in hostname.split("."):
        if (
            not label
            or len(label) > 63
            or not label.isascii()
            or not label[0].isalnum()
            or not label[-1].isalnum()
            or any(not (character.isalnum() or character == "-") for character in label)
        ):
            return False
    return True


def _normalize_url(raw_url: str, *, redirect: bool = False, base: URL | None = None) -> URL:
    error_code = HtmlFetchErrorCode.INVALID_REDIRECT if redirect else HtmlFetchErrorCode.INVALID_URL
    try:
        authority = _raw_authority(raw_url)
        raw_port = _raw_explicit_port(authority) if authority is not None else None
        if raw_port is not None:
            normalized_port = raw_port.lstrip("0") or "0"
            if (
                not raw_port.isascii()
                or not raw_port.isdecimal()
                or len(normalized_port) > 5
                or int(normalized_port) > 65535
            ):
                raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_PORT)
        parsed = URL(raw_url)
        if base is not None:
            parsed = base.join(parsed)
        scheme = parsed.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES or not parsed.is_absolute() or parsed.host is None:
            raise HtmlFetchError(error_code)
        if (
            (authority is not None and "@" in authority)
            or parsed.user is not None
            or parsed.password is not None
        ):
            raise HtmlFetchError(error_code)
        parsed = parsed.with_host(parsed.host)
        normalized_host = parsed.host
        if normalized_host is None:
            raise HtmlFetchError(error_code)
        try:
            ipaddress.ip_address(normalized_host)
        except ValueError:
            if parsed.raw_host is None or not _is_dns_hostname(parsed.raw_host):
                raise HtmlFetchError(error_code) from None
        try:
            explicit_port = parsed.explicit_port
        except ValueError as exc:
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_PORT) from exc
        if explicit_port is not None and explicit_port != _DEFAULT_PORTS[scheme]:
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_PORT)
        if explicit_port is not None:
            parsed = parsed.with_port(None)
        return parsed.with_fragment(None)
    except HtmlFetchError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise HtmlFetchError(error_code) from exc


def _admit_ip(value: str) -> _Address:
    if "%" in value:
        raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS) from exc
    mapped = address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else None
    if (
        not address.is_global
        or address.is_link_local
        or address.is_loopback
        or address.is_multicast
        or address.is_private
        or address.is_reserved
        or address.is_unspecified
        or (mapped is not None and not mapped.is_global)
    ):
        raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    return _Address(str(address), family)


async def _resolve(url: URL) -> tuple[_Address, ...]:
    host = url.host
    if host is None:
        raise HtmlFetchError(HtmlFetchErrorCode.INVALID_URL)
    try:
        return (_admit_ip(host),)
    except HtmlFetchError as exc:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise exc

    loop = asyncio.get_running_loop()
    try:
        answers = await loop.getaddrinfo(
            host,
            url.port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except asyncio.CancelledError:
        raise
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        raise HtmlFetchError(HtmlFetchErrorCode.DNS_FAILURE) from exc
    if not answers:
        raise HtmlFetchError(HtmlFetchErrorCode.DNS_FAILURE)

    admitted: list[_Address] = []
    seen: set[tuple[str, socket.AddressFamily]] = set()
    for answer in answers:
        if not isinstance(answer, tuple) or len(answer) != 5:
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
        family, socktype, proto, _canonname, sockaddr = answer
        if (
            family not in (socket.AF_INET, socket.AF_INET6)
            or socktype != socket.SOCK_STREAM
            or proto not in (0, socket.IPPROTO_TCP)
        ):
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
        if not isinstance(sockaddr, tuple):
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
        if family == socket.AF_INET:
            valid_sockaddr = (
                len(sockaddr) == 2
                and isinstance(sockaddr[0], str)
                and type(sockaddr[1]) is int
                and sockaddr[1] == url.port
            )
        else:
            valid_sockaddr = (
                len(sockaddr) == 4
                and isinstance(sockaddr[0], str)
                and type(sockaddr[1]) is int
                and sockaddr[1] == url.port
                and type(sockaddr[2]) is int
                and type(sockaddr[3]) is int
                and sockaddr[3] == 0
            )
        if not valid_sockaddr:
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
        admitted_address = _admit_ip(sockaddr[0])
        if admitted_address.family != family:
            raise HtmlFetchError(HtmlFetchErrorCode.DISALLOWED_ADDRESS)
        key = (admitted_address.value, admitted_address.family)
        if key not in seen:
            seen.add(key)
            admitted.append(admitted_address)
    return tuple(admitted)


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
    connector = aiohttp.TCPConnector(
        resolver=_PinnedResolver(addresses),
        use_dns_cache=False,
    )
    try:
        session = aiohttp.ClientSession(
            connector=connector,
            connector_owner=True,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=None, connect=5, sock_connect=5, sock_read=10),
            auto_decompress=True,
        )
    except BaseException:
        await connector.close()
        raise
    try:
        response = await session.get(url, allow_redirects=False)
    except BaseException:
        await session.close()
        raise
    return response, session


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
