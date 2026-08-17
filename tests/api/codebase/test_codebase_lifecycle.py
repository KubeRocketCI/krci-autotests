import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.models import Codebase, name_of
from tests.test_data.codebase_data import smoke_change
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.pipelinerun_utils import PipelineRuns, submit_and_verify_change


@pytest.mark.regression
@pytest.mark.api
def test_codebase_create_lifecycle(
    codebase: Codebase, codebase_utils: CodebaseUtils, pipeline_runs: PipelineRuns, vcs: VCSProvider
):
    """Codebase lifecycle through the platform's real trigger path.

    Given a KRCI cluster with a connected GitServer
    When  a Codebase is created via CR (create strategy, unique run-ID name)
    Then  the repo is provisioned; Codebase + default branch become ready
    When  a change is submitted for review in the VCS (branch + commit + change request)
    Then  the platform renders a review PipelineRun via its own webhook/trigger
          chain and the run succeeds (timeout_run_trigger + timeout_build_success)
    When  the change is merged
    Then  the platform renders a build PipelineRun and it succeeds
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster (timeout_codebase_delete)

    Not asserted: the pipelineUrl deep-link param (environment-computed default
    that does not track the portal ingress everywhere); VCS repo removal
    (teardown deletes it best-effort — the operator never does).
    """
    name = name_of(codebase)
    submit_and_verify_change(vcs, pipeline_runs, codebase, smoke_change())
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)


@pytest.mark.regression
@pytest.mark.api
def test_codebase_import_lifecycle(
    imported_codebase: Codebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Import-strategy onboarding of an existing repo, then the real trigger path.

    Given a VCS repo seeded by a former create-strategy codebase (repo survives deletion)
    When  an import-strategy Codebase is created over that repo's gitUrlPath
    Then  Codebase + default branch become ready (fixture asserts readiness)
    When  a change is submitted and merged
    Then  the platform renders review and build PipelineRuns and both succeed
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster

    Not asserted: repo content fidelity after import; VCS repo removal (best-effort
    teardown).
    """
    name = name_of(imported_codebase)
    submit_and_verify_change(vcs, pipeline_runs, imported_codebase, smoke_change())
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)


@pytest.mark.regression
@pytest.mark.api
def test_codebase_clone_lifecycle(
    cloned_codebase: Codebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Clone-strategy onboarding: the operator clones an external source repo
    into a new GitServer repo, then the real trigger path.

    Given a public source repo (the platform's own helm-helm-pipeline template —
          the same source create strategy uses internally, so no clone credentials)
    When  a clone-strategy Codebase is created with spec.repository.url set
    Then  the operator clones, squashes and pushes the repo; Codebase + default
          branch become ready (fixture asserts readiness)
    When  a change is submitted and merged
    Then  the platform renders review and build PipelineRuns and both succeed
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster

    Not asserted: cloneRepositoryCredentials (public source — the private-source
    credential path stays with the operator's own put_project tests); commit
    squashing details; VCS repo removal (best-effort teardown); the chained
    branch steps, owned by the branch lifecycle tests.
    """
    name = name_of(cloned_codebase)
    submit_and_verify_change(vcs, pipeline_runs, cloned_codebase, smoke_change())
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)
