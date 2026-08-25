"""reportportal_reachable: reporting must degrade, never gate test execution."""

import pytest

from krci_testkit.reporting import reportportal_reachable, rp_verify
from tests.unit.vcs_mock import Recorder, failing_transport


def test_answering_server_is_reachable():
    recorder = Recorder({("GET", "/api/info"): [(200, {"build": {"version": "5"}})]})
    assert reportportal_reachable("https://rp.example.com", transport=recorder.transport)


def test_http_error_still_counts_as_reachable():
    recorder = Recorder({("GET", "/api/info"): [(401, {"error": "unauthorized"})]})
    assert reportportal_reachable("https://rp.example.com", transport=recorder.transport)


def test_connect_failure_is_unreachable():
    assert not reportportal_reachable("https://rp.example.com", transport=failing_transport())


def test_trailing_slash_normalized():
    recorder = Recorder({("GET", "/api/info"): [(200, {})]})
    assert reportportal_reachable("https://rp.example.com/", transport=recorder.transport)
    (request,) = recorder.requests
    assert request.url.path == "/api/info"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),
        ("", True),
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("Y", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("n", False),
        ("/etc/ssl/certs/rp-ca.pem", "/etc/ssl/certs/rp-ca.pem"),
    ],
)
def test_rp_verify_matches_plugin_parsing(raw: str | None, expected: bool | str):
    assert rp_verify(raw) == expected


def test_unusable_ca_bundle_is_unreachable():
    assert not reportportal_reachable("https://rp.example.com", verify="/no/such/ca.pem")
