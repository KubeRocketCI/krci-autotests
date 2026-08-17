import pytest

from tests.ui.pageobjects.overview_page import OverviewPage


@pytest.mark.smoke
@pytest.mark.ui
def test_overview_page_loads(overview: OverviewPage):
    """Overview renders for an authenticated session.

    Given an authenticated portal session (shared per-worker storage state)
    When  the user opens the Overview page
    Then  the Overview page renders its widget tiles

    Not asserted: widget counts vs cluster state; the login flow itself
    (owned by test_token_login_opens_overview).
    """
    overview.open_overview().should_show_overview_widgets()
