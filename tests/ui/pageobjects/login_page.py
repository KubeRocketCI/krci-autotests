from playwright.sync_api import Page

from tests.ui.pageobjects.base_page import BasePage
from tests.ui.pageobjects.overview_page import OverviewPage

# The token field is a plaintext textarea; the id is the portal's own stable anchor.
_TOKEN_INPUT = "#sa-token"


class LoginPage(BasePage):
    def __init__(self, page: Page, portal_url: str):
        super().__init__(page)
        self.portal_url = portal_url

    @property
    def use_token_button(self):
        return self.page.get_by_role("button", name="Use Service Account Token")

    @property
    def token_input(self):
        return self.page.locator(_TOKEN_INPUT)

    @property
    def sign_in_button(self):
        return self.page.get_by_role("button", name="Sign In")

    def open(self):
        self.page.goto(self.portal_url)
        return self

    def login_with_token(self, token: str) -> OverviewPage:
        self.use_token_button.click()
        self.token_input.fill(token)
        self.sign_in_button.click()
        overview = OverviewPage(self.page)
        # Block until the portal accepted the token: a rejected token must fail HERE
        # with a clear message, not as a confusing error later in the flow.
        overview.should_be_visible(overview.overview_nav_link)
        return overview
