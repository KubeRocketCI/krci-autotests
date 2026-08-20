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
        self.requests.append(request)
        key = (request.method, request.url.path)
        status, body, *extra = self.responses[key].pop(0)
        return self._response(status, body, extra[0] if extra else None)

    def _response(self, status: int, body: Any, headers: dict[str, str] | None) -> httpx.Response:
        import httpx  # local: unit-test seam, keeps module import clean

        return httpx.Response(status, json=body, headers=headers)

    @property
    def transport(self):
        import httpx

        return httpx.MockTransport(self.handler)


class GerritRecorder(Recorder):
    """Recorder whose bodies carry Gerrit's XSSI guard.

    Gerrit prefixes every JSON response with `)]}'`, which is not valid JSON.
    Serving plain JSON here would let a client that never strips it pass its
    tests and then fail against a real server, so the double reproduces the
    prefix. A scripted body of None is served with no body at all, which is what
    Gerrit answers to a change edit or a project delete."""

    def _response(self, status: int, body: Any, headers: dict[str, str] | None) -> httpx.Response:
        import json

        import httpx

        if body is None:
            return httpx.Response(status, headers=headers)
        guarded = b")]}'\n" + json.dumps(body).encode()
        return httpx.Response(status, content=guarded, headers=headers)


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
