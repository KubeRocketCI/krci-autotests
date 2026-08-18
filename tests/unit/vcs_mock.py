"""Shared mock-transport test double for the provider-client unit tests.

Lives in tests/unit (not conftest) so the three client test modules import it
explicitly; the local httpx imports keep the module import clean for the
import-linter contract (the sole sanctioned tests->httpx seam)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx


class Recorder:
    """Collects requests and plays scripted responses keyed by (method, path).

    Keys use DECODED paths (httpx normalizes %2F in url.path). A scripted response
    is (status, body) or (status, body, headers) — the optional third element lets
    a test script pagination signals (Link, X-Next-Page, ...)."""

    def __init__(
        self,
        responses: dict[tuple[str, str], list[tuple[int, Any] | tuple[int, Any, dict[str, str]]]],
    ):
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        import httpx  # local: unit-test seam, keeps module import clean

        self.requests.append(request)
        key = (request.method, request.url.path)
        status, body, *extra = self.responses[key].pop(0)
        headers = extra[0] if extra else None
        return httpx.Response(status, json=body, headers=headers)

    @property
    def transport(self):
        import httpx

        return httpx.MockTransport(self.handler)


def raw_transport(content: bytes, *, expect_path: str):
    """Transport serving one raw (non-JSON) body — the double for tarball fetches.
    expect_path pins the endpoint so a wrong URL fails the test, not the decode."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expect_path
        return httpx.Response(200, content=content)

    return httpx.MockTransport(handler)


def failing_transport(message: str = "connection refused"):
    """Transport whose every request fails at the socket level — the double for
    'server is down' paths (e.g. the ReportPortal reachability probe)."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(message)

    return httpx.MockTransport(handler)
