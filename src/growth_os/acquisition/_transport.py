from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

if TYPE_CHECKING:
    from aiohttp.abc import ResolveResult

_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
_DEFAULT_PORTS: Final = {"http": 80, "https": 443}


class TransportError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Address:
    value: str
    family: socket.AddressFamily


class PinnedResolver(AbstractResolver):
    def __init__(self, addresses: tuple[Address, ...]) -> None:
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
    return all(
        label
        and len(label) <= 63
        and label.isascii()
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in hostname.split(".")
    )


def normalize_url(raw_url: str, *, redirect: bool = False, base: URL | None = None) -> URL:
    error_code = "invalid_redirect" if redirect else "invalid_url"
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
                raise TransportError("disallowed_port")
        parsed = URL(raw_url)
        if base is not None:
            parsed = base.join(parsed)
        scheme = parsed.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES or not parsed.is_absolute() or parsed.host is None:
            raise TransportError(error_code)
        if (
            (authority is not None and "@" in authority)
            or parsed.user is not None
            or parsed.password is not None
        ):
            raise TransportError(error_code)
        parsed = parsed.with_host(parsed.host)
        normalized_host = parsed.host
        if normalized_host is None:
            raise TransportError(error_code)
        try:
            ipaddress.ip_address(normalized_host)
        except ValueError:
            if parsed.raw_host is None or not _is_dns_hostname(parsed.raw_host):
                raise TransportError(error_code) from None
        try:
            explicit_port = parsed.explicit_port
        except ValueError as exc:
            raise TransportError("disallowed_port") from exc
        if explicit_port is not None and explicit_port != _DEFAULT_PORTS[scheme]:
            raise TransportError("disallowed_port")
        if explicit_port is not None:
            parsed = parsed.with_port(None)
        return parsed.with_fragment(None)
    except TransportError:
        raise
    except (TypeError, ValueError, UnicodeError) as exc:
        raise TransportError(error_code) from exc


def admit_ip(value: str) -> Address:
    if "%" in value:
        raise TransportError("disallowed_address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise TransportError("disallowed_address") from exc
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
        raise TransportError("disallowed_address")
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    return Address(str(address), family)


async def resolve(url: URL) -> tuple[Address, ...]:
    host = url.host
    if host is None:
        raise TransportError("invalid_url")
    try:
        return (admit_ip(host),)
    except TransportError as exc:
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise exc

    try:
        answers = await asyncio.get_running_loop().getaddrinfo(
            host, url.port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
        )
    except asyncio.CancelledError:
        raise
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        raise TransportError("dns_failure") from exc
    if not answers:
        raise TransportError("dns_failure")

    admitted: list[Address] = []
    seen: set[tuple[str, socket.AddressFamily]] = set()
    for answer in answers:
        if not isinstance(answer, tuple) or len(answer) != 5:
            raise TransportError("disallowed_address")
        family, socktype, proto, _canonname, sockaddr = answer
        if (
            family not in (socket.AF_INET, socket.AF_INET6)
            or socktype != socket.SOCK_STREAM
            or proto not in (0, socket.IPPROTO_TCP)
            or not isinstance(sockaddr, tuple)
        ):
            raise TransportError("disallowed_address")
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
            raise TransportError("disallowed_address")
        admitted_address = admit_ip(sockaddr[0])
        if admitted_address.family != family:
            raise TransportError("disallowed_address")
        key = (admitted_address.value, admitted_address.family)
        if key not in seen:
            seen.add(key)
            admitted.append(admitted_address)
    return tuple(admitted)


async def request_hop(
    url: URL, addresses: tuple[Address, ...], headers: dict[str, str]
) -> tuple[aiohttp.ClientResponse, aiohttp.ClientSession]:
    connector = aiohttp.TCPConnector(resolver=PinnedResolver(addresses), use_dns_cache=False)
    try:
        session = aiohttp.ClientSession(
            connector=connector,
            connector_owner=True,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            headers=headers,
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
