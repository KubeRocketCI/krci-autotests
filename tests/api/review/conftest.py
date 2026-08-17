"""Review-suite fixtures."""

import pytest

from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import helm_pipeline_library


@pytest.fixture
def recheck_codebase(owned_codebase: OwnedCodebase):
    """Owned by the recheck test."""
    return owned_codebase(helm_pipeline_library(prefix="rchk"))
