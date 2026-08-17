# Discovery map (UI tests)

Do not trust a catalog — catalogs drift. The code is the source of truth. This
map says what to discover, when, and where.

## When and where to look

| Before... | Discover in | How |
|---|---|---|
| adding/extending a page object | `tests/ui/pageobjects/*.py` | read the class: locators are `@property`, assertions are `should_*` methods returning `self`, navigation returns the next page object |
| using a fixture | `tests/ui/conftest.py` (short — read the whole file) | `uv run pytest --fixtures tests/ui -q` prints fixtures with docstrings |
| choosing an entry point | the `overview` fixture | the normal authenticated start; chain into pages (`overview.open_projects()`) |
| writing any locator | the running portal | use the `playwright-cli` skill — never guess |

## Facts no single file states (keep pinned)

- There is NO login fixture and tests never see the login page: the session
  `_auth_state` fixture logs in once per xdist worker; every context replays its
  storage state. Only `tests/ui/login/test_login.py` drives the login UI, via
  `anonymous_page`.
- `expect()` timeout is set ONCE globally from the `krci_timeout_ui_expect`
  knob; page objects and `should_*` methods never take or pass a timeout. If an
  element genuinely needs longer, raise the knob for the run.
- Screenshot-on-failure is a `pytest_runtest_makereport` hook in
  `tests/ui/conftest.py`, not a fixture.
- Shared components go under `tests/ui/pageobjects/components/` when they
  appear.

# Adding a UI test

1. Seed the subject through the API, never through portal forms — request the
   `owned_codebase` factory (root conftest) from a fixture in the suite's own
   conftest, e.g. `tests/ui/projects/conftest.py`.
2. Take `overview` and chain into the page you need.
3. Annotate the fixture parameters (`overview: OverviewPage`,
   `codebase: Codebase`). Without annotations the test body is `Any` and
   pyright checks nothing in it.
4. Mark it `@pytest.mark.ui` (plus `smoke` if it belongs to the fast suite).

# Adding a page object

- Subclass `BasePage`, expose locators as `@property`, keep methods returning
  `self` or the next page object (chaining).
- Prefer role-based locators over CSS. A CSS selector needs a comment naming
  the portal's stable anchor (see `_TOKEN_INPUT` in `login_page.py`).
- Assertions belong in `should_*` methods so tests read as intent, not as
  locators.
