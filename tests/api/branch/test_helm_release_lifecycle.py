"""Clone strategy + semver + release-branch lifecycle in one codebase."""

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.models import Codebase, name_of
from tests.test_data.codebase_data import release_branch, simple_change
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.pipelinerun_utils import PipelineRuns, submit_and_verify_change


@pytest.mark.api
def test_helm_release_lifecycle(
    cloned_semver_codebase: Codebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Release-branch CRUD on a clone-strategy semver codebase (real trigger path).

    Given a helm library onboarded with the CLONE strategy (public template repo
          as source) and SEMVER versioning — one codebase covering both smoke
          dimensions
    Then  the codebase and its default branch become ready (fixture asserts —
          this alone proves the clone operator path end to end)
    When  a release CodebaseBranch CR (release=true, explicit version) is created
    Then  the branch becomes ready (the operator creates the git branch and the
          semver branch pipelines)
    When  a change is submitted to the release branch and merged
    Then  the platform renders review and build PipelineRuns labeled with the
          branch, and both succeed
    When  the CodebaseBranch CR is deleted
    Then  it is fully removed from the cluster

    Not asserted: computed branch-version semantics and the default-branch
    version bump (regression scope — versioning specifics per build tool are
    deliberately out of smoke); git-branch removal in the VCS (the operator
    never deletes remote branches); clone content fidelity. This is the smoke
    recomposition of clone x release-branch; the regression suite keeps the
    per-dimension tests.
    """
    name = name_of(cloned_semver_codebase)
    branch = release_branch()
    codebase_utils.create_branch(name, branch)
    submit_and_verify_change(
        vcs,
        pipeline_runs,
        cloned_semver_codebase,
        simple_change(prefix="srl"),
        branch=branch.branch_name,
    )
    codebase_utils.delete_branch(name, branch.branch_name)
    codebase_utils.wait_branch_deleted(name, branch.branch_name)
