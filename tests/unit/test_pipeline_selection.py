"""Unit tests for platform-run selection: success wins, duplicate-webhook runs
that fail fast are tolerated while anything is still pending, total failure raises."""

import pytest

from krci_testkit.models import PipelineRun, name_of
from krci_testkit.waits import FailFast, Timeouts
from tests.utils.pipelinerun_utils import PipelineRuns, _any_succeeded


def _run(
    name: str, status: str | None, reason: str = "", start_time: str | None = None
) -> PipelineRun:
    conditions = (
        [{"type": "Succeeded", "status": status, "reason": reason, "message": reason}]
        if status is not None
        else []
    )
    manifest = {
        "apiVersion": "tekton.dev/v1",
        "kind": "PipelineRun",
        "metadata": {"name": name},
        "status": {"conditions": conditions},
    }
    if start_time:
        manifest["status"]["startTime"] = start_time
    return PipelineRun.model_validate(manifest)


def test_success_among_failed_duplicates_wins():
    assert _any_succeeded([_run("dup", "False", "Failed"), _run("real", "True")])


def test_pending_run_keeps_polling_despite_failed_duplicate():
    assert not _any_succeeded([_run("dup", "False", "Failed"), _run("real", "Unknown")])


def test_no_runs_yet_keeps_polling():
    assert not _any_succeeded([])


def test_all_terminal_failures_raise():
    with pytest.raises(FailFast, match="dup"):
        _any_succeeded([_run("dup", "False", "Failed"), _run("other", "False", "Failed")])


class _FakeCluster:
    """Minimal Cluster double: wait_success_for only ever calls .list on it."""

    def __init__(self, runs: list[PipelineRun]):
        self._runs = runs

    def list(
        self,
        _model: type[PipelineRun],
        *,
        labels: dict[str, str],  # noqa: ARG002
    ) -> list[PipelineRun]:
        return self._runs


def test_wait_success_for_returns_the_newest_succeeded_run_not_list_order():
    """Old bug: among several green runs (e.g. a duplicate webhook delivery) the
    FIRST one the API happened to return won, even though list order is not
    chronological — the run under test would be a coin flip. The newest run is
    listed LAST here on purpose: with it first, the old first-match code would
    return it too and the test would pass against the bug it exists to pin."""
    newer = _run("newer", "True", start_time="2026-08-16T10:05:00Z")
    older = _run("older", "True", start_time="2026-08-16T10:00:00Z")
    runs = PipelineRuns(
        cluster=_FakeCluster([older, newer]),  # pyright: ignore[reportArgumentType]
        timeouts=Timeouts(),
    )
    winner = runs.wait_success_for({}, since=frozenset(), timeout=1, describe_what="build")
    assert name_of(winner) == "newer"
