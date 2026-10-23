"""The HTTP client behind HTTP request nodes, guarded against server-side request forgery.

Flows are written by workspace editors, and their URLs are templates filled from run
inputs, so the destination of a request is untrusted. Every connection goes through a
network backend that resolves the host itself and refuses loopback, private, link-local,
shared (CGNAT), multicast, reserved and unspecified addresses (cloud metadata endpoints
included) unless the host is explicitly allowed. The check happens at connect time, on the
address actually dialled, so redirects and DNS rebinding are covered as well. TLS still
verifies the certificate against the original host name.

Requests to the reserved host `sandbox.agentstudio.test` never leave the process: they are
answered by the built-in sandbox API, which is what lets the templates run offline.
"""

from __future__ import annotations

import ipaddress
import socket
import ssl
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import anyio
import certifi
import httpcore
import httpx
from starlette.types import ASGIApp

from agentstudio import __version__
from agentstudio.core import metrics
from agentstudio.engine.errors import NodeError
from agentstudio.engine.ports import HttpResponse

SANDBOX_HOST = "sandbox.agentstudio.test"
USER_AGENT = f"Euron-AgentStudio/{__version__}"
MAX_REDIRECTS = 3
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class BlockedAddressError(Exception):
    def __init__(self, host: str) -> None:
        super().__init__(host)
        self.host = host


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    allowed_hosts: frozenset[str] = frozenset()
    allow_private: bool = False

    @classmethod
    def from_hosts(cls, hosts: Iterable[str], *, allow_private: bool) -> NetworkPolicy:
        return cls(frozenset(host.strip().lower() for host in hosts if host.strip()), allow_private)

    def host_allowed(self, host: str) -> bool:
        name = host.lower().rstrip(".")
        for allowed in self.allowed_hosts:
            if allowed.startswith("*.") and (name.endswith(allowed[1:]) or name == allowed[2:]):
                return True
            if name == allowed:
                return True
        return False

    def allows(self, host: str, address: IPAddress) -> bool:
        if self.allow_private or self.host_allowed(host):
            return True
        return is_public(address)


def is_public(address: IPAddress) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped or address.sixtofour
        if mapped is not None:
            return is_public(mapped)
    return bool(address.is_global) and not address.is_multicast


async def _resolve(host: str, port: int) -> list[IPAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    infos = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    addresses: list[IPAddress] = []
    for info in infos:
        raw = str(info[4][0]).split("%", 1)[0]
        address = ipaddress.ip_address(raw)
        if address not in addresses:
            addresses.append(address)
    return addresses


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Resolves, vets and dials addresses itself, so nothing private is ever connected to."""

    def __init__(
        self, policy: NetworkPolicy, inner: httpcore.AsyncNetworkBackend | None = None
    ) -> None:
        self._policy = policy
        self._inner = inner or httpcore.AnyIOBackend()

    # The parameter names below are httpcore's backend interface, timeout included.
    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        try:
            addresses = await _resolve(host, port)
        except OSError as exc:
            raise httpcore.ConnectError(f"Could not resolve {host}") from exc
        allowed = [address for address in addresses if self._policy.allows(host, address)]
        if not allowed:
            raise BlockedAddressError(host)
        return await self._inner.connect_tcp(
            str(allowed[0]),
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,  # noqa: ASYNC109
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise BlockedAddressError(path)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class GuardedTransport(httpx.AsyncHTTPTransport):
    def __init__(self, policy: NetworkPolicy) -> None:
        super().__init__(trust_env=False)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(cafile=certifi.where()),
            max_connections=50,
            max_keepalive_connections=10,
            keepalive_expiry=30.0,
            network_backend=GuardedBackend(policy),
        )


class GuardedHttpClient:
    """Implements the engine's `HttpClient` port."""

    def __init__(
        self,
        policy: NetworkPolicy,
        *,
        sandbox: ASGIApp | None = None,
        max_response_bytes: int = 1024 * 1024,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        mounts: dict[str, httpx.AsyncBaseTransport] = {}
        if sandbox is not None:
            mounts[f"all://{SANDBOX_HOST}"] = httpx.ASGITransport(app=sandbox)
        self._client = httpx.AsyncClient(
            transport=transport or GuardedTransport(policy),
            mounts=mounts,
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            headers={"user-agent": USER_AGENT},
            trust_env=False,
        )
        self._max_bytes = max_response_bytes

    async def send(self, spec: dict[str, Any], *, timeout_s: float) -> HttpResponse:
        url = str(spec.get("url", ""))
        if not url.lower().startswith(("http://", "https://")):
            raise NodeError("invalid_url", "The URL must start with http:// or https://.")
        try:
            request = self._client.build_request(
                spec.get("method", "GET"),
                url,
                headers=spec.get("headers") or None,
                params=spec.get("params") or None,
                json=spec.get("json"),
                content=spec.get("content"),
                timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            )
        except (httpx.InvalidURL, ValueError, TypeError) as exc:
            raise NodeError("invalid_url", f"The request could not be built: {exc}") from exc
        try:
            response = await self._client.send(request, stream=True)
            try:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise NodeError(
                            "response_too_large",
                            f"The response is larger than {self._max_bytes // 1024} KB.",
                        )
            finally:
                await response.aclose()
        except BlockedAddressError as exc:
            metrics.HTTP_TOOL_REQUESTS.labels("blocked").inc()
            raise NodeError(
                "blocked_address",
                f"Requests to {exc.host} are not allowed: it resolves to a private or internal "
                "address. An operator can allow it with HTTP_ALLOWED_HOSTS.",
            ) from exc
        except httpx.TimeoutException as exc:
            metrics.HTTP_TOOL_REQUESTS.labels("error").inc()
            raise NodeError("http_timeout", "The request timed out.", retryable=True) from exc
        except httpx.TooManyRedirects as exc:
            metrics.HTTP_TOOL_REQUESTS.labels("error").inc()
            raise NodeError(
                "too_many_redirects", "The request was redirected too many times."
            ) from exc
        except httpx.HTTPError as exc:
            metrics.HTTP_TOOL_REQUESTS.labels("error").inc()
            raise NodeError(
                "http_unreachable", f"The server could not be reached: {exc}", retryable=True
            ) from exc
        metrics.HTTP_TOOL_REQUESTS.labels(
            "ok" if response.status_code < 400 else "http_error"
        ).inc()
        encoding = response.encoding or "utf-8"
        return HttpResponse(
            status=response.status_code,
            text=bytes(body).decode(encoding, errors="replace"),
            content_type=response.headers.get("content-type", ""),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
