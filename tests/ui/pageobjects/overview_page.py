import re

from playwright.sync_api import Locator

from tests.ui.pageobjects.base_page import BasePage
from tests.ui.pageobjects.projects_page import ProjectsPage

# The dashboard tile renders live pipeline-run counters. Matching the counter, not
# the tile's static copy, is what makes this an assertion about the PLATFORM:
# the surrounding heading and blurb render even when the data query fails.
_RUN_COUNTER = re.compile(r"\d+\s*Runs")


class OverviewPage(BasePage):
    @property
    def overview_nav_link(self) -> Locator:
        return self.page.get_by_role("link", name="Overview")

    @property
    def projects_nav_link(self) -> Locator:
        # exact: the dashboard also has a "Browse Projects" quick link
        return self.page.get_by_role("link", name="Projects", exact=True)

    @property
    def platform_dashboard_widget(self) -> Locator:
        return self.page.get_by_role("link", name="Platform Dashboard")

    @property
    def pipeline_run_counter(self) -> Locator:
        return self.platform_dashboard_widget.get_by_text(_RUN_COUNTER)

    def open_overview(self) -> OverviewPage:
        self.overview_nav_link.click()
        return self

    def open_projects(self) -> ProjectsPage:
        self.projects_nav_link.click()
        return ProjectsPage(self.page)

    def should_show_overview_widgets(self) -> OverviewPage:
        self.should_be_visible(self.platform_dashboard_widget)
        self.should_be_visible(self.pipeline_run_counter)
        return self
