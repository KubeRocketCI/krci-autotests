"""ReportPortal wiring, as an opt-in pytest plugin.

Loader: `scripts/suite.py run`, via `-p krci_testkit.reporting`.

Reporting is secondary evidence: an unreachable RP server must disable reporting,
never gate test execution — with RP enabled but unreachable, pytest-reportportal's
startup hang takes the xdist workers down and the whole run dies before a single
test."""

import logging
import os
import ssl

import httpx
import pytest
from dotenv import load_dotenv
from reportportal_client.helpers import to_bool

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 5.0

_ENV_TO_INI = {
    "RP_ENDPOINT": "rp_endpoint",
    "RP_PROJECT": "rp_project",
    "RP_API_KEY": "rp_api_key",
    "RP_VERIFY_SSL": "rp_verify_ssl",
}


def rp_verify(raw: str | None) -> bool | str:
    """Parse RP_VERIFY_SSL through the plugin's own parser: what to_bool rejects is
    a CA bundle path. Unset means verify."""
    if raw is None or not raw.strip():
        return True
    value = raw.strip()
    try:
        return bool(to_bool(value))
    except ValueError:
        return value


def _is_tls_failure(exc: BaseException) -> bool:
    """The ssl error sits two levels down: httpx wraps httpcore, which wraps ssl."""
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLError):
            return True
        cause = cause.__cause__ or cause.__context__
    return False


def reportportal_reachable(
    endpoint: str,
    *,
    verify: bool | str = True,
    transport: httpx.BaseTransport | None = None,
) -> bool:
    """True when the RP server answers /api/info within the probe timeout.

    ANY HTTP response counts as reachable, auth errors included; only transport-level
    failure counts as down. TLS is verified by default; a self-signed RP needs
    RP_VERIFY_SSL. A rejected certificate and an unusable CA bundle path both return
    False: this runs in pytest_configure, where raising kills the run before any test."""
    url = f"{endpoint.rstrip('/')}/api/info"
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT, verify=verify, transport=transport) as client:
            client.get(url)
    except (httpx.HTTPError, OSError) as exc:
        tls = _is_tls_failure(exc)
        log.warning(
            "ReportPortal %s (%s: %s) — running without reporting%s",
            "certificate rejected" if tls else "unreachable",
            url,
            exc,
            "; set RP_VERIFY_SSL to a CA bundle path or false if the server is self-signed"
            if tls
            else "",
        )
        return False
    return True


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Enable pytest-reportportal from the environment.

    Values go through the ini store: secrets must never reach argv. tryfirst lands
    them before pytest-reportportal reads its config; popping the private-but-stable
    _inicache guards against an earlier cached read.
    """
    load_dotenv(override=False)
    if config.option.collectonly or not os.environ.get("RP_ENDPOINT"):
        return
    if not reportportal_reachable(
        os.environ["RP_ENDPOINT"], verify=rp_verify(os.environ.get("RP_VERIFY_SSL"))
    ):
        return
    config.option.rp_enabled = True  # what --reportportal would have set
    for env_name, ini_name in _ENV_TO_INI.items():
        value = os.environ.get(env_name)
        if value:
            config.inicfg[ini_name] = value
            config._inicache.pop(ini_name, None)
