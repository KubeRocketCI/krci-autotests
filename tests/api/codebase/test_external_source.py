import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.models import name_of
from tests.conftest import OwnedCodebase, OwnedImportedCodebase
from tests.test_data.codebase_data import cloned_codebase, imported_codebase, simple_change
from tests.test_data.external_sources import (
    EXTERNAL_CLONE_SOURCES,
    EXTERNAL_IMPORT_SOURCES,
    ExternalSource,
)
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.pipelinerun_utils import PipelineRuns, submit_and_verify_change


@pytest.mark.api
@pytest.mark.parametrize("source", EXTERNAL_CLONE_SOURCES, ids=lambda source: source.key)
def test_external_clone_lifecycle(
    source: ExternalSource,
    owned_codebase: OwnedCodebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Clone-strategy onboarding from a NAMED external source repo, then the real
    trigger path.

    One case per external_sources.py entry: covering a specific repo is one entry
    plus one suites.yaml line. A suite names the cases it runs; nothing here decides.

    Given the named public source repo (external_sources.py declares the URL and
          the stack whose pipelines its content matches)
    When  a clone-strategy Codebase is created with spec.repository.url set to it
    Then  the operator clones the source into a new GitServer repo; Codebase +
          default branch become ready (fixture asserts readiness)
    When  a change is submitted and merged
    Then  the platform renders review and build PipelineRuns and both succeed
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster

    Not asserted: everything the catalog clone lifecycle already excludes
    (credentials, squash, template injection, branch chains); the source repo is
    never touched or owned.
    """
    codebase = owned_codebase(
        cloned_codebase(source.stack, f"xc-{source.slug}", repository_url=source.url)
    )
    name = name_of(codebase)
    submit_and_verify_change(
        vcs, pipeline_runs, codebase, simple_change(prefix=f"xcc-{source.slug}")
    )
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)


@pytest.mark.api
@pytest.mark.parametrize("source", EXTERNAL_IMPORT_SOURCES, ids=lambda source: source.key)
def test_external_import_lifecycle(
    source: ExternalSource,
    owned_imported_codebase: OwnedImportedCodebase,
    codebase_utils: CodebaseUtils,
    pipeline_runs: PipelineRuns,
    vcs: VCSProvider,
):
    """Import-strategy onboarding of a repo seeded from a NAMED external source,
    then the real trigger path.

    One case per external_sources.py entry: covering a specific repo is one entry
    plus one suites.yaml line. A suite names the cases it runs; nothing here decides.

    Given a GitServer repo seeded with the named source repo's content through the
          provider API (an existing repo with real content — the platform played
          no part in shaping it)
    When  an import-strategy Codebase is created over that repo's gitUrlPath
    Then  the operator builds the platform wiring from scratch and Codebase +
          default branch become ready (fixture asserts readiness)
    When  a change is submitted and merged
    Then  the platform renders review and build PipelineRuns and both succeed
    When  the Codebase is deleted
    Then  the CR is fully removed from the cluster

    Not asserted: everything the catalog import lifecycle already excludes
    (template injection, source history fidelity, repo removal).
    """
    codebase = owned_imported_codebase(
        source.url, imported_codebase(source.stack, f"xi-{source.slug}")
    )
    name = name_of(codebase)
    submit_and_verify_change(
        vcs, pipeline_runs, codebase, simple_change(prefix=f"xic-{source.slug}")
    )
    codebase_utils.delete_codebase(name)
    codebase_utils.wait_deleted(name)
