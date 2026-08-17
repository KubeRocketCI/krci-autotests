"""Authenticated portal DOM inspector for selector discovery.

Run from the repo root (so .env config loads):

    uv run python .claude/skills/playwright-cli/scripts/inspect_portal.py /c/main/projects
    uv run python .claude/skills/playwright-cli/scripts/inspect_portal.py / --dump html
    uv run python .claude/skills/playwright-cli/scripts/inspect_portal.py / --headed
    uv run python .claude/skills/playwright-cli/scripts/inspect_portal.py / \
        --screenshot /tmp/shot.png

For flows that need clicks between login and the target screen, copy this file
to /tmp and edit the navigation section — never commit the copy.
"""

import argparse

from playwright.sync_api import sync_playwright

from krci_testkit.auth import portal_token, portal_url
from krci_testkit.config import load_config

ROLES = ("link", "button", "heading", "textbox", "combobox", "menuitem", "tab")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="/", help="portal path, e.g. /c/main/projects")
    parser.add_argument("--dump", choices=("roles", "html"), default="roles")
    parser.add_argument("--screenshot", metavar="FILE", help="full-page PNG path")
    parser.add_argument("--headed", action="store_true", help="watch the run (slow_mo=300)")
    args = parser.parse_args()

    cfg = load_config()
    base_url = portal_url(cfg)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, slow_mo=300 if args.headed else 0)
        ctx = browser.new_context(ignore_https_errors=cfg.browser_ignore_https_errors)
        page = ctx.new_page()
        page.goto(base_url)
        page.get_by_role("button", name="Use Service Account Token").click()
        page.locator("#sa-token").fill(portal_token(cfg))
        page.get_by_role("button", name="Sign In").click()
        page.wait_for_load_state("networkidle")

        page.goto(base_url.rstrip("/") + args.path)
        page.wait_for_load_state("networkidle")

        print(page.url)
        if args.dump == "html":
            print(page.content())
        else:
            for role in ROLES:
                for el in page.get_by_role(role).all():
                    print(role, "|", el.text_content())
        if args.screenshot:
            page.screenshot(path=args.screenshot, full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
