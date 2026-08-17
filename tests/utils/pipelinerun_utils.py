"""Watch PipelineRuns the PLATFORM renders (webhook -> EventListener -> TriggerTemplate).

Tekton PipelineRuns only — CDPipeline CRs live in cdpipeline_utils. In this suite
bare "pipeline" always means the CDPipeline CR; a Tekton object is always a
"pipelinerun" or a "run", which is what this module handles.

The suite never creates PipelineRuns: runs are discovered by the
platform's own labels against a per-step baseline, so earlier runs and duplicate
webhook deliveries (a known GitLab behavior — the duplicate fails fast on its
report-status task) can never be mistaken for the run under test.
"""

import logging

from krci_testkit import labels
from krci_testkit.clients import Change, MergeStrategy, VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.models import (
    Codebase,
    PipelineRun,
    default_branch_of,
    git_url_path_of,
    name_of,
)
from krci_testkit.naming import branch_cr_name
from krci_testkit.platform import PipelineType
from krci_testkit.waits import FailFast, Timeouts, wait_for
from tests.test_data.codebase_data import ChangeTestData

log = logging.getLogger(__name__)


def deploy_labels(cdpipeline: str, stage_cr_name: str | None = None) -> dict[str, str]:
    """Selector for platform-rendered deploy runs (stage_cr_name = <pipeline>-<stage>)."""
    selector = {labels.CDPIPELINE: cdpipeline, labels.PIPELINE_TYPE: PipelineType.DEPLOY}
    if stage_cr_name:
        selector[labels.CDSTAGE] = stage_cr_name
    return selector


class PipelineRuns:
    def __init__(self, cluster: Cluster, timeouts: Timeouts):
        self.cluster = cluster
        self.timeouts = timeouts

    def baseline_for(self, labels: dict[str, str]) -> frozenset[str]:
        """Names of runs that already exist; wait_success_for only considers newer ones."""
        return frozenset(name_of(r) for r in self.cluster.list(PipelineRun, labels=labels))

    def wait_success_for(
        self,
        labels: dict[str, str],
        *,
        since: frozenset[str],
        timeout: float,
        describe_what: str,
    ) -> PipelineRun:
        def fresh() -> list[PipelineRun]:
            return [
                r for r in self.cluster.list(PipelineRun, labels=labels) if name_of(r) not in since
            ]

        wait_for(
            fresh,
            lambda runs: bool(runs),
            timeout=self.timeouts.run_trigger,
            interval=self.timeouts.poll_interval,
            describe=f"platform renders a {describe_what} pipelinerun",
        )
        runs = wait_for(
            fresh,
            _any_succeeded,
            timeout=timeout,
            interval=self.timeouts.poll_interval,
            describe=f"{describe_what} pipelinerun Succeeded",
        )
        # Newest of the succeeded runs, not the first the API happened to return:
        # a duplicate webhook delivery can leave two green runs, and list order is
        # not chronological, so "the run under test" would otherwise be a coin flip.
        winner = max((run for run in runs if _succeeded(run)), key=_started_at)
        log.info("%s pipelinerun %s succeeded", describe_what, name_of(winner))
        return winner

    def _codebase_labels(
        self, codebase: str, pipeline_type: PipelineType, branch: str | None
    ) -> dict[str, str]:
        selector = {labels.CODEBASE: codebase, labels.PIPELINE_TYPE: pipeline_type}
        if branch:
            selector[labels.CODEBASE_BRANCH] = branch_cr_name(codebase, branch)
        return selector

    def baseline(
        self, codebase: str, pipeline_type: PipelineType, *, branch: str | None = None
    ) -> frozenset[str]:
        return self.baseline_for(self._codebase_labels(codebase, pipeline_type, branch))

    def wait_success(
        self,
        codebase: str,
        pipeline_type: PipelineType,
        *,
        since: frozenset[str],
        timeout_factor: float = 1.0,
        branch: str | None = None,
    ) -> PipelineRun:
        return self.wait_success_for(
            self._codebase_labels(codebase, pipeline_type, branch),
            since=since,
            timeout=self.timeouts.build_success * timeout_factor,
            describe_what=f"{pipeline_type} for {codebase}" + (f"@{branch}" if branch else ""),
        )


