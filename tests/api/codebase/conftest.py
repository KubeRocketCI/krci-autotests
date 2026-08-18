"""Codebase-suite fixtures. Each scenario declares its own test data here — the
onboarding strategy under test IS the scenario, so it belongs next to it rather
than in the root conftest. Distinct unique_name prefixes keep the codebases from
colliding inside one run (the owned_codebase factory enforces it).

The data builders are imported under `*_data` names: the fixtures below are named
after the strategy under test, and would otherwise rebind the builder they call.
"""

import pytest

from tests.conftest import OwnedCodebase, OwnedImportedCodebase
from tests.test_data.codebase_data import HELM_LIBRARY
from tests.test_data.codebase_data import cloned_codebase as cloned_codebase_data
from tests.test_data.codebase_data import created_codebase as created_codebase_data
from tests.test_data.codebase_data import imported_codebase as imported_codebase_data


@pytest.fixture
def codebase(owned_codebase: OwnedCodebase):
    """A ready codebase (helm stack, default versioning)."""
    return owned_codebase(created_codebase_data(HELM_LIBRARY, "helm"))


@pytest.fixture
def cloned_codebase(owned_codebase: OwnedCodebase):
    """A ready clone-strategy codebase (public template repo as source)."""
    return owned_codebase(cloned_codebase_data(HELM_LIBRARY, "cln"))


@pytest.fixture
def imported_codebase(owned_imported_codebase: OwnedImportedCodebase):
    """A ready import-strategy codebase over a repo seeded by a prior
    create-strategy codebase (created, then deleted — the repo survives)."""
    return owned_imported_codebase(
        created_codebase_data(HELM_LIBRARY, "impsd"),
        lambda source_path: imported_codebase_data(HELM_LIBRARY, "imp", source_path),
    )


@pytest.fixture
def squash_codebase(owned_codebase: OwnedCodebase):
    """Owned by the squash-merge test."""
    return owned_codebase(created_codebase_data(HELM_LIBRARY, "sqsh"))
