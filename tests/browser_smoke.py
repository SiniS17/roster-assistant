"""Browser smoke test for the KHDT review flow (optional: needs `pip install playwright && playwright install chromium`).

Starts the real Flask app on a free port with the mock squads of the unit tests, then drives Chromium:
run a KHDT file -> highlighted cells -> keep/reject (popover + list) -> reload keeps the decisions for this
browser only -> a second browser context sees nothing -> export writes only the kept cells -> the review empties.

Run:  python tests/browser_smoke.py
"""

import copy
import io
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openpyxl  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

import app as web  # noqa: E402
import khdt_review  # noqa: E402
import test_khdt_review as t  # noqa: E402


def khdt_xlsx(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["STT", "Mã NV", "Họ tên", "Phòng/Đội", "Tên KĐT", "Mã lớp học", "Bắt đầu", "Kết thúc", "Lí do"])
    # KHDT dates are YYYY-DD-MM: '2026-01-10' = 1 Oct ... '2026-04-10' = 4 Oct.
    ws.append([1, "VAE07777", "Test Bốn", "D4", "An toàn hàng không", "ATHK/2610/01", "2026-01-10", "2026-04-10", None])
    ws.append([2, "VAE02481", "Hứa Quang Trung", "D1", "An toàn hàng không", "ATHK/2610/01", "2026-01-10", "2026-01-10", None])
    wb.save(path)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        check.failed = True


check.failed = False


def main():
    sources, _ = t.setup()
    live = {s.id: s for s in sources if hasattr(s, "grids")}

    def fake_write(sid, gid, updates):  # act like the real sheet: the cells change
        for u in updates:
            live[sid].grids["ROSTER"][u["row"]][u["col"]] = u["value"]
        fake_write.calls.append((sid, [(u["row"], u["col"], u["value"]) for u in updates]))

    fake_write.calls = []
    khdt_review.write_roster_updates = fake_write

    import tempfile

    import auth
    users = os.path.join(tempfile.mkdtemp(), "users.xlsx")  # export needs a login
    ub = openpyxl.Workbook()
    ub.active.append(["username", "password"])
    ub.active.append(["smoke", "pw"])
    ub.save(users)
    auth.USERS_FILE = users

    server = make_server("127.0.0.1", 0, web.app, threaded=True)
    port = server.server_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    xlsx = os.path.join(os.environ.get("TMPDIR", "/tmp"), "khdt_smoke.xlsx")
    khdt_xlsx(xlsx)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1400, "height": 800})
        page = ctx.new_page()
        ctx.request.post(url + "api/login", data={"username": "smoke", "password": "pw"})  # cookie is shared with the page
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.wait_for_selector("table")
        check(page.locator(".pend").count() == 0 and page.locator("#review").is_hidden(), "plain roster: no review bar")

        page.click("#menuBtn"); page.click("#navKhdt")
        page.set_input_files("#file", xlsx)
        page.click("#runBtn")
        page.wait_for_selector("#see")
        check("changes" in page.inner_text("#out") or "highlighted" in page.inner_text("#out"), "run summary shown")
        page.click("#see")
        page.wait_for_selector(".pend")
        n_pend = page.locator(".pend").count()
        check(n_pend >= 3, f"changed cells highlighted ({n_pend} boxes)")
        check(page.locator("#review").is_visible() and "undecided" in page.inner_text("#review"), "review bar visible")
        check(page.locator(".cfl").count() >= 1, "overwrite-existing cell flagged")

        # Keep the Squad 4 course (a merged two-day box) through the popover.
        box = page.locator("tr", has_text="VAE07777").locator(".pend").first
        box.click()
        check(page.locator("#pop").is_visible() and "Test Bốn" in page.inner_text("#pop"), "popover opens")
        page.screenshot(path=os.path.join(os.environ.get("TMPDIR", "/tmp"), "khdt_review.png"))
        page.click("#pop [data-set=kept]")
        check(page.locator(".kept").count() >= 1, "cell kept")

        # Reject the conflict one through the list.
        page.click("#review [data-act=list]")
        page.fill("#revQ", "VAE02481")
        page.click("#revList [data-set=rejected]")
        page.click("#revClose")
        check(page.locator("tr", has_text="VAE02481").locator(".rej").count() >= 1, "rejected cell shown dotted")

        before = page.inner_text("#review")
        page.reload(); page.wait_for_selector("table"); page.wait_for_selector("#review:not([hidden])")
        check(page.inner_text("#review") == before, "reload keeps this browser's decisions")
        check(page.locator(".kept").count() >= 1 and page.locator(".rej").count() >= 1, "reload keeps highlights")

        other = browser.new_context().new_page()
        other.goto(url); other.wait_for_selector("table")
        check(other.locator("#review").is_hidden() and other.locator(".pend,.kept,.rej").count() == 0,
              "another browser/profile sees an untouched roster")

        # Export: only the kept cells reach the sheet.
        page.click("#review [data-act=keepAll]")
        page.click("#review [data-act=rejectAll]") if page.locator("#review [data-act=rejectAll]:not([disabled])").count() else None
        page.click("#review [data-act=export]")
        page.click("#expGo")
        page.wait_for_selector(".okline")
        written = {sid: calls for sid, calls in fake_write.calls}
        check(set(written) == {"sq4"}, f"only Squad 4 (the kept squad) was written: {sorted(written)}")
        check(all(v == "H ATHK" or v == "N" for _, _, v in written.get("sq4", [])), "written values are the proposed ones")
        page.click("#expDone")
        page.wait_for_selector("table")
        check(page.locator(".kept").count() == 0 and page.locator(".pend").count() == 0, "exported cells leave the review")
        check(page.locator("tr", has_text="VAE02481").locator(".rej").count() >= 1, "rejected change is still there, untouched")
        check(not errors, f"no page errors {errors}")
        page.screenshot(path=os.path.join(os.environ.get("TMPDIR", "/tmp"), "khdt_smoke.png"))
        browser.close()
    server.shutdown()
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
