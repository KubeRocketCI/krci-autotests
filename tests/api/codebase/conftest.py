"""Codebase-suite fixtures. Each scenario declares its own test data here — the
onboarding strategy under test IS the scenario, so it belongs next to it rather
than in the root conftest. Distinct unique_name prefixes keep the codebases from
colliding inside one run (the owned_codebase factory enforces it)."""

import pytest

from krci_testkit.clients import MergeStrategy, VCSProvider
from krci_testkit.models import GitServer
from tests.conftest import OwnedCodebase
from tests.test_data.codebase_data import created_codebase
from tests.test_data.stacks import HELM_LIBRARY


@pytest.fixture
def squash_codebase(owned_codebase: OwnedCodebase, vcs: VCSProvider, git_server: GitServer):
    """Owned by the squash-merge test."""
    if MergeStrategy.SQUASH not in vcs.merge_strategies:
        pytest.skip(
            f"{git_server.spec.gitProvider.value} cannot land a change as a "
            f"'{MergeStrategy.SQUASH}' merge (its client lands: "
            f"{', '.join(sorted(vcs.merge_strategies))})"
        )
    return owned_codebase(created_codebase(HELM_LIBRARY, "sqsh"))
