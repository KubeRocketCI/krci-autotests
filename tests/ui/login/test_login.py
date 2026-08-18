import pytest
from playwright.sync_api import Page

from krci_testkit.auth import portal_token, portal_url
from krci_testkit.config import KrciConfig
from tests.ui.pageobjects.login_page import LoginPage


@pytest.mark.ui
def test_token_login_opens_overview(anonymous_page: Page, cfg: KrciConfig):
    """The ServiceAccount-token login flow grants portal access.

    Given an unauthenticated browser context (no shared session state)
    When  the user signs in through the token dialog
    Then  the Overview page renders its widget tiles (the token was accepted)

    The ONLY test that exercises the login UI: every other UI test starts from
    the shared per-worker storage state and never sees the login page.

    Not asserted: widget content vs cluster state; session persistence across
    contexts (implicitly covered by every storage-state-based UI test).
    """
    overview = LoginPage(anonymous_page, portal_url(cfg)).open().login_with_token(portal_token(cfg))
    overview.should_show_overview_widgets()
