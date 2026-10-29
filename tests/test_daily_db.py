"""Database-style day tabs (Phase 4): the format 'A123-OCT29' = Name | VAEID | Function | Zone | remark.

Run:  python tests/test_daily_db.py        (or: pytest tests)

Mock squads only (the Squad 1 / Squad 2 grids of test_assignments.py), nothing touches Google: the writers
are replaced by recorders.
"""

import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import openpyxl  # noqa: E402
import pytest  # noqa: E402

import assignments as a  # noqa: E402
import auth  # noqa: E402
import daily_db  # noqa: E402
import distribution as dist  # noqa: E402
import khdt_review  # noqa: E402
import test_assignments as ta  # noqa: E402

N = None
HEAD = ["Name", "VAEID", "Function", "Zone", "remark"]


@pytest.fixture(autouse=True)
def _database_format():
    before = a.DAILY_WRITE_FORMAT
    a.DAILY_WRITE_FORMAT = "database"
    yield
    a.DAILY_WRITE_FORMAT = before


def db_tab():
    return [HEAD,
            ["Hồ Sĩ Út", "VAE02854", "B1", "A864-128", N],
            ["Đào Việt Hải", "VAE00708", "B1", "A864-128", "late"],
            ["Lê Văn Bảy", "VAE07777", "B2", "A864-567", N]]


def ctx_with(extra_tabs=None, index=0):
    """Squad 1 mock (hand-made tabs '1'..'3' for Oct 1-3) plus optional database tabs."""
    tabs = {"1": ta.day1(), "2": ta.day1(), "3": ta.day1()}
    days = [{"tab": t, "ac": "", "date": f"2026-10-{int(t):02d}"} for t in tabs]
    for t, grid in (extra_tabs or {}).items():
        tabs[t] = grid
        d = daily_db.date_of(t, date(2026, 10, 1))
        days.append({"tab": t, "ac": t.split("-")[0], "date": d.isoformat()})
    ctx = a.make_context(index, ta.make_sq(ta.ROSTER1, ta.COLORS1), days, lambda tab: dist._rect(tabs[tab], []), {})
    return ctx, tabs


def intent(origin="roster", **kw):
    return ta.intent(origin, **kw)


def cells(writes):
    return {(w["tab"], w["a1"]): (w["old"], w["new"]) for w in writes}


# ----------------------------------------------------------------- the format and its reader
def test_tab_name_follows_the_existing_pattern():
    assert daily_db.tab_name("a123", date(2026, 10, 29)) == "A123-OCT29"
    assert daily_db.tab_name("A611", date(2026, 10, 6)) == "A611-OCT06"
    assert dist.parse_tab_name("A123-OCT29", date(2026, 10, 1)) == ("A123", date(2026, 10, 29))
    with pytest.raises(ValueError):
        daily_db.tab_name("", date(2026, 10, 1))


def test_header_detection_never_takes_a_hand_made_tab_for_this_format():
    assert daily_db.header_map(HEAD) == {"name": 0, "id": 1, "pos": 2, "zone": 3, "remark": 4}
    assert daily_db.header_map(["vaeid", "NAME", "zone", "function"]) == {"id": 0, "name": 1, "zone": 2, "pos": 3}
    assert daily_db.header_map(["ORD", "NAME AND SURNAME", "ID", "POSITION", "REMARK"]) is None
    assert daily_db.read_grid(ta.day1()) is None and daily_db.read_grid([]) is None


def test_reader_gives_records_and_the_sections_the_daily_page_expects():
    db = daily_db.read_grid(db_tab())
    assert [(r["id"], r["pos"], r["zone"], r["remark"]) for r in db["records"]] == [
        ("VAE02854", "B1", "A864-128", ""), ("VAE00708", "B1", "A864-128", "late"), ("VAE07777", "B2", "A864-567", "")]
    values, colors = dist._rect(db_tab(), [])
    secs = dist.parse_day(values, colors, {"VAE02854": "0900000001"})  # parse_day reads the new format
    assert [(s["title"], s["kind"], [p["id"] for p in s["people"]]) for s in secs] == [
        ("A864-128", "zone", ["VAE02854", "VAE00708"]), ("A864-567", "zone", ["VAE07777"])]
    first = secs[0]["people"][0]
    assert first["pos"] == "B1" and first["phone"] == "0900000001" and first["ord"] == 1
    assert secs[0]["people"][1]["remark"] == "late"


