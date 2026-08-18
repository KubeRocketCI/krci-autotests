"""Branch-suite fixtures: the versioning scheme is what each scenario needs, so
the data lives with the scenario."""

import pytest

from krci_testkit.platform import VersioningType
from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import created_codebase
from tests.test_data.stacks import HELM_LIBRARY


@pytest.fixture
def branch_codebase(owned_codebase: OwnedCodebase):
    """Owned by the feature-branch lifecycle test."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "brch"))


@pytest.fixture
def semver_codebase(owned_codebase: OwnedCodebase):
    """A ready semver-versioned codebase (release branches require semver versioning)."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "vhelm", versioning=VersioningType.SEMVER))
