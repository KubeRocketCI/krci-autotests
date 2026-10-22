from playwright.sync_api import Locator, Page

from tests.ui.pageobjects.base_page import BasePage
from tests.ui.pageobjects.overview_page import OverviewPage

# The token field is a plaintext textarea; the id is the portal's own stable anchor.
_TOKEN_INPUT = "#sa-token"


class LoginPage(BasePage):
    def __init__(self, page: Page, portal_url: str):
        super().__init__(page)
        self.portal_url = portal_url

    @property
    def more_options_button(self) -> Locator:
        return self.page.get_by_role("button", name="More options")

    @property
    def use_token_button(self) -> Locator:
        return self.page.get_by_role("button", name="Use Service Account Token")

    @property
    def token_input(self) -> Locator:
        return self.page.locator(_TOKEN_INPUT)

    @property
    def sign_in_button(self) -> Locator:
        # Scoped to the token's form: with OIDC enabled the page has a second
        # "Sign In" button, the one that redirects to the identity provider.
        token_form = self.page.locator("form").filter(has=self.token_input)
        return token_form.get_by_role("button", name="Sign In")

    def open(self):
        self.page.goto(self.portal_url)
        return self

    def login_with_token(self, token: str) -> OverviewPage:
        self._open_token_form()
        self.token_input.fill(token)
        self.sign_in_button.click()
        overview = OverviewPage(self.page)
        # Block until the portal accepted the token: a rejected token must fail HERE
        # with a clear message, not as a confusing error later in the flow.
        overview.should_be_visible(overview.overview_nav_link)
        return overview

    def _open_token_form(self) -> None:
        """OIDC enabled: the token button sits behind "More options". OIDC disabled: it
        is shown directly, but the portal renders the OIDC layout until it has loaded
        that setting, so "More options" can vanish mid-click and the click re-resolves
        to the token button."""
        self.more_options_button.or_(self.use_token_button).click()
        if self.token_input.is_hidden():
            self.use_token_button.click()