def test_people_without_a_zone_are_listed_as_unassigned_and_hand_made_tabs_still_parse():
    grid = [HEAD, ["Người Mới", "VAE05555", N, N, N], ["Khác", "VAE00001", "x", "ZONE 128", N]]
    secs = dist.parse_day(*dist._rect(grid, []))
    assert [(s["title"], s["kind"]) for s in secs] == [("UNASSIGNED", "other"), ("ZONE 128", "zone")]
    legacy = dist.parse_day(*dist._rect(ta.day1(), []))
    assert [s["title"] for s in legacy] == ["A864-128", "A864-567", "A864-34"]


def test_a_new_tab_is_listed_as_a_day_of_its_date_and_read_through_build_day_helpers():
    secs = dist.parse_day(*dist._rect(db_tab(), []))
    assert sum(len(s["people"]) for s in secs) == 3
    info, _book, _warn = dist.parse_info(dist._rect(db_tab(), [])[0])  # build_day also runs this on the tab
    assert info["people"] == {}


# ----------------------------------------------------------------- roster edit -> new tab
def test_a_roster_edit_creates_the_tab_with_function_and_zone():
    ctx, _ = ctx_with()
    # Hồ Sĩ Út (VAE02854) is on hand-made tab '2' as B1; Oct 2 changes from A864-128 to A864-34
    p = a.plan_link(ctx, intent(id="VAE02854", kind="code", value="A864-34"))
    assert p["status"] == "ok" and p["blocked"] is None
    assert p["create_tabs"] == [{"tab": "A864-OCT02", "date": "2026-10-02", "ac": "A864"}]
    assert cells(p["day"]) == {("A864-OCT02", "A2"): ("", "Hồ Sĩ Út"), ("A864-OCT02", "B2"): ("", "VAE02854"),
                               ("A864-OCT02", "C2"): ("", "B1"), ("A864-OCT02", "D2"): ("", "A864-34")}
    assert ta.by_a1(p["roster"]) == {("ROSTER", "E3"): ("A864-128", "A864-34")}
    assert not any(w["tab"] in ("1", "2", "3") for w in p["day"])  # hand-made tabs are never written


def test_the_example_from_the_request_a123_oct29():
    grid = ta.ROSTER1 + []
    roster = [r[:] for r in grid]
    roster[0] = ["NO", "NAME & SURNAME", "ID"] + [ta.serial(n) for n in (28, 29, 30)]
    roster[1:] = [[1, "Trần Hoàng Nhung", "VAE02591", N, N, N], [2, "Hồ Sĩ Út", "VAE02854", N, N, N]]
    ctx = a.make_context(0, ta.make_sq(roster), [], lambda tab: [[]], {})
    p = a.plan_link(ctx, intent(id="VAE02591", date="2026-10-29", kind="code", value="A123"))
    assert p["status"] == "ok"
    assert [t["tab"] for t in p["create_tabs"]] == ["A123-OCT29"]
    assert cells(p["day"]) == {("A123-OCT29", "A2"): ("", "Trần Hoàng Nhung"), ("A123-OCT29", "B2"): ("", "VAE02591")}
    # a code without a zone leaves Zone empty, and the function is unknown, so both cells stay empty
    # the next person of the same batch goes to the next row
    p2 = a.plan_link(ctx, intent(id="VAE02854", date="2026-10-29", kind="code", value="A123"))
    assert cells(p2["day"]) == {("A123-OCT29", "A3"): ("", "Hồ Sĩ Út"), ("A123-OCT29", "B3"): ("", "VAE02854")}
    assert p2["create_tabs"] == []  # the batch already knows the tab


