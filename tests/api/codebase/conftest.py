"""Codebase-suite fixtures. Each scenario declares its own test data here — the
onboarding strategy under test IS the scenario, so it belongs next to it rather
than in the root conftest. Distinct unique_name prefixes keep the codebases from
colliding inside one run (the owned_codebase factory enforces it)."""

import pytest

from tests.conftest import OwnedCodebase, OwnedImportedCodebase
from tests.test_data.codebase_data import (
    cloned_helm_library,
    helm_pipeline_library,
    imported_helm_library,
)


@pytest.fixture
def codebase(owned_codebase: OwnedCodebase):
    """A ready codebase (helm triple, default versioning)."""
    return owned_codebase(helm_pipeline_library())


@pytest.fixture
def cloned_codebase(owned_codebase: OwnedCodebase):
    """A ready clone-strategy codebase (public template repo as source)."""
    return owned_codebase(cloned_helm_library())


@pytest.fixture
def imported_codebase(owned_imported_codebase: OwnedImportedCodebase):
    """A ready import-strategy codebase over a repo seeded by a prior
    create-strategy codebase (created, then deleted — the repo survives)."""
    return owned_imported_codebase(helm_pipeline_library(prefix="impsd"), imported_helm_library)


@pytest.fixture
def squash_codebase(owned_codebase: OwnedCodebase):
    """Owned by the squash-merge test."""
    return owned_codebase(helm_pipeline_library(prefix="sqsh"))
