import json
import logging
import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from krci_testkit.auth import portal_token, portal_url
from krci_testkit.config import KrciConfig
from krci_testkit.waits import Timeouts
from tests.ui.pageobjects.login_page import LoginPage
from tests.ui.pageobjects.overview_page import OverviewPage

log = logging.getLogger(__name__)

# react-joyride tours intercept pointer events; mark them completed before first paint.
_TOURS = ("welcome_tour", "pinned_items_intro", "form_guide_intro", "page_guide_intro")


def _tours_init_script() -> str:
    now_ms = int(time.time() * 1000)
    payload = {
        "schemaVersion": 1,
        "firstVisit": "1970-01-01T00:00:00.000Z",
        "tours": {
            t: {"completedAt": now_ms, "version": "0.0.0", "completed": True} for t in _TOURS
        },
    }
    return f"window.localStorage.setItem('portal_tours', JSON.stringify({json.dumps(payload)}))"


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict, cfg: KrciConfig) -> dict:
    """Make KRCI_CA_BUNDLE reach the browser too.

    Chromium's node host reads NODE_EXTRA_CA_CERTS at launch — there is no
    per-context CA option — so a self-signed environment configured with a bundle
    was verified by the API layer (httpx_verify) but not by the UI layer."""
    if cfg.ca_bundle:
        os.environ.setdefault("NODE_EXTRA_CA_CERTS", str(cfg.ca_bundle))
    return browser_type_launch_args


@pytest.fixture(scope="session", autouse=True)
def _expect_timeout(timeouts: Timeouts) -> None:
    # One global default feeds every expect() — page objects carry no numbers.
    expect.set_options(timeout=timeouts.ui_expect * 1000)


@pytest.fixture(scope="session")
def _auth_state(browser: Browser, cfg: KrciConfig, tmp_path_factory: pytest.TempPathFactory):
    """ONE real token login per session (per xdist worker); its storage state is
    replayed into every test context so tests start authenticated and never see
    the login page. The state file holds the session token: tmp_path_factory
    keeps it worker-unique and outside the repo. The login UI itself stays
    covered by the dedicated login test (anonymous_page)."""
    context = browser.new_context(ignore_https_errors=cfg.browser_ignore_https_errors)
    context.add_init_script(_tours_init_script())
    page = context.new_page()
    LoginPage(page, portal_url(cfg)).open().login_with_token(portal_token(cfg))
    path = tmp_path_factory.mktemp("auth") / "portal-state.json"
    context.storage_state(path=str(path))
    context.close()
    log.info("portal session state captured for this worker")
    return path


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict, cfg: KrciConfig, _auth_state: Path) -> dict:
    return {
        **browser_context_args,
        "ignore_https_errors": cfg.browser_ignore_https_errors,
        "viewport": {"width": 1600, "height": 1000},
        "storage_state": str(_auth_state),
    }


@pytest.fixture(autouse=True)
def _disable_onboarding_tours(context: BrowserContext) -> None:
    context.add_init_script(_tours_init_script())


@pytest.fixture
def overview(_disable_onboarding_tours: None, page: Page, cfg: KrciConfig) -> OverviewPage:
    """Authenticated Overview entry point — pre-seeded session state, no login UI.

    The tour suppression is requested EXPLICITLY, not left to autouse ordering: its
    init script only applies to navigations that come after it, and a tour that
    slips through does not fail here — it silently intercepts pointer events and
    surfaces as an unrelated flaky click somewhere downstream."""
    page.goto(portal_url(cfg))
    overview_page = OverviewPage(page)
    overview_page.should_be_visible(overview_page.overview_nav_link)
    return overview_page


@pytest.fixture
def anonymous_page(browser: Browser, cfg: KrciConfig):
    """A context WITHOUT the shared auth state — only the login test uses it."""
    context = browser.new_context(ignore_https_errors=cfg.browser_ignore_https_errors)
    context.add_init_script(_tours_init_script())
    page = context.new_page()
    yield page
    context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    """Attach a screenshot of EVERY page the failing test actually drove.

    Done in the report hook rather than an autouse fixture for two reasons. A
    fixture would have to name one page fixture, and it would name the wrong one:
    the login test drives `anonymous_page`, so a fixture bound to `page` both
    screenshots an untouched context AND forces every test to build a second,
    unused authenticated one. The hook runs before any fixture teardown, so every
    page the test opened is still live here.

    Unmasked by choice: the SA token renders only in the dedicated login test,
    a viewport never shows the huge JWT in full, and the target env is isolated
    — revisit if a shared-identity flow (e.g. Keycloak) arrives.
    """
    outcome = yield
    report = outcome.get_result()
    if call.when != "call" or not report.failed:
        return
    for fixture_name, page in _live_pages(item):
        # pytest-reportportal picks attachments up from the logging bridge.
        log.info(
            "screenshot on failure: %s (%s)",
            item.name,
            fixture_name,
            extra={
                "attachment": {
                    "name": f"{item.name}-{fixture_name}.png",
                    "data": page.screenshot(full_page=True),
                    "mime": "image/png",
                }
            },
        )


def _live_pages(item: pytest.Item) -> list[tuple[str, Page]]:
    """Every still-open Page the test instantiated, by fixture name."""
    funcargs: dict = getattr(item, "funcargs", {})
    return [
        (name, value)
        for name, value in funcargs.items()
        if isinstance(value, Page) and not value.is_closed()
    ]
