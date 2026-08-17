from types import SimpleNamespace

import pytest

from krci_testkit.errors import NotFound
from krci_testkit.models import Codebase, CodebaseBranch
from krci_testkit.waits import (
    FailFast,
    Timeouts,
    WaitTimeout,
    branch_ready,
    reconciled,
    timeout_knobs,
    wait_for,
    wait_gone,
)


def _branch(**status: str) -> CodebaseBranch:
    return CodebaseBranch.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "CodebaseBranch",
            "metadata": {"name": "at-helm-x-at-rel-1"},
            "spec": {
                "codebaseName": "at-helm-x",
                "branchName": "at-rel-1",
                "fromCommit": "",
                "release": True,
            },
            "status": {
                "action": "ci_configuration",
                "failureCount": 0,
                "lastTimeUpdated": "2026-08-15T10:00:00Z",
                "username": "system",
                "value": "active",
                **status,
            },
        }
    )


def test_branch_is_ready_once_the_operator_pushed_the_git_branch():
    assert branch_ready(_branch(result="success", status="created", git="branch-created"))


def test_branch_is_not_ready_while_the_git_branch_is_still_missing():
    """status.result turns success on every intermediate reconcile. Accepting it
    alone returned on the first poll, and the caller then asked the VCS to branch
    off a ref the operator had not pushed — a 400 from the provider instead of a
    wait that does its job."""
    assert not branch_ready(_branch(result="success", status="initialized", git="initialized"))


def test_branch_with_no_status_is_not_ready():
    assert not branch_ready(SimpleNamespace(status=None))


def test_every_timeout_field_is_a_registered_knob():
    """The knob list drives both pytest's addini calls and the Timeouts fixture:
    a field missing from it would silently ignore its `-o` override."""
    assert {k.name for k in timeout_knobs()} == set(Timeouts().__dataclass_fields__)


def test_knob_ini_names_are_stable():
    """Ini names are the public `-o` surface (README, CI PYTEST_ADDOPTS): they are
    derived, but a rename must be a deliberate edit, not a field rename side effect."""
    assert {k.ini for k in timeout_knobs()} == {
        "krci_timeout_codebase_ready",
        "krci_timeout_build_success",
        "krci_timeout_codebase_delete",
        "krci_timeout_run_trigger",
        "krci_timeout_change_merge",
        "krci_timeout_deploy_success",
        "krci_timeout_vcs_request",
        "krci_poll_interval",
        "krci_timeout_ui_expect",
    }


def test_knob_defaults_match_the_dataclass():
    defaults = Timeouts()
    assert all(getattr(defaults, k.name) == k.default for k in timeout_knobs())


def test_timeouts_defaults_include_trigger_and_merge():
    t = Timeouts()
    assert t.run_trigger == 300
    assert t.change_merge == 180


def test_timeouts_defaults_include_deploy():
    assert Timeouts().deploy_success == 900


def test_returns_when_predicate_true():
    calls = []

    def fetch():
        calls.append(1)
        return len(calls)

    assert wait_for(fetch, lambda n: n >= 3, timeout=10, interval=0) == 3


def test_timeout_includes_last_seen_state():
    with pytest.raises(WaitTimeout) as err:
        wait_for(
            lambda: {"status": "pending"},
            lambda _: False,
            timeout=0.2,
            interval=0.05,
            describe="thing becomes ready",
        )
    assert "thing becomes ready" in str(err.value)
    assert "pending" in str(err.value)  # last-seen state dumped into the failure


