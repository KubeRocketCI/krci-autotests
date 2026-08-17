import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.models import Codebase, git_url_path_of, name_of
from krci_testkit.platform import PipelineType
from tests.test_data.codebase_data import recheck_comment, smoke_change
from tests.utils.pipelinerun_utils import PipelineRuns, submit_change_and_wait_review


@pytest.mark.regression
@pytest.mark.api
def test_recheck_comment_reruns_review(
    recheck_codebase: Codebase, pipeline_runs: PipelineRuns, vcs: VCSProvider
):
    """A /recheck comment re-renders the review pipeline through the real
    comment-event path (VCS note webhook -> EventListener -> interceptor ->
    TriggerTemplate).

    Given a ready Codebase with an open change whose review run succeeded
    When  "/recheck" is commented on the change
    Then  the platform renders a SECOND review PipelineRun and it succeeds

    Not asserted: non-conforming comments being ignored (starts-with filter —
    covered by edp-tekton unit tests: TestContainsPipelineRecheckPrefix,
    gitlab processor and interceptor "comment event with no recheck" cases);
    /ok-to-test (same interceptor branch); recheck on build pipelines (no such
    platform behavior).
    """
    name = name_of(recheck_codebase)
    change = submit_change_and_wait_review(vcs, pipeline_runs, recheck_codebase, smoke_change())
    rerun_seen = pipeline_runs.baseline(name, PipelineType.REVIEW)
    vcs.comment_change(git_url_path_of(recheck_codebase), change, recheck_comment())
    pipeline_runs.wait_success(name, PipelineType.REVIEW, since=rerun_seen)