def test_a_person_already_on_the_tab_keeps_function_and_remark_and_only_the_zone_changes():
    ctx, _ = ctx_with({"A864-OCT02": db_tab()})
    p = a.plan_link(ctx, intent(id="VAE02854", kind="code", value="A864-34"))
    assert p["create_tabs"] == [] and cells(p["day"]) == {("A864-OCT02", "D2"): ("A864-128", "A864-34")}
    same = a.plan_link(ctx, intent(id="VAE00708", kind="code", value="A864-128"))
    assert same["day"] == [] and same["roster"] == [] and same["status"] == "noop"  # already listed in that zone


def test_normal_n_removes_the_person_and_the_rows_below_move_up():
    ctx, _ = ctx_with({"A864-OCT02": db_tab()})
    p = a.plan_link(ctx, intent(id="VAE02854", kind="n"))
    assert p["status"] == "ok"
    assert cells(p["day"]) == {
        ("A864-OCT02", "A2"): ("Hồ Sĩ Út", "Đào Việt Hải"), ("A864-OCT02", "B2"): ("VAE02854", "VAE00708"),
        ("A864-OCT02", "E2"): ("", "late"),
        ("A864-OCT02", "A3"): ("Đào Việt Hải", "Lê Văn Bảy"), ("A864-OCT02", "B3"): ("VAE00708", "VAE07777"),
        ("A864-OCT02", "C3"): ("B1", "B2"), ("A864-OCT02", "D3"): ("A864-128", "A864-567"),
        ("A864-OCT02", "E3"): ("late", ""),
        ("A864-OCT02", "A4"): ("Lê Văn Bảy", ""), ("A864-OCT02", "B4"): ("VAE07777", ""),
        ("A864-OCT02", "C4"): ("B2", ""), ("A864-OCT02", "D4"): ("A864-567", "")}
    assert a.plan_link(ctx, intent(id="VAE02854", kind="n"))["status"] in ("noop", "blocked")  # batch saw it gone


def test_changing_the_aircraft_moves_the_person_between_tabs():
    other = [HEAD, ["Hồ Sĩ Út", "VAE02854", "B1", "A611-ZONE 128", N]]
    ctx, _ = ctx_with({"A864-OCT02": db_tab(), "A611-OCT02": other})
    p = a.plan_link(ctx, intent(id="VAE07777", kind="code", value="A611"))
    assert p["status"] == "ok"
    new = {k: v for k, v in cells(p["day"]).items() if k[0] == "A611-OCT02"}
    assert new == {("A611-OCT02", "A3"): ("", "Lê Văn Bảy"), ("A611-OCT02", "B3"): ("", "VAE07777"),
                   ("A611-OCT02", "C3"): ("", "B2")}  # function carried over from the tab he left
    assert cells(p["day"])[("A864-OCT02", "B4")] == ("VAE07777", "")  # and he is gone from the old tab


def test_a_hand_made_tab_with_the_same_name_is_left_alone():
    ctx, _ = ctx_with({"A864-OCT02": ta.day1()})  # exists, but in the hand-made layout
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-567"))
    assert p["status"] == "roster_only" and p["day"] == [] and p["roster"]
    assert "hand-made layout" in p["day_skipped"]


def test_other_codes_are_not_linked_and_locked_cells_still_block():
    ctx, _ = ctx_with({"A864-OCT02": db_tab()})
    assert a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-FM"))["day"] == []
    blocked = a.plan_link(ctx, intent(id="VAE02379", kind="code", value="A864-34", date="2026-10-03"))
    assert blocked["status"] == "blocked" and "red N" in blocked["blocked"]


# ----------------------------------------------------------------- daily page -> db tab
def test_daily_move_between_zones_sets_the_zone_and_the_roster_code():
    ctx, _ = ctx_with({"A864-OCT02": db_tab()})
    p = a.plan_link(ctx, intent("daily", id="VAE02854", tab="A864-OCT02", to="A864-34"))
    assert p["status"] == "ok"
    assert cells(p["day"]) == {("A864-OCT02", "D2"): ("A864-128", "A864-34")}
    assert ta.by_a1(p["roster"]) == {("ROSTER", "E3"): ("A864-128", "A864-34")}