def _errored_codebase(failure_count: int = 7) -> Codebase:
    return Codebase.model_validate(
        {
            "apiVersion": "v2.edp.epam.com/v1",
            "kind": "Codebase",
            "metadata": {"name": "at-helm-x"},
            "spec": {
                "type": "library",
                "strategy": "create",
                "lang": "helm",
                "framework": "pipeline",
                "buildTool": "helm",
                "defaultBranch": "main",
                "gitServer": "gitlab",
                "gitUrlPath": "/grp/at-helm-x",
                "ciTool": "tekton",
                "versioning": {"type": "default"},
                "emptyProject": False,
                "deploymentScript": "helm-chart",
            },
            "status": {
                "action": "put_project",
                "available": False,
                "failureCount": failure_count,
                "git": "failed",
                "lastTimeUpdated": "2026-08-15T10:00:00Z",
                "result": "error",
                "status": "failed",
                "username": "ci",
                "value": "failed",
                "detailedMessage": "failed to create project: group quota exceeded",
            },
        }
    )


def test_timeout_dumps_state_of_a_model_carrying_enums():
    """The last-seen-state dump is the suite's primary failure diagnostic, and it
    runs only when something is already wrong — so it must survive the CR shapes it
    exists to report. Every KRCI CR has Enum fields (Codebase.spec.ciTool,
    status.result), which a plain model_dump leaves as Python objects that
    yaml.safe_dump cannot represent: the dump would raise instead of reporting."""
    with pytest.raises(WaitTimeout) as err:
        wait_for(
            _errored_codebase,
            lambda _: False,
            timeout=0.2,
            interval=0.05,
            describe="codebase at-helm-x available",
        )
    message = str(err.value)
    assert "result: error" in message  # enum rendered as its value, not repr
    assert "group quota exceeded" in message  # the operator's own explanation
    assert "ciTool: tekton" in message


def test_timeout_dumps_state_when_fetch_returns_a_list_of_models():
    """Old bug: _dumpable passed a LIST of pydantic models straight to
    yaml.safe_dump, which raised yaml.representer.RepresenterError instead of
    reporting the timeout — exactly the shape the pipeline-run waits fetch (a list
    of PipelineRun models), so a timed-out pipeline wait died with an opaque
    RepresenterError instead of ever reporting the last-seen state."""
    runs = [_errored_codebase(failure_count=1), _errored_codebase(failure_count=2)]
    with pytest.raises(WaitTimeout) as err:
        wait_for(
            lambda: runs,
            lambda _: False,
            timeout=0.2,
            interval=0.05,
            describe="pipelineruns succeeded",
        )
    message = str(err.value)
    assert "at-helm-x" in message  # the model data made it into the dump
    assert "result: error" in message


def test_reconciled_tolerates_a_retryable_reconcile_failure():
    """The operator retries, so a single `result: error` is not terminal — failing
    on sight of it would break runs that recover on the next reconcile."""
    assert reconciled(_errored_codebase(failure_count=1)) is False  # keep polling


def test_reconciled_aborts_once_the_operator_has_given_up():
    """A climbing failure count is a stuck CR: abort naming the operator's own
    reason instead of burning the full codebase_ready timeout."""
    with pytest.raises(FailFast, match="group quota exceeded") as err:
        reconciled(_errored_codebase(failure_count=3))
    assert "3x" in str(err.value)
    assert "put_project" in str(err.value)  # the action that failed


def test_reconciled_ignores_models_without_a_failure_count():
    """CDPipeline and Stage carry no failureCount; they must be unaffected."""

    class _StageLike:
        status = SimpleNamespace(available=True, result=SimpleNamespace(value="success"))

    assert reconciled(_StageLike()) is True


def test_transient_errors_are_retried_only_from_allowlist():
    attempts = []

    def flaky_fetch():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("transient")
        return "ok"

    assert wait_for(flaky_fetch, lambda v: v == "ok", timeout=10, interval=0) == "ok"


def test_non_allowlisted_error_propagates():
    def broken_fetch():
        raise ValueError("logic bug — must not be swallowed")

    with pytest.raises(ValueError, match="logic bug"):
        wait_for(broken_fetch, lambda _: True, timeout=5, interval=0)


def _raise_on_failed(value: str) -> bool:
    if value == "failed":
        raise FailFast("resource entered terminal failure")
    return False


def test_failfast_aborts_polling():
    with pytest.raises(FailFast):
        wait_for(lambda: "failed", _raise_on_failed, timeout=30, interval=0)


