"""Portal authentication: ServiceAccount-token only (no Keycloak flow).

The portal's token login is the supported strategy for all target environments;
a different strategy would be a new module behind this same function, added only
when an environment actually requires it.

The accessors are also the single gate on the UI-only config: portal facts are
optional in KrciConfig so an API-only run needs no portal at all, and a UI test
that reaches for a missing one fails here by name instead of on a `None` URL."""

import httpx

from krci_testkit.config import KrciConfig

_REQUEST_TIMEOUT = 30.0


def portal_url(cfg: KrciConfig) -> str:
    if not cfg.portal_url:
        raise ValueError("KRCI_PORTAL_URL is required to run UI tests")
    return cfg.portal_url


def portal_token(cfg: KrciConfig) -> str:
    if not cfg.portal_token:
        raise ValueError("KRCI_PORTAL_TOKEN is required to run UI tests")
    return cfg.portal_token.get_secret_value()


def portal_token_identity(
    cfg: KrciConfig,
    api_server: str,
    *,
    verify: bool | str,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """The username the portal token authenticates as, proving the token is live.

    The portal signs the browser in by forwarding this ServiceAccount token to the
    API server, so a SelfSubjectReview there is the same acceptance test the login
    dialog performs — and the only one that can tell a valid token from an expired
    one. Checking that the token env var is merely non-empty, or that the portal
    URL answers unauthenticated, passes for a token that every UI test will reject.
    """
    with httpx.Client(verify=verify, timeout=_REQUEST_TIMEOUT, transport=transport) as client:
        resp = client.post(
            f"{api_server.rstrip('/')}/apis/authentication.k8s.io/v1/selfsubjectreviews",
            headers={"Authorization": f"Bearer {portal_token(cfg)}"},
            json={"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview"},
        )
    if resp.status_code == httpx.codes.UNAUTHORIZED:
        raise ValueError("KRCI_PORTAL_TOKEN was rejected by the API server (expired or invalid)")
    resp.raise_for_status()
    return str(resp.json()["status"]["userInfo"]["username"])
