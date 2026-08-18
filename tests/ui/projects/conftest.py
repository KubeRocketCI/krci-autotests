"""Projects-page fixtures: the UI suite seeds its subject through the API
shortcut (CR), never through portal forms."""

import pytest

from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import created_codebase
from tests.test_data.stacks import HELM_LIBRARY


@pytest.fixture
def codebase(owned_codebase: OwnedCodebase):
    """A ready codebase for the Projects list to show (helm stack, fast build)."""
    return owned_codebase(created_codebase(HELM_LIBRARY, "uipj"))
