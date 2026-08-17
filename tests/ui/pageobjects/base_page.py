from playwright.sync_api import Locator, Page, expect


class BasePage:
    def __init__(self, page: Page):
        self.page = page

    def should_be_visible(self, locator: Locator):
        expect(locator).to_be_visible()
        return self