def test_daily_move_to_unassigned_clears_the_zone_and_taking_out_removes_the_row():
    ctx, _ = ctx_with({"A864-OCT02": db_tab()})
    p = a.plan_link(ctx, intent("daily", id="VAE02854", tab="A864-OCT02", to="UNASSIGNED"))
    assert cells(p["day"]) == {("A864-OCT02", "D2"): ("A864-128", "")}
    out = a.plan_link(ctx, intent("daily", id="VAE00708", tab="A864-OCT02", to=None))
    assert out["status"] == "ok" and out["roster"] == [] and any("left as it is" in n for n in out["notes"])


def test_daily_edit_of_a_hand_made_tab_is_refused_in_database_mode():
    ctx, _ = ctx_with()
    p = a.plan_link(ctx, intent("daily", id="VAE02854", tab="2", to="A864-34"))
    assert p["status"] == "blocked" and "hand-made day tab" in p["blocked"]


# ----------------------------------------------------------------- commit
class Recorder:
    def __init__(self, fail_day=False):
        self.calls, self.fail_day = [], fail_day

    def install(self, ctx):
        src = SimpleNamespace(id="SHEET1", kind="sheets")
        ctx["sq"]["src"] = src
        self.real = (a.load_context, a.sheets_client.write_roster_updates, a.sheets_client.add_sheet,
                     a.sheets_client.write_cells, khdt_review._tab_gid, auth.can_edit)
        a.load_context = lambda index, force=True: ctx
        a.sheets_client.write_roster_updates = lambda sid, gid, ups: self.calls.append(("roster", sid, gid, len(ups)))
        a.sheets_client.add_sheet = lambda sid, title, header: self.calls.append(("add_sheet", sid, title, tuple(header)))
        a.sheets_client.write_cells = self._cells
        khdt_review._tab_gid = lambda sid, title: 7
        auth.can_edit = lambda user, squad: True
        return self

    def _cells(self, sid, title, cells_):
        if self.fail_day:
            raise RuntimeError("quota")
        self.calls.append(("cells", sid, title, sorted((c["row"], c["col"], c["value"]) for c in cells_)))

    def restore(self):
        (a.load_context, a.sheets_client.write_roster_updates, a.sheets_client.add_sheet,
         a.sheets_client.write_cells, khdt_review._tab_gid, auth.can_edit) = self.real


def test_commit_writes_the_roster_first_then_creates_the_tab_then_fills_it():
    ctx, _ = ctx_with()
    rec = Recorder().install(ctx)
    try:
        res = a.commit([intent(id="VAE02854", kind="code", value="A864-34"),
                        intent(id="VAE05555", kind="code", value="A864-34")], "tester")
    finally:
        rec.restore()
    assert [c[0] for c in rec.calls] == ["roster", "add_sheet", "cells"]
    assert rec.calls[1][2:] == ("A864-OCT02", tuple(HEAD))
    assert rec.calls[2][2:] == ("A864-OCT02", [(1, 0, "Hồ Sĩ Út"), (1, 1, "VAE02854"), (1, 2, "B1"), (1, 3, "A864-34"),
                                               (2, 0, "Người Mới"), (2, 1, "VAE05555"), (2, 3, "A864-34")])
    s = res["squads"][0]
    assert (s["roster_written"], s["day_written"], s["created_tabs"], s["error"], s["partial"]) == \
        (2, 7, ["A864-OCT02"], None, False)
    assert any("new tab 'A864-OCT02'" in line for line in res["lines"])


def test_commit_reports_a_partial_failure_and_does_not_hide_what_was_written():
    ctx, _ = ctx_with()
    rec = Recorder(fail_day=True).install(ctx)
    try:
        res = a.commit([intent(id="VAE02854", kind="code", value="A864-34")], "tester")
    finally:
        rec.restore()
    s = res["squads"][0]
    assert s["partial"] is True and "quota" in s["error"] and s["roster_written"] == 1 and s["created_tabs"] == ["A864-OCT02"]


def test_commit_skips_blocked_intents_and_writes_nothing_for_them():
    ctx, _ = ctx_with()
    rec = Recorder().install(ctx)
    try:
        res = a.commit([intent(id="VAE02379", kind="code", value="A864-34", date="2026-10-03")], "tester")
    finally:
        rec.restore()
    assert rec.calls == [] and res["plans"][0]["status"] == "blocked" and res["squads"][0]["error"] is None


