from playwright.sync_api import Locator

from tests.ui.pageobjects.base_page import BasePage


class ProjectsPage(BasePage):
    @property
    def search_input(self) -> Locator:
        return self.page.get_by_placeholder("Search projects")

    def project_row(self, name: str) -> Locator:
        """The table row whose Name cell is EXACTLY this project.

        Filtering the row by substring instead would match any project whose name
        merely contains this one — every codebase in a suite shares a prefix, so
        'at-uipj-x' would also match the row for 'at-uipj-x-2' and turn the
        assertion into a strict-mode violation or a check on the wrong row."""
        return self.page.get_by_role("row").filter(
            has=self.page.get_by_role("cell", name=name, exact=True)
        )

    def search(self, text: str) -> ProjectsPage:
        self.search_input.fill(text)
        return self

    def should_show_project(self, name: str, *, status: str = "Created") -> ProjectsPage:
        row = self.project_row(name)
        self.should_be_visible(row)
        # Exact cell match, not free text in the row: a substring search would also
        # be satisfied by any other column that happens to contain the word.
        self.should_be_visible(row.get_by_role("cell", name=status, exact=True))
        return self
