"""Unit tests for the two guards that stop a run from silently testing the wrong
thing: the label-selector safety check in Cluster.list, and the codebase-name
claim that catches two scenarios sharing a unique_name prefix.

Both failure modes are false GREENS — a suite that reports success while asserting
against another test's resources — which is the one outcome a test framework must
never produce quietly.
"""

import pytest

from krci_testkit.clusters import Cluster
from krci_testkit.models import PipelineRun
from tests.conftest import _claim


def _cluster() -> Cluster:
    """A Cluster that was never connected. Cluster.__init__ needs a live API
    server, and the selector guard runs before any request, so the guard is
    reachable — and only reachable — without one."""
    return object.__new__(Cluster)


def test_list_rejects_a_label_value_that_would_change_the_selector() -> None:
    """A ',' in a value silently turns one selector term into two, matching a
    WIDER set than asked for. That returns runs belonging to other tests and the
    assertion passes on them — so it must raise instead."""
    with pytest.raises(AssertionError, match="silently change the selector"):
        _cluster().list(PipelineRun, labels={"app.edp.epam.com/codebase": "a,b"})


def test_list_rejects_an_equals_sign_in_a_label_value() -> None:
    with pytest.raises(AssertionError, match="silently change the selector"):
        _cluster().list(PipelineRun, labels={"app.edp.epam.com/codebase": "a=b"})


def test_list_accepts_the_dns1123_vocabulary_the_suite_actually_uses() -> None:
    """The guard must not reject legitimate values; getting past it means reaching
    the (absent) API client, which is a different error entirely."""
    with pytest.raises(AttributeError):
        _cluster().list(PipelineRun, labels={"app.edp.epam.com/codebase": "at-csl-0bf329gw0"})


def test_two_scenarios_sharing_a_prefix_are_named_as_the_collision() -> None:
    """unique_name(prefix) is stable per prefix in a process, so two scenarios with
    the same prefix would silently share ONE codebase and corrupt each other."""
    claimed: dict[str, str] = {}
    _claim(claimed, "at-dup-abc123", "tests/api/a.py::test_one")
    with pytest.raises(ValueError, match="already created in this session"):
        _claim(claimed, "at-dup-abc123", "tests/api/b.py::test_two")


def test_a_rerun_of_the_same_test_may_reclaim_its_own_name() -> None:
    """Old bug: the claim was keyed by name alone, so pytest-rerunfailures turned
    a retryable flake into a hard 'already created' error — the rerun could never
    run, and the collision message hid the original failure."""
    claimed: dict[str, str] = {}
    _claim(claimed, "at-rer-abc123", "tests/api/a.py::test_one")
    _claim(claimed, "at-rer-abc123", "tests/api/a.py::test_one")
    assert claimed == {"at-rer-abc123": "tests/api/a.py::test_one"}
