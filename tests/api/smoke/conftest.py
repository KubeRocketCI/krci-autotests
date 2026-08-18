"""Smoke-suite fixtures. The three API smoke tests are designed for one fully
parallel run (`-n 3`): each owns uniquely-named resources end to end, and the
suite holds no shared mutable state."""

from collections.abc import Callable, Iterator

import pytest

from krci_testkit.clients import VCSProvider
from krci_testkit.clusters import Cluster
from krci_testkit.platform import VersioningType
from krci_testkit.waits import Timeouts
from tests.conftest import OwnedCodebase, OwnedImportedCodebase
from tests.test_data.codebase_data import cloned_codebase, created_codebase, imported_codebase
from tests.test_data.deploy_data import CDPipelineTestData, journey_pipeline
from tests.test_data.stacks import GO_GIN, HELM_LIBRARY, PY_FASTAPI
from tests.utils.cdpipeline_utils import CDPipelineUtils
from tests.utils.codebase_utils import CodebaseUtils
from tests.utils.deploy_utils import CodebaseWithCd, codebase_with_cd_before_build


@pytest.fixture
def cloned_semver_codebase(owned_codebase: OwnedCodebase):
    """Clone-strategy + semver codebase (smoke: one codebase, two dimensions)."""
    return owned_codebase(cloned_codebase(HELM_LIBRARY, "csl", versioning=VersioningType.SEMVER))


@pytest.fixture
def imported_fastapi_codebase(owned_imported_codebase: OwnedImportedCodebase):
    """Import-strategy fastapi application, re-imported UNDER THE SEED'S NAME
    (registry image paths must match an existing GitLab project)."""
    seed = created_codebase(PY_FASTAPI, "pysd")
    return owned_imported_codebase(
        seed, lambda path: imported_codebase(PY_FASTAPI, "pysd", path, name=seed.name)
    )


# Published beside the factory that produces it, the way the root conftest
# publishes OwnedCodebase — a consumer annotates this name, not a bare Callable.
OwnedPipeline = Callable[[CDPipelineTestData], CDPipelineTestData]


@pytest.fixture
def owned_pipeline(cd_utils: CDPipelineUtils) -> Iterator[OwnedPipeline]:
    """Factory for CD pipelines created mid-test (e.g. over a branch stream that
    does not exist until the test builds it). Teardown is an assertion-free
    safety net — happy paths assert deletion inside the test; cleanup_cdpipeline
    waits for full deletion so later codebase teardown cannot race the Stage
    finalizer."""
    created: list[CDPipelineTestData] = []

    def _create(data: CDPipelineTestData) -> CDPipelineTestData:
        cd_utils.create_cdpipeline(data)
        created.append(data)
        return data

    yield _create
    for data in created:
        cd_utils.cleanup_cdpipeline(data)


@pytest.fixture
def smoke_journey_setup(
    codebase_utils: CodebaseUtils,
    vcs: VCSProvider,
    cd_utils: CDPipelineUtils,
    cluster: Cluster,
    timeouts: Timeouts,
) -> Iterator[CodebaseWithCd]:
    """Smoke journey CD pipeline (Auto dev -> Manual qa, promoting) over its own
    go codebase; created BEFORE any build (Auto stages react to CBIS updates).
    The test itself commits a qa values override to the platform's gitops repo."""
    yield from codebase_with_cd_before_build(
        codebase_utils,
        vcs,
        cd_utils,
        cluster,
        timeouts,
        # distinct prefixes: regression owns "go"/"jgo"
        data=created_codebase(GO_GIN, "sgo", versioning=VersioningType.SEMVER),
        pipeline_factory=lambda app, branch: journey_pipeline(app, branch, prefix="sjr"),
    )
