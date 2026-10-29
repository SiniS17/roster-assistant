"""Browser smoke test for the phone layout (optional: needs `pip install playwright` and a Chromium).

Starts the real Flask app on the mock squads, opens it at 390x780 with touch, and checks: no sideways
page scroll (roster and Daily Distribution), Edit mode / Log in live in the side menu, a tap opens the
bottom-sheet editor, 'Select more cells...' + a second tap selects a block, the block can be staged, and the
desktop layout still hides the phone-only items. Screenshots go to $SHOTS (default: the temp dir).

Run:  python tests/browser_mobile.py
Chromium: playwright's own (`playwright install chromium`), or set CHROMIUM_PATH to an installed binary.
"""

import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openpyxl  # noqa: E402

TMP = tempfile.mkdtemp()
USERS = os.path.join(TMP, "users.xlsx")
_wb = openpyxl.Workbook()
_wb.active.append(["Name", "ID", "Password"])
_wb.active.append(["Test User", "VAE00001", "pw"])
_wb.save(USERS)
os.environ["AUTH_USERS_FILE"] = USERS  # before auth is imported

from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import app as web  # noqa: E402
import khdt_review  # noqa: E402
import test_distribution as td  # noqa: E402
import test_khdt_review as t  # noqa: E402

SHOTS = os.environ.get("SHOTS") or TMP


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        check.failed = True


check.failed = False


def main():
    sources, _ = t.setup()
    sources[0].grids["1"] = td.squad1_day(1)  # a populated Squad 1 day tab for the Daily page
    khdt_review.write_roster_updates = lambda *a, **k: None
    server = make_server("127.0.0.1", 0, web.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    launch = {"args": ["--no-sandbox"]}
    if os.environ.get("CHROMIUM_PATH"):
        launch["executable_path"] = os.environ["CHROMIUM_PATH"]

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        ctx = browser.new_context(viewport={"width": 390, "height": 780}, device_scale_factor=2, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_selector("table")
        wide = lambda: page.evaluate("document.documentElement.scrollWidth") <= 390  # noqa: E731
        check(wide(), "roster: no sideways page scroll")
        check(page.locator("#loginBtn").is_hidden() and page.locator("#editBtn").is_hidden(), "login/edit buttons are not in the top bar")
        page.screenshot(path=os.path.join(SHOTS, "m_roster.png"))

        page.tap("#menuBtn")
        check(page.locator("#navLogin").is_visible() and page.locator("#navEdit").is_hidden(), "menu: Log in shown, Edit mode hidden while logged out")
        page.tap("#navLogin")
        page.wait_for_selector("#loginDlg[open]")
        page.fill("#lgUser", "VAE00001")
        page.fill("#lgPass", "pw")
        page.tap("#lgGo")
        page.wait_for_function("document.getElementById('navLogin').textContent.indexOf('Log out') < 0 || window.AUTH.user")
        page.tap("#menuBtn")
        check(page.locator("#navEdit").is_visible() and "Log out" in page.inner_text("#navLogin"), "menu: Edit mode + Log out after login")
        page.tap("#navEdit")
        page.wait_for_selector("body.editing")

        cells = page.locator("td.day[data-e]:not([data-lck])")
        cells.nth(0).tap()
        page.wait_for_selector("#edpop:not([hidden])")
        box = page.locator("#edpop").bounding_box()
        check(box["y"] + box["height"] > 700, "editor opens as a bottom sheet")
        check(page.locator("#edpop [data-ed=extend]").is_visible(), "'Select more cells...' is offered")
        page.screenshot(path=os.path.join(SHOTS, "m_editor.png"))
        page.tap("#edpop [data-ed=extend]")
        check(page.locator("#edpop").is_hidden() and "last cell" in page.inner_text("#editbar"), "extend: sheet hides, bar asks for the last cell")
        cells.nth(5).tap()
        page.wait_for_selector("#edpop:not([hidden])")
        check(page.locator("td.sel").count() >= 4, f"a block is selected ({page.locator('td.sel').count()} cells)")
        page.fill("#edCode", "A864-34")
        page.tap("#edpop [data-ed=code]")
        check(page.locator(".stg").count() >= 4 and "staged" in page.inner_text("#editbar"), "block staged, edit bar sits under the table")
        bar = page.locator("#editbar").bounding_box()
        check(bar["y"] > page.locator("#wrap").bounding_box()["y"], "edit bar is below the table")
        page.screenshot(path=os.path.join(SHOTS, "m_staged.png"))

        page.tap("#menuBtn")
        page.tap("#navDist")
        page.wait_for_selector("table.dt")
        check(wide(), "Daily Distribution: no sideways page scroll")
        check(page.locator("table.dt th.c-id").first.is_hidden() and page.locator("table.dt a.tel").count() >= 1, "Daily: ORD/ID/POS columns hidden, phones are tel: links")
        page.screenshot(path=os.path.join(SHOTS, "m_daily.png"))
        check(not errors, f"no page errors {errors}")

        desk = browser.new_context(viewport={"width": 1400, "height": 800}).new_page()
        desk.goto(url)
        desk.wait_for_selector("table")
        check(desk.locator("#navEdit").is_hidden() and desk.locator("#sub").is_visible(), "desktop: phone-only menu items hidden, layout unchanged")
        browser.close()
    server.shutdown()
    print("screenshots in", SHOTS)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
