import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.models import Codebase, name_of
from tests.test_data.codebase_data import feature_branch, release_branch, simple_change
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.pipelinerun_utils import PipelineRuns, submit_and_verify_change


@pytest.mark.api
def test_feature_branch_lifecycle(
    branch_codebase: Codebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Non-default branch CRUD through the real trigger path.

    Given a ready default-versioned Codebase
    When  a CodebaseBranch CR is created for a feature branch
    Then  the branch becomes ready (the operator creates the git branch and
          branch pipelines) (timeout_codebase_ready)
    When  a change is submitted to that branch and merged
    Then  the platform renders review and build PipelineRuns labeled with the
          branch, and both succeed
    When  the CodebaseBranch CR is deleted
    Then  it is fully removed from the cluster (timeout_codebase_delete)

    Not asserted: git-branch removal in the VCS (the operator does not delete
    remote branches); CodebaseImageStream cleanup (operator-internal cascade).
    """
    name = name_of(branch_codebase)
    branch = feature_branch()
    codebase_utils.create_branch(name, branch)
    submit_and_verify_change(
        vcs, pipeline_runs, branch_codebase, simple_change(), branch=branch.branch_name
    )
    codebase_utils.delete_branch(name, branch.branch_name)
    codebase_utils.wait_branch_deleted(name, branch.branch_name)


@pytest.mark.api
def test_release_branch_lifecycle(
    semver_codebase: Codebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Release branch CRUD on a semver-versioned codebase through the real trigger path.

    Given a ready semver-versioned Codebase
    When  a release CodebaseBranch CR (release=true, explicit version) is created
    Then  the branch becomes ready
    When  a change is submitted to the release branch and merged
    Then  review and build PipelineRuns for that branch succeed
    When  the CodebaseBranch CR is deleted
    Then  it is fully removed from the cluster

    Not asserted: the computed branch version semantics (portal-side concern);
    default-branch version bump after release-branch creation.
    """
    name = name_of(semver_codebase)
    branch = release_branch()
    codebase_utils.create_branch(name, branch)
    submit_and_verify_change(
        vcs, pipeline_runs, semver_codebase, simple_change(), branch=branch.branch_name
    )
    codebase_utils.delete_branch(name, branch.branch_name)
    codebase_utils.wait_branch_deleted(name, branch.branch_name)
