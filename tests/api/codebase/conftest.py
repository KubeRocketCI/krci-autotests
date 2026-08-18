"""Codebase-suite fixtures. Each scenario declares its own test data here — the
onboarding strategy under test IS the scenario, so it belongs next to it rather
than in the root conftest. Distinct unique_name prefixes keep the codebases from
colliding inside one run (the owned_codebase factory enforces it)."""

import pytest

from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import created_codebase
from tests.test_data.stacks import HELM_LIBRARY


@pytest.fixture
def squash_codebase(owned_codebase: OwnedCodebase):
    """Owned by the squash-merge test."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "sqsh"))
