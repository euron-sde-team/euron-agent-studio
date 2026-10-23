import ipaddress

import httpx
import pytest

from agentstudio.engine.errors import NodeError
from agentstudio.integrations.http import (
    SANDBOX_HOST,
    BlockedAddressError,
    GuardedBackend,
    GuardedHttpClient,
    NetworkPolicy,
    is_public,
)
from agentstudio.integrations.sandbox import create_sandbox_app


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "172.16.4.1",
        "192.168.1.20",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 (an address under test, not a bind)
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "2002:7f00:1::",
    ],
)
def test_internal_addresses_are_refused(address: str) -> None:
    assert not is_public(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address: str) -> None:
    assert is_public(ipaddress.ip_address(address))


def test_operators_can_allow_hosts_and_wildcards() -> None:
    policy = NetworkPolicy.from_hosts(["crm.internal", "*.corp.example"], allow_private=False)
    loopback = ipaddress.ip_address("10.1.2.3")
    assert policy.allows("crm.internal", loopback)
    assert policy.allows("api.corp.example", loopback)
    assert policy.allows("corp.example", loopback)
    assert not policy.allows("evilcorp.example", loopback)
    assert NetworkPolicy(allow_private=True).allows("anything", loopback)


async def test_the_backend_refuses_to_dial_private_addresses() -> None:
    backend = GuardedBackend(NetworkPolicy())
    with pytest.raises(BlockedAddressError):
        await backend.connect_tcp("127.0.0.1", 80)
    with pytest.raises(BlockedAddressError):
        await backend.connect_unix_socket("/var/run/docker.sock")


async def test_requests_to_internal_hosts_fail_with_a_clear_error() -> None:
    client = GuardedHttpClient(NetworkPolicy())
    for url in (
        "http://127.0.0.1:9/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:9/",
    ):
        with pytest.raises(NodeError) as error:
            await client.send({"method": "GET", "url": url}, timeout_s=2)
        assert error.value.code == "blocked_address"
        assert not error.value.retryable
    await client.aclose()


async def test_only_http_and_https_urls_are_sent() -> None:
    client = GuardedHttpClient(NetworkPolicy())
    for url in ("file:///etc/passwd", "gopher://x", "ftp://example.com", ""):
        with pytest.raises(NodeError) as error:
            await client.send({"url": url}, timeout_s=1)
        assert error.value.code == "invalid_url"
    await client.aclose()


async def test_sandbox_requests_never_leave_the_process() -> None:
    client = GuardedHttpClient(NetworkPolicy(), sandbox=create_sandbox_app())
    response = await client.send(
        {
            "method": "GET",
            "url": f"https://{SANDBOX_HOST}/crm/contacts",
            "params": {"email": "dana.whitfield@globex.example"},
        },
        timeout_s=5,
    )
    await client.aclose()
    assert response.status == 200
    assert '"plan":"enterprise"' in response.text.replace(" ", "")
    assert response.content_type.startswith("application/json")


async def test_responses_are_capped() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 5000))
    client = GuardedHttpClient(NetworkPolicy(), max_response_bytes=1000, transport=transport)
    with pytest.raises(NodeError) as error:
        await client.send({"url": "https://big.example.com/"}, timeout_s=5)
    assert error.value.code == "response_too_large"
    await client.aclose()


async def test_timeouts_and_connection_errors_are_retryable() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler, code in ((slow, "http_timeout"), (down, "http_unreachable")):
        client = GuardedHttpClient(NetworkPolicy(), transport=httpx.MockTransport(handler))
        with pytest.raises(NodeError) as error:
            await client.send({"url": "https://api.example.com/"}, timeout_s=5)
        assert error.value.code == code
        assert error.value.retryable
        await client.aclose()