def submit_change_and_wait_review(
    vcs: VCSProvider,
    pipeline_runs: PipelineRuns,
    codebase: Codebase,
    change_data: ChangeTestData,
    *,
    branch: str | None = None,
) -> Change:
    """Submit a change and wait for the platform-rendered review run to succeed.

    branch targets a non-default branch and filters runs to it (the platform labels
    both review and build runs with app.edp.epam.com/codebasebranch)."""
    codebase_name = name_of(codebase)
    # Always scope to a branch, defaulting to the codebase's own. The platform labels
    # default-branch runs too, so leaving the filter off would let a run from ANOTHER
    # branch of the same codebase satisfy this wait.
    target = branch or default_branch_of(codebase)
    review_seen = pipeline_runs.baseline(codebase_name, PipelineType.REVIEW, branch=target)
    change = vcs.submit_change(
        git_url_path_of(codebase),
        source_branch=change_data.source_branch,
        target_branch=target,
        title=change_data.title,
        files=change_data.files,
    )
    pipeline_runs.wait_success(codebase_name, PipelineType.REVIEW, since=review_seen, branch=target)
    return change


def merge_and_wait_build(
    vcs: VCSProvider,
    pipeline_runs: PipelineRuns,
    codebase: Codebase,
    change: Change,
    *,
    strategy: MergeStrategy = MergeStrategy.MERGE,
    branch: str | None = None,
) -> None:
    """Merge the change (neutral strategy) and wait for the build run to succeed."""
    codebase_name = name_of(codebase)
    target = branch or default_branch_of(codebase)
    build_seen = pipeline_runs.baseline(codebase_name, PipelineType.BUILD, branch=target)
    vcs.merge_change(git_url_path_of(codebase), change, strategy=strategy)
    pipeline_runs.wait_success(codebase_name, PipelineType.BUILD, since=build_seen, branch=target)


def submit_and_verify_change(
    vcs: VCSProvider,
    pipeline_runs: PipelineRuns,
    codebase: Codebase,
    change_data: ChangeTestData,
    *,
    branch: str | None = None,
) -> None:
    """Real trigger path: submit -> review succeeds -> merge -> build succeeds."""
    change = submit_change_and_wait_review(vcs, pipeline_runs, codebase, change_data, branch=branch)
    merge_and_wait_build(
        vcs, pipeline_runs, codebase, change, strategy=change_data.merge_strategy, branch=branch
    )


def _started_at(run: PipelineRun) -> str:
    """Tekton's status.startTime, for ordering runs by when the platform began them.

    Unwrapped via .root, not str(): startTime is a RootModel, whose str() is the
    repr "root='...'". That happens to sort identically today, but only by accident
    of a constant prefix — ordering must not depend on a model's repr.

    Absent on a run the controller has not admitted yet, which sorts it first —
    correct, since such a run cannot be the succeeded one being chosen between."""
    started = getattr(run.status, "startTime", None) if run.status else None
    if started is None:
        return ""
    return str(getattr(started, "root", started) or "")


def _condition(run: PipelineRun) -> dict:
    # KnativeCondition is a pydantic RootModel[Any]; .root is the raw dict it wraps.
    for cond in (run.status.conditions or []) if run.status else []:
        raw = cond.root
        if raw.get("type") == "Succeeded":
            return raw
    return {}


def _succeeded(run: PipelineRun) -> bool:
    return _condition(run).get("status") == "True"


def _failed(run: PipelineRun) -> bool:
    return _condition(run).get("status") == "False"


def _any_succeeded(runs: list[PipelineRun]) -> bool:
    if any(_succeeded(run) for run in runs):
        return True
    if runs and all(_failed(run) for run in runs):
        raise FailFast(
            "all triggered runs failed: "
            + "; ".join(
                f"{name_of(r)}: {_condition(r).get('reason')}: {_condition(r).get('message')}"
                for r in runs
            )
        )
    return False
