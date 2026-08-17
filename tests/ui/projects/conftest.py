"""Projects-page fixtures: the UI suite seeds its subject through the API
shortcut (CR), never through portal forms."""

import pytest

from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import helm_pipeline_library


@pytest.fixture
def codebase(owned_codebase: OwnedCodebase):
    """A ready codebase for the Projects list to show (helm triple, fast build)."""
    return owned_codebase(helm_pipeline_library(prefix="uipj"))
