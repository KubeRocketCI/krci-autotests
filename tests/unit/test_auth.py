"""Unit tests for portal-token verification (mock transport, no network).

The point of portal_token_identity is that bootstrap fails on a DEAD token instead
of reporting OK and letting every UI test fail later, so these tests pin exactly
that: a live token yields its identity, a rejected one raises with a named reason.
"""

import httpx
import pytest
from pydantic import SecretStr

from krci_testkit.auth import portal_token, portal_token_identity, portal_url
from krci_testkit.config import KrciConfig

_API = "https://api.test:6443"


def _cfg(token: str | None) -> KrciConfig:
    return KrciConfig(
        portal_url="https://portal.test",
        portal_token=SecretStr(token) if token else None,
        git_server="gitlab",
        git_group="grp",
        namespace="krci",
    )


def _transport(status: int, body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _request: httpx.Response(status, json=body))


def test_identity_is_read_from_the_api_servers_verdict() -> None:
    """A live token returns the username the API SERVER reports, not anything the
    caller supplied — that is what makes it evidence the token still works."""
    transport = _transport(201, {"status": {"userInfo": {"username": "system:sa:krci:admin"}}})
    identity = portal_token_identity(_cfg("live"), _API, verify=False, transport=transport)
    assert identity == "system:sa:krci:admin"


def test_rejected_token_fails_with_a_named_reason() -> None:
    """Old bug: bootstrap only checked the env var was non-empty and then probed the
    portal UNAUTHENTICATED, so an expired token passed bootstrap and surfaced as a
    confusing Playwright failure deep in the UI suite."""
    transport = _transport(401, {"message": "Unauthorized"})
    with pytest.raises(ValueError, match="rejected by the API server"):
        portal_token_identity(_cfg("stale"), _API, verify=False, transport=transport)


def test_missing_token_is_reported_by_its_env_var_name() -> None:
    with pytest.raises(ValueError, match="KRCI_PORTAL_TOKEN"):
        portal_token(_cfg(None))


def test_missing_portal_url_is_reported_by_its_env_var_name() -> None:
    """Portal facts are optional config so an API-only run needs none; a UI test
    that reaches for an unset one must name the variable rather than navigate to None."""
    # portal_url is passed explicitly: init values outrank the .env file, which on a
    # configured checkout would otherwise supply the very value under test.
    cfg = KrciConfig(portal_url=None, git_server="gitlab", git_group="grp", namespace="krci")
    with pytest.raises(ValueError, match="KRCI_PORTAL_URL"):
        portal_url(cfg)


def test_the_token_is_sent_as_a_bearer_credential() -> None:
    """The API server only accepts the token as a bearer header; sending it any
    other way would make every verdict a false negative."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"status": {"userInfo": {"username": "u"}}})

    portal_token_identity(_cfg("tok"), _API, verify=False, transport=httpx.MockTransport(handler))
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert seen[0].url.path == "/apis/authentication.k8s.io/v1/selfsubjectreviews"
