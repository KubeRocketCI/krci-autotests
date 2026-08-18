import pytest

from krci_testkit.clients import MergeStrategy, VCSProvider
from krci_testkit.models import Codebase, git_url_path_of
from krci_testkit.platform import CIStatus
from tests.test_data.codebase_data import simple_change
from tests.utils.pipelinerun_utils import (
    PipelineRuns,
    merge_and_wait_build,
    submit_change_and_wait_review,
)


@pytest.mark.api
def test_squash_merge_triggers_build(
    squash_codebase: Codebase, pipeline_runs: PipelineRuns, vcs: VCSProvider
):
    """A squash merge lands the change and triggers the build pipeline.

    Given a ready Codebase with an open, review-passed change
    Then  the platform reported a success CI status on the change's head commit
          (the review pipeline's report task posted it — user-visible merge gate)
    When  the change is merged with the squash strategy (neutral verb; the
          client translates to its native squash mechanics and asserts the
          provider ACTUALLY squashed — silent-degradation guard)
    Then  the merge completes in the VCS
    And   the platform renders a build PipelineRun that succeeds

    Not asserted: plain merge (implicitly exercised by every other lifecycle
    test); fast-forward (payload fallback covered by edp-tekton unit test
    "merge event without merge_commit_sha"); resulting git history shape
    (provider-internal); the status's context name and deep-link URL
    (chart-version copy / environment-fragile pipelineUrl).
    """
    change_data = simple_change(prefix="sqch", merge_strategy=MergeStrategy.SQUASH)
    change = submit_change_and_wait_review(vcs, pipeline_runs, squash_codebase, change_data)
    statuses = vcs.change_statuses(git_url_path_of(squash_codebase), change)
    assert any(s.state is CIStatus.SUCCESS for s in statuses), f"no success CI status: {statuses}"
    merge_and_wait_build(vcs, pipeline_runs, squash_codebase, change, strategy=MergeStrategy.SQUASH)
