"""Branch fixtures: the onboarding strategy and versioning scheme are what each
scenario needs, so the data lives with the scenario."""

from collections.abc import Callable, Iterator

import pytest

from krci_testkit.platform import VersioningType
from tests.conftest import OwnedCodebase, OwnedImportedCodebase
from tests.test_data.codebase_data import cloned_codebase, created_codebase, imported_codebase
from tests.test_data.deploy_data import CDPipelineTestData
from tests.test_data.stacks import HELM_LIBRARY, PY_FASTAPI
from tests.utils.cdpipeline_utils import CDPipelineUtils


@pytest.fixture
def branch_codebase(owned_codebase: OwnedCodebase):
    """Owned by the feature-branch lifecycle test."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "brch"))


@pytest.fixture
def semver_codebase(owned_codebase: OwnedCodebase):
    """A ready semver-versioned codebase (release branches require semver versioning)."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "vhelm", versioning=VersioningType.SEMVER))


@pytest.fixture
def cloned_semver_codebase(owned_codebase: OwnedCodebase):
    """Clone-strategy + semver codebase: one codebase covering both dimensions."""
    return owned_codebase(cloned_codebase(HELM_LIBRARY, "csl", versioning=VersioningType.SEMVER))


@pytest.fixture
def imported_fastapi_codebase(owned_imported_codebase: OwnedImportedCodebase):
    """Import-strategy fastapi application over a repo seeded from the stack's
    public source repo — an existing repo the platform did not shape."""
    return owned_imported_codebase(
        PY_FASTAPI.template_repo_url, imported_codebase(PY_FASTAPI, "pysd")
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
