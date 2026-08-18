"""Review-suite fixtures."""

import pytest

from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import created_codebase
from tests.test_data.stacks import HELM_LIBRARY


@pytest.fixture
def recheck_codebase(owned_codebase: OwnedCodebase):
    """Owned by the recheck test."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "rchk"))
