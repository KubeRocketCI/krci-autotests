---
name: playwright-cli
description: This skill should be used before writing or fixing any page-object locator, or when the user asks to "find a selector", "inspect the portal DOM", "debug a UI flow", or "watch a flaky interaction" in krci-autotests. Drives a browser from a bundled script — no browser MCP.
---

# Playwright selector discovery (script-based, MCP-free)

Selectors are never guessed and never taken from screenshots alone — they come
from the live DOM. This repo's rule: drive the browser from a self-contained
sync-Playwright script, never a browser MCP.

## Workflow

1. Run the bundled inspector from the repo root (so `.env` config loads). It
   logs in with the service-account token and dumps the target screen:

   ```bash
   uv run python .claude/skills/playwright-cli/scripts/inspect_portal.py <portal-path>
   ```

   Options: `--dump html` (full page source), `--screenshot /tmp/shot.png`,
   `--headed` (watch with `slow_mo=300` — use for flaky interactions).
2. For flows that need clicks between login and the target screen, copy the
   script to `/tmp`, edit the navigation section, and run the copy. The copy is
   throwaway — never commit it.
3. Read the role/text dump; choose locators by the priority order
   (role > label > text > placeholder > CSS).
4. Transfer the finding into a page-object `@property` under
   `tests/ui/pageobjects/`.

Remember the portal gotchas in the ui-test-writer skill (tours overlay,
no stable input names, dependent selects).
