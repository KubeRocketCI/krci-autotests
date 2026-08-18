"""Deploy fixtures. built_codebase is the sanctioned expensive prerequisite:
ONE real build (go application — compiles and ships an image on arm64) shared
READ-ONLY by the manual-deploy and promote tests; each test creates its own
CDPipeline/Stage over it. AutoDeploy owns its codebase (its trigger IS the build)."""

from collections.abc import Generator, Iterator
from dataclasses import dataclass

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.models import Codebase, git_url_path_of
from krci_testkit.platform import VersioningType
from krci_testkit.waits import Timeouts
from tests.test_data.codebase_data import CodebaseTestData, created_codebase, simple_change
from tests.test_data.deploy_data import (
    CDPipelineTestData,
    journey_pipeline,
    manual_pipeline,
    promote_pipeline,
)
from tests.test_data.stacks import GO_GIN
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.deploy_utils import (
    CodebaseWithCd,
    codebase_with_cd_before_build,
    wait_image_entry,
)
from tests.utils.pipelinerun_utils import PipelineRuns, submit_and_verify_change


@dataclass(frozen=True)
class BuiltCodebase:
    codebase: Codebase
    data: CodebaseTestData
    tag: str
    digest: str | None


@pytest.fixture(scope="session")
def built_codebase(
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    pipeline_runs: PipelineRuns,
    cluster: Cluster,
    timeouts: Timeouts,
) -> Generator[BuiltCodebase]:
    data = created_codebase(GO_GIN, "go")
    created = codebase_utils.create_codebase(data)
    submit_and_verify_change(vcs, pipeline_runs, created, simple_change())
    entry = wait_image_entry(cluster, timeouts, data.name, data.default_branch)
    yield BuiltCodebase(codebase=created, data=data, tag=entry["name"], digest=entry.get("digest"))
    codebase_utils.delete_codebase(data.name)
    vcs.delete_repo(git_url_path_of(created))


@pytest.fixture
def manual_cd(
    built_codebase: BuiltCodebase, cd_utils: CDPipelineUtils
) -> Generator[CDPipelineTestData]:
    """A Manual-stage CD pipeline over the shared built codebase. Teardown is an
    assertion-free safety net; the happy path asserts deletion inside the test.
    """
    data = manual_pipeline(built_codebase.data.name, built_codebase.data.default_branch)
    cd_utils.create_cdpipeline(data)
    yield data
    cd_utils.cleanup_cdpipeline(data)


@pytest.fixture
def promote_cd(
    built_codebase: BuiltCodebase, cd_utils: CDPipelineUtils
) -> Generator[CDPipelineTestData]:
    """A two-stage (Manual dev -> Auto qa) promoting CD pipeline over the shared
    built codebase. Same safety-net teardown contract as manual_cd."""
    data = promote_pipeline(built_codebase.data.name, built_codebase.data.default_branch)
    cd_utils.create_cdpipeline(data)
    yield data
    cd_utils.cleanup_cdpipeline(data)


@pytest.fixture
def deploy_journey_setup(
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    cd_utils: CDPipelineUtils,
    cluster: Cluster,
    timeouts: Timeouts,
) -> Iterator[CodebaseWithCd]:
    """Journey CD pipeline (Auto dev -> Manual qa, promoting) over its own go
    codebase; created BEFORE any build (Auto stages react to CBIS updates). The
    test itself commits a qa values override to the platform's gitops repo."""
    yield from codebase_with_cd_before_build(
        codebase_utils,
        vcs,
        cd_utils,
        cluster,
        timeouts,
        # distinct prefixes: the full-chain journey owns "jgo"
        data=created_codebase(GO_GIN, "sgo", versioning=VersioningType.SEMVER),
        pipeline_factory=lambda app, branch: journey_pipeline(app, branch, prefix="sjr"),
    )
