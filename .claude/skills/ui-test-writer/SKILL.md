---
name: ui-test-writer
description: This skill should be used when the user asks to "write a UI test", "add a page object", "fix a flaky Playwright test", "update a locator", or changes files under tests/ui in krci-autotests.
---

# UI test writer

CLAUDE.md holds the hard rules (markers, naming, timeouts, output discipline)
and always loads — do not restate it; on conflict, CLAUDE.md wins. This skill
adds the UI workflow, Playwright rules, and pinned portal facts.

## Recipe

1. Discover before writing: `references/pageobjects.md` is the map of where
   page objects and UI fixtures live and how to list them, plus the
   add-a-test / add-a-page-object procedures. Extend before duplicating.
2. Discover selectors with the `playwright-cli` skill — never guess a locator,
   never use a browser MCP.
3. Add/extend page objects under `tests/ui/pageobjects/`, then the test under
   `tests/ui/<area>/`.
4. Run headless AND `--headed` once; both must pass with `--reruns 0`.
   Then `make lint`.

## Playwright rules

- Locators live in page objects as `@property`, never in test bodies.
- Locator priority: `get_by_role` > `get_by_label` > `get_by_text` >
  `get_by_placeholder` > CSS `.locator()` (last resort) > `.filter()`.
- Assertions via `expect()` ONLY inside page objects (`should_*` methods
  returning `self`); tests call `should_*` methods.
- No `wait_for_timeout()` — rely on auto-waiting and the single global
  `expect()` timeout knob (see `references/pageobjects.md`).
- Cluster-state assertions in mixed tests go through testkit flows, not the
  browser.

## Portal gotchas (pinned facts)

- Login: button "Use Service Account Token" → textarea `#sa-token` → button
  "Sign In" (`LoginPage` implements this). Tests do NOT log in: the
  session-scoped `_auth_state` fixture logs in once per worker and replays its
  storage state into every context — request the `overview` fixture for an
  authenticated entry point. Only the dedicated login test uses
  `anonymous_page` to exercise the login UI itself.
- react-joyride onboarding tours intercept clicks — already disabled by the
  `_disable_onboarding_tours` init-script fixture; do not remove it.
- Form fields have NO stable `name`/`id` attrs (React.useId) —
  role/label/placeholder only.
- Dependent form fields auto-fill only on change events — when keeping a
  default select value, fill dependent fields explicitly or submit silently
  no-ops.
- Kebab/action menus: Radix trigger exposes `aria-haspopup="menu"`.