def test_not_found_retried_by_default():
    """Creation waits: 'not there yet' is the expected transient state."""
    attempts = []

    def eventually_created():
        attempts.append(1)
        if len(attempts) < 3:
            raise NotFound("not created yet")
        return "created"

    assert wait_for(eventually_created, lambda v: v == "created", timeout=10, interval=0)


def test_not_found_fails_fast_when_absence_is_terminal():
    """Post-creation waits: the resource existed — absence means it was deleted,
    fail immediately instead of burning the whole timeout."""

    def gone_fetch():
        raise NotFound("deleted mid-wait")

    with pytest.raises(NotFound):
        wait_for(
            gone_fetch,
            lambda _: True,
            timeout=30,
            interval=0,
            not_found="fail",
            describe="pipelinerun Succeeded",
        )


def test_wait_gone_returns_when_resource_already_absent():
    def fetch():
        raise NotFound("Codebase/x in ns")

    wait_gone(fetch, timeout=5, interval=0, describe="codebase x deleted")


def test_wait_gone_returns_once_the_resource_disappears():
    remaining = [{"metadata": {"deletionTimestamp": "2026-08-16T08:54:51Z"}}] * 2

    def fetch():
        if remaining:
            return remaining.pop()
        raise NotFound("gone")

    wait_gone(fetch, timeout=5, interval=0, describe="stage deleted")


def test_wait_gone_timeout_names_the_blocking_finalizer():
    wedged = {
        "metadata": {
            "deletionTimestamp": "2026-08-16T08:54:51Z",
            "finalizers": ["envLabelDeletion"],
        }
    }
    with pytest.raises(WaitTimeout, match="envLabelDeletion") as exc_info:
        wait_gone(lambda: wedged, timeout=0.2, interval=0.1, describe="stage deleted")
    assert "wedged" in str(exc_info.value)


def test_wait_gone_timeout_flags_a_deletion_never_requested():
    with pytest.raises(WaitTimeout, match="NEVER requested"):
        wait_gone(
            lambda: {"metadata": {"name": "x"}},
            timeout=0.2,
            interval=0.1,
            describe="cdpipeline deleted",
        )


def test_wait_gone_evidence_survives_wrapped_manifest_types():
    """kr8s raw manifests carry Box/BoxList wrappers yaml.safe_dump refuses;
    the evidence dump must coerce them instead of crashing the diagnostics."""

    class WrappedList(list):
        pass

    wedged = {
        "metadata": {
            "deletionTimestamp": "2026-08-16T08:54:51Z",
            "finalizers": WrappedList(["demo.krci/hold"]),
        }
    }
    with pytest.raises(WaitTimeout, match="demo.krci/hold"):
        wait_gone(lambda: wedged, timeout=0.2, interval=0.1, describe="namespace deleted")


def test_zero_timeout_still_attempts_one_fetch():
    """The deadline guards the SLEEP, never the fetch: even an exhausted budget
    gets one attempt, so a state change during the final sleep still counts."""
    assert wait_for(lambda: 42, lambda n: n == 42, timeout=0, interval=5) == 42

    def gone():
        raise NotFound("already gone")

    wait_gone(gone, timeout=0, interval=5, describe="instant")


def test_timeout_reports_measured_duration_and_limit():
    with pytest.raises(WaitTimeout, match=r"timed out after \d+s \(limit 0.2s\)"):
        wait_for(lambda: 1, lambda n: n == 2, timeout=0.2, interval=0.1, describe="never")


def test_cluster_timeout_budget_scales_with_the_knobs():
    """The hard kill switch is derived, not a literal: raising a wait knob must
    raise the budget too, or pytest-timeout kills the test before its own
    WaitTimeout can report the last-seen state."""
    from tests.conftest import _cluster_timeout_budget

    default = _cluster_timeout_budget(Timeouts())
    doubled = _cluster_timeout_budget(Timeouts(build_success=1800))
    assert doubled > default
    # covers the heaviest scenario in the suite at default knobs
    assert default >= 5400
