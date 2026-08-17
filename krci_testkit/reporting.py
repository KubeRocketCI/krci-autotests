"""ReportPortal preflight. Reporting is secondary evidence: an unreachable RP
server must disable reporting, never gate test execution — with RP enabled but
unreachable, pytest-reportportal's startup hang takes the xdist workers down and
the whole run dies before a single test."""

import logging

import httpx

log = logging.getLogger(__name__)

_PROBE_TIMEOUT = 5.0


def reportportal_reachable(endpoint: str, *, transport: httpx.BaseTransport | None = None) -> bool:
    """True when the RP server answers /api/info within the probe timeout.

    ANY HTTP response counts as reachable (auth errors included — the plugin
    will surface those itself); only transport-level failure counts as down.
    TLS is not verified: this is a reachability probe that sends nothing
    sensitive, and a cert problem must not silently disable reporting."""
    url = f"{endpoint.rstrip('/')}/api/info"
    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT, verify=False, transport=transport) as client:
            client.get(url)
    except httpx.HTTPError as exc:
        log.warning("ReportPortal unreachable (%s: %s) — running without reporting", url, exc)
        return False
    return True
