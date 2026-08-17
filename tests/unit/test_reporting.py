"""reportportal_reachable: reporting must degrade, never gate test execution."""

from krci_testkit.reporting import reportportal_reachable
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
