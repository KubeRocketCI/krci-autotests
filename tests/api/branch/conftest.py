"""Branch-suite fixtures: the versioning scheme is what each scenario needs, so
the data lives with the scenario."""

import pytest

from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import helm_pipeline_library, semver_helm_library


@pytest.fixture
def branch_codebase(owned_codebase: OwnedCodebase):
    """Owned by the feature-branch lifecycle test."""
    return owned_codebase(helm_pipeline_library(prefix="brch"))


@pytest.fixture
def semver_codebase(owned_codebase: OwnedCodebase):
    """A ready semver-versioned codebase (release branches require semver versioning)."""
    return owned_codebase(semver_helm_library())
