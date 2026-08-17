import pytest

from krci_testkit.models import Codebase, name_of
from tests.ui.pageobjects.overview_page import OverviewPage


@pytest.mark.smoke
@pytest.mark.ui
def test_created_codebase_listed(codebase: Codebase, overview: OverviewPage):
    """An API-created codebase appears in the portal Projects list.

    Given a ready Codebase (seeded via CR — the API shortcut, not UI forms)
    And   an authenticated portal session (shared per-worker storage state)
    When  the user opens Projects and searches for the codebase name
    Then  the codebase's row is visible with platform-computed status "Created"

    Not asserted: row details beyond status (type/language/build-tool cells),
    counts, other projects.
    """
    projects = overview.open_projects()
    projects.search(name_of(codebase))
    projects.should_show_project(name_of(codebase))
