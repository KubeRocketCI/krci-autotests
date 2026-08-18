import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.models import name_of
from tests.conftest import OwnedCodebase, OwnedImportedCodebase
from tests.test_data.codebase_data import (
    cloned_codebase,
    created_codebase,
    imported_codebase,
    simple_change,
)
from tests.test_data.stacks import CATALOG, Stack
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.pipelinerun_utils import PipelineRuns, submit_and_verify_change


@pytest.mark.api
@pytest.mark.parametrize("stack", CATALOG.values(), ids=lambda stack: stack.key)
def test_codebase_create_lifecycle(
    stack: Stack,
    owned_codebase: OwnedCodebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Codebase lifecycle through the platform's real trigger path, per stack.

    One case per catalog stack, so a language added to the catalog is covered
    without new test code. A suite names the cases it runs; nothing here decides.

    Given a KRCI cluster with a connected GitServer
    When  a Codebase is created via CR for this stack (create strategy)
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
    (teardown deletes it best-effort — the operator never does); which pipeline
    the platform picked (a green run for the stack is the evidence).

    A stack whose pipelines the target cluster does not serve fails here — the
    platform's configuration is the finding, not something the suite arranges.
    """
    codebase = owned_codebase(created_codebase(stack, f"cl-{stack.slug}"))
    name = name_of(codebase)
    submit_and_verify_change(vcs, pipeline_runs, codebase, simple_change(prefix=f"cc-{stack.slug}"))
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)


@pytest.mark.api
@pytest.mark.parametrize("stack", CATALOG.values(), ids=lambda stack: stack.key)
def test_codebase_import_lifecycle(
    stack: Stack,
    owned_imported_codebase: OwnedImportedCodebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Import-strategy onboarding of an existing repo, then the real trigger path,
    per stack.

    One case per catalog stack, so a language added to the catalog is covered
    without new test code. A suite names the cases it runs; nothing here decides.

    Given an EXISTING GitServer repo the platform did not shape — seeded with the
          content of the stack's public source repo through the provider API
          (the real user-flow precondition: a repo with real content to onboard)
    When  an import-strategy Codebase is created over that repo's gitUrlPath
    Then  the operator builds the platform wiring from scratch — webhook, default
          branch CR — and Codebase + default branch become ready (fixture asserts it)
    When  a change is submitted and merged
    Then  the platform renders review and build PipelineRuns and both succeed
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster

    Not asserted: deploy-template injection — the source scaffold already carries
    the templates, so this test proves onboarding and CI wiring of an existing
    repo, never repo-content transformation (that stays with the operator's own
    controller tests); source history fidelity (the seed is the source's HEAD
    content as one commit); VCS repo removal (best-effort teardown).
    """
    codebase = owned_imported_codebase(
        stack.template_repo_url, imported_codebase(stack, f"im-{stack.slug}")
    )
    name = name_of(codebase)
    submit_and_verify_change(vcs, pipeline_runs, codebase, simple_change(prefix=f"ic-{stack.slug}"))
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)


@pytest.mark.api
@pytest.mark.parametrize("stack", CATALOG.values(), ids=lambda stack: stack.key)
def test_codebase_clone_lifecycle(
    stack: Stack,
    owned_codebase: OwnedCodebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Clone-strategy onboarding: the operator clones an external source repo
    into a new GitServer repo, then the real trigger path, per stack.

    One case per catalog stack, so a language added to the catalog is covered
    without new test code. A suite names the cases it runs; nothing here decides.

    Given a public source repo (the stack's own template repo — the same source
          create strategy uses internally, so no clone credentials)
    When  a clone-strategy Codebase is created with spec.repository.url set
    Then  the operator clones the source history as-is and pushes it; Codebase +
          default branch become ready (fixture asserts readiness)
    When  a change is submitted and merged
    Then  the platform renders review and build PipelineRuns and both succeed
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster

    Not asserted: cloneRepositoryCredentials (public source — the private-source
    credential path stays with the operator's own put_project tests); commit
    squashing (a create-strategy-only operation — cloned history is preserved);
    deploy-template injection (the template source already carries them);
    VCS repo removal (best-effort teardown); the chained branch steps, owned by
    the branch lifecycle tests.
    """
    codebase = owned_codebase(cloned_codebase(stack, f"cn-{stack.slug}"))
    name = name_of(codebase)
    submit_and_verify_change(vcs, pipeline_runs, codebase, simple_change(prefix=f"cm-{stack.slug}"))
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)