def test_commit_refuses_the_hand_made_layout_and_an_uploaded_xlsx():
    ctx, _ = ctx_with()
    rec = Recorder().install(ctx)
    try:
        a.DAILY_WRITE_FORMAT = "legacy"
        res = a.commit([intent(id="VAE05555", kind="code", value="A864-567")], "tester")
        assert "database day-tab format" in res["squads"][0]["error"] and rec.calls == []
        a.DAILY_WRITE_FORMAT = "database"
        ctx["sq"]["src"] = SimpleNamespace(id="X", kind="xlsx")
        res = a.commit([intent(id="VAE05555", kind="code", value="A864-567")], "tester")
        assert "uploaded Excel" in res["squads"][0]["error"] and rec.calls == []
    finally:
        rec.restore()


def test_a_tab_created_by_somebody_else_meanwhile_is_not_written_to():
    ctx, _ = ctx_with()
    rec = Recorder().install(ctx)

    def exists(sid, title, header):
        raise a.sheets_client.TabExists(title)

    a.sheets_client.add_sheet = exists
    try:
        res = a.commit([intent(id="VAE02854", kind="code", value="A864-34")], "tester")
    finally:
        rec.restore()
    s = res["squads"][0]
    assert "created by somebody else" in s["error"] and s["day_written"] == 0 and s["roster_written"] == 1
    assert not [c for c in rec.calls if c[0] == "cells"]


def test_sheets_client_builds_the_expected_requests():
    import sheets_client as sc

    class Exec:
        def __init__(self, out=None):
            self.out = out

        def execute(self):
            return self.out

    log = []

    class Values:
        def update(self, **kw):
            log.append(("update", kw["range"], kw["body"]["values"]))
            return Exec()

        def batchUpdate(self, **kw):
            log.append(("values.batch", [d["range"] for d in kw["body"]["data"]]))
            return Exec()

    class Sheets:
        def batchUpdate(self, **kw):
            log.append(("batch", [list(r)[0] for r in kw["body"]["requests"]]))
            return Exec({"replies": [{"addSheet": {"properties": {"sheetId": 99}}}]})

        def values(self):
            return Values()

    class Svc:
        def spreadsheets(self):
            return Sheets()

    real = sc.get_service
    sc.get_service = lambda: Svc()
    try:
        assert sc.add_sheet("S", "A123-OCT29", HEAD) == 99
        sc.write_cells("S", "A123-OCT29", [{"row": 1, "col": 0, "value": "x"}, {"row": 27, "col": 3, "value": ""}])
    finally:
        sc.get_service = real
    assert log == [("batch", ["addSheet"]), ("update", "'A123-OCT29'!A1:E1", [HEAD]), ("batch", ["repeatCell"]),
                   ("values.batch", ["'A123-OCT29'!A2", "'A123-OCT29'!D28"])]


def test_route_needs_a_login_and_commits_through_assignments():
    import app as web

    seen = []
    real = a.commit
    a.commit = lambda intents, user: seen.append((intents, user)) or {"plans": [], "squads": [], "lines": []}
    try:
        c = web.app.test_client()
        body = {"intents": [intent(id="VAE05555", kind="n")]}
        assert c.post("/api/link/save", json=body).status_code == 401
        users = os.path.join(tempfile.mkdtemp(), "users.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["username", "password"])
        wb.active.append(["tester", "pw"])
        wb.save(users)
        auth.USERS_FILE = users
        auth._cache.update(key=None, users={})
        assert c.post("/api/login", json={"username": "tester", "password": "pw"}).status_code == 200
        assert c.post("/api/link/save", json=body).get_json()["ok"] is True and len(seen) == 1
        assert c.post("/api/link/save", json={"intents": []}).status_code == 400
    finally:
        a.commit = real


if __name__ == "__main__":
    a.DAILY_WRITE_FORMAT = "database"
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL ", name, "->", type(e).__name__, e)
    sys.exit(1 if failed else 0)
