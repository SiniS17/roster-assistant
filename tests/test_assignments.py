"""Roster <-> Daily Distribution link tests (Phase 3, dry run only).

Run:  python tests/test_assignments.py        (or: pytest tests)

The grids are small mock squads laid out like the screenshot-based mocks of test_distribution.py (not the
live sheets): Squad 1 style ("zone": roster 'A864-34' <-> section 'A864-34', two tables side by side) and
Squad 2 style ("aircraft": roster 'A611', tab 'A611-OCT02' with 'ZONE 128'). Nothing touches Google, and
every test also proves that no writer is ever called.
"""

import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import openpyxl  # noqa: E402

import assignments as a  # noqa: E402
import auth  # noqa: E402
import distribution as dist  # noqa: E402
import khdt_review  # noqa: E402
import roster_edit  # noqa: E402
from engine import find_roster_header_grid  # noqa: E402
from squad_roster import own_rows_cutoff  # noqa: E402

N = None


def serial(dd, m=10):
    return (date(2026, m, dd) - date(1899, 12, 30)).days


def forbid_writes():
    def boom(*args, **kw):
        raise AssertionError("a dry run must never write to Google")

    roster_edit.write_roster_updates = boom
    khdt_review.write_roster_updates = boom


def make_sq(values, colors=None):
    values, colors = dist._rect(values, colors or [])
    header_row, id_col, name_col, date_cols = find_roster_header_grid(values, lenient=True)
    return {"values": values, "colors": colors, "header_row": header_row, "id_col": id_col, "name_col": name_col,
            "date_cols": date_cols, "cutoff": own_rows_cutoff(values, header_row), "title": "ROSTER", "src": None}


def ctx_for(index, sq, tabs, days, phones=None):
    forbid_writes()
    return a.make_context(index, sq, days, lambda tab: dist._rect(tabs[tab], []), phones or {})


def by_a1(writes, sheet=None):
    return {(w["tab"], w["a1"]): (w["old"], w["new"]) for w in writes if sheet in (None, w["sheet"])}


# ----------------------------------------------------------------- Squad 1 (zone layout)
# Oct 1..5 in columns 3..7
ROSTER1 = [
    ["NO", "NAME & SURNAME", "ID"] + [serial(n) for n in range(1, 6)],
    [1, "Trần Hoàng Nhung", "VAE02591", "A864-PPC", "A864-34", "A864-34", "N", "A864-128"],
    [2, "Hồ Sĩ Út", "VAE02854", "A864-128", "A864-128", "N", "A864-128", "N"],
    [3, "Đào Việt Hải", "VAE00708", "H ATHK", "A864-128", "N", N, N],
    [4, "Lộc Đức Hiền", "VAE02379", N, "A864-567", "N", N, N],     # Oct 3 is a red N (colours below)
    [5, "Người Mới", "VAE05555", N, N, N, N, N],
    [6, "Lê Văn Bảy", "VAE07777", N, "A864-567", N, N, N],
    [7, "Võ Nghỉ Phép", "VAE06666", N, "P", N, N, N],
]
COLORS1 = [[N] * 8 for _ in range(8)]
COLORS1[4][5] = "FF0000"


def day1():
    """Squad 1 day tab: info line, then two tables side by side (left cols 0-5, right cols 7-12)."""
    hdr = ["ORD", "NAME AND SURNAME", "VAECO ID", "POSITION", "PHONE", "REMARK", N,
           "ORD", "NAME AND SURNAME", "VAECO ID", "POSITION", "PHONE", "REMARK"]
    return [
        ["A/C:  A864"],
        hdr,
        [N, "A864-128", N, N, N, N, N, N, "A864-34"],
        [1, "Hồ Sĩ Út", "VAE02854", "B1", N, N, N, 1, "Trần Hoàng Nhung", "VAE02591", "B1"],
        [2, "Đào Việt Hải", "VAE00708", "B1"],
        [N, "A864-567"],
        [1, "Lê Văn Bảy", "VAE07777", "B1"],
        [],
        [],
    ]


def squad1(phones=None):
    tabs = {"1": day1(), "2": day1(), "3": day1()}
    days = [{"tab": t, "ac": "", "date": f"2026-10-{int(t):02d}"} for t in tabs]
    return ctx_for(0, make_sq(ROSTER1, COLORS1), tabs, days, phones), tabs


def intent(origin="roster", **kw):
    base = {"origin": origin, "squad": 0, "date": "2026-10-02"}
    base.update(kw)
    return base


def test_code_classification():
    c = a.parse_code
    assert c("")["kind"] == "empty" and c("n")["kind"] == "n" and c("H ATHK")["kind"] == "course"
    assert c(" a864 - 34 ")["aircraft"] == "A864" and c("A864-34")["zone"] == "34"
    assert c("A611")["kind"] == "aircraft" and c("A611")["zone"] is None
    assert c("TĐ")["kind"] == "role" and c("A864-FM")["kind"] == "role" and c("A864-PPC")["kind"] == "role"
    assert c("TĐ @16:00")["kind"] == "other" and c("P")["kind"] == "other"
    assert a.a1(0, 0) == "A1" and a.a1(11, 27) == "AB12"


def test_locate_day_agrees_with_parse_day():
    values = dist._rect(day1(), [])[0]
    loc = a.locate_day(values)
    got = [(s["title"].upper() or "OTHER", [p["id"] for p in s["people"]]) for t in loc["tables"] for s in t["sections"]]
    want = [(s["title"], [p["id"] for p in s["people"]]) for s in dist.parse_day(values, dist._rect(day1(), [])[1])]
    assert got == want == [("A864-128", ["VAE02854", "VAE00708"]), ("A864-567", ["VAE07777"]), ("A864-34", ["VAE02591"])]


def test_roster_code_adds_the_person_to_the_section_with_the_same_title():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-567"))
    assert p["status"] == "ok" and p["blocked"] is None
    assert by_a1(p["roster"]) == {("ROSTER", "E6"): ("", "A864-567")}
    # section 'A864-567' (left table): first free row is row 8 (index 7); ORD blank -> 2 (one person listed);
    # nobody's phone is known, so no phone cell is planned
    assert by_a1(p["day"]) == {("2", "A8"): ("", "2"), ("2", "B8"): ("", "Người Mới"), ("2", "C8"): ("", "VAE05555")}


def test_phone_is_filled_from_the_phone_book():
    ctx, _ = squad1({"VAE05555": "0900000001"})
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-34"))
    cells = by_a1(p["day"])
    assert cells[("2", "H5")] == ("", "2") and cells[("2", "I5")] == ("", "Người Mới")
    assert cells[("2", "J5")] == ("", "VAE05555") and cells[("2", "L5")] == ("", "0900000001")


def test_moving_to_another_zone_removes_the_old_row_and_reports_a_full_section():
    ctx, _ = squad1()
    # A864-128 has no free row (bounded by the 'A864-567' title): the day tab cannot follow, the roster still can
    p = a.plan_link(ctx, intent(id="VAE02591", kind="code", value="A864-128", old="A864-34"))
    assert p["status"] == "roster_only" and by_a1(p["roster"]) == {("ROSTER", "E2"): ("A864-34", "A864-128")}
    assert p["day"] == [] and "no free row in section 'A864-128'" in p["day_skipped"]
    assert not any("removed" in n for n in p["notes"])  # no notes about writes that will not happen


def test_moving_between_two_free_sections_clears_the_old_row_and_fills_the_new_one():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE07777", kind="code", value="A864-34", old="A864-567"))
    assert p["status"] == "ok"
    cells = by_a1(p["day"])
    # the whole row is blanked in the left table (ORD too: an ORD-only row would parse as a section title)
    assert cells[("2", "A7")] == ("1", "") and cells[("2", "B7")] == ("Lê Văn Bảy", "") and cells[("2", "C7")] == ("VAE07777", "")
    assert cells[("2", "I5")] == ("", "Lê Văn Bảy")  # first free row of 'A864-34' (right table)


def test_normal_n_takes_the_person_off_the_day_tab_and_blanks_the_whole_row():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE02854", kind="n", old="A864-128"))
    assert p["status"] == "ok" and by_a1(p["roster"]) == {("ROSTER", "E3"): ("A864-128", "N")}
    cells = by_a1(p["day"])
    assert cells == {("2", "A4"): ("1", ""), ("2", "B4"): ("Hồ Sĩ Út", ""), ("2", "C4"): ("VAE02854", ""),
                     ("2", "D4"): ("B1", "")}
    # and the blanked row is a plain free row again: re-reading the planned grid still parses without a stray section
    grid = a._grid(ctx, "2")
    assert [s["title"] for t in a.locate_day(grid)["tables"] for s in t["sections"]] == ["A864-128", "A864-567", "A864-34"]


def test_clear_does_the_same_and_a_person_not_listed_is_just_noted():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE02854", kind="clear", old="A864-128"))
    assert p["status"] == "ok" and len(p["day"]) == 4
    p = a.plan_link(ctx, intent(id="VAE05555", kind="n"))
    assert by_a1(p["roster"]) == {("ROSTER", "E6"): ("", "N")} and p["day"] == []
    assert any("nothing to remove" in n for n in p["notes"])


def test_aircraft_without_a_zone_goes_to_unassigned_appended_below_a_table():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864"))
    assert p["status"] == "ok"
    cells = by_a1(p["day"])
    # the right table is the emptier one: its last used row is 4 (index 3) -> title row 5, person row 6
    assert cells[("2", "I5")] == ("", "UNASSIGNED")
    assert cells[("2", "H6")] == ("", "1") and cells[("2", "I6")] == ("", "Người Mới") and cells[("2", "J6")] == ("", "VAE05555")
    assert any("new section 'UNASSIGNED'" in n for n in p["notes"])


def test_a_batch_sees_its_own_earlier_writes():
    ctx, _ = squad1()
    p1, p2 = a.plan_batch(ctx, [
        intent(id="VAE05555", kind="code", value="A864-567"),
        intent(id="VAE06666", kind="code", value="A864-567", old="P"),
    ])
    r1 = {w["a1"] for w in p1["day"]}
    r2 = {w["a1"] for w in p2["day"]}
    assert r1 == {"A8", "B8", "C8"} and r2 == {"A9", "B9", "C9"} and not (r1 & r2)
    # the same cell edited twice in one batch: the second sees the first one's value as its 'old'
    p3 = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-567"))
    assert p3["status"] == "noop"


def test_locked_cells_block_everything():
    ctx, _ = squad1()
    for kw, word in ((dict(id="VAE00708", date="2026-10-01", kind="code", value="A864-34"), "course marker"),
                     (dict(id="VAE02379", date="2026-10-03", kind="code", value="A864-34"), "red N")):
        p = a.plan_link(ctx, intent(**kw))
        assert p["status"] == "blocked" and word in p["blocked"] and p["roster"] == [] and p["day"] == []
    # moving somebody on a course (or on a guaranteed day off) into a zone from the daily side is blocked too
    p = a.plan_link(ctx, intent("daily", id="VAE00708", date="2026-10-01", tab="1", to="A864-34"))
    assert p["status"] == "blocked" and "course marker" in p["blocked"]
    p = a.plan_link(ctx, intent("daily", id="VAE02379", date="2026-10-03", tab="3", to="A864-34"))
    assert p["status"] == "blocked" and "red N" in p["blocked"]


def test_stale_old_value_and_unknown_things_are_blocked_not_forced():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-34", old="A864-128"))
    assert p["status"] == "blocked" and "changed since" in p["blocked"]
    assert "not on this squad's roster" in a.plan_link(ctx, intent(id="VAE00001", kind="n"))["blocked"]
    assert "not on the roster" in a.plan_link(ctx, intent(id="VAE05555", date="2026-12-25", kind="n"))["blocked"]
    assert "unknown origin" in a.plan_link(ctx, {"origin": "x", "id": "VAE05555", "date": "2026-10-02"})["blocked"]


def test_role_course_and_shift_codes_are_not_linked():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-FM"))
    assert p["status"] == "ok" and p["day"] == [] and any("role code" in n for n in p["notes"])
    p = a.plan_link(ctx, intent(id="VAE05555", kind="code", value="A864-34 @16H00", old="A864-FM"))
    assert p["day"] == [] and any("other code" in n for n in p["notes"])


def test_day_without_a_tab_is_roster_only():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent(id="VAE05555", date="2026-10-05", kind="code", value="A864-34"))
    assert p["status"] == "roster_only" and by_a1(p["roster"]) == {("ROSTER", "H6"): ("", "A864-34")}
    assert "no day tab for that date" in p["day_skipped"]


def test_daily_move_writes_the_roster_code_from_the_section_title():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent("daily", id="VAE05555", tab="2", to="A864-34"))
    assert p["status"] == "ok" and by_a1(p["roster"]) == {("ROSTER", "E6"): ("", "A864-34")}
    assert by_a1(p["day"])[("2", "I5")] == ("", "Người Mới")
    # a black N in the roster is replaced, and the plan says so
    p = a.plan_link(ctx, intent("daily", id="VAE02854", date="2026-10-03", tab="3", to="A864-567"))
    assert p["status"] == "ok" and by_a1(p["roster"]) == {("ROSTER", "F3"): ("N", "A864-567")}
    assert any("day off" in n for n in p["notes"])


def test_daily_move_to_unassigned_keeps_the_aircraft_only():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent("daily", id="VAE02591", tab="2", to="UNASSIGNED"))
    assert p["status"] == "ok" and by_a1(p["roster"]) == {("ROSTER", "E2"): ("A864-34", "A864")}
    cells = by_a1(p["day"])
    assert cells[("2", "I4")] == ("Trần Hoàng Nhung", "") and cells[("2", "H4")] == ("1", "") and any(v[1] == "UNASSIGNED" for v in cells.values())


def test_daily_origin_is_all_or_nothing():
    ctx, _ = squad1()
    # the target section is full: nothing at all is planned (the roster is not written alone)
    p = a.plan_link(ctx, intent("daily", id="VAE05555", tab="2", to="A864-128"))
    assert p["status"] == "blocked" and "no free row" in p["blocked"] and p["roster"] == [] and p["day"] == []
    # a section that does not exist is never created from a typo (only UNASSIGNED is)
    p = a.plan_link(ctx, intent("daily", id="VAE05555", tab="2", to="A864-999"))
    assert p["status"] == "blocked" and "does not exist" in p["blocked"]
    # a roster cell that is not an aircraft code ('P' = leave) must be fixed in the roster first
    p = a.plan_link(ctx, intent("daily", id="VAE06666", tab="2", to="A864-34"))
    assert p["status"] == "blocked" and "not an aircraft code" in p["blocked"]
    assert a.plan_link(ctx, intent("daily", id="VAE05555", tab="9", to="A864-34"))["status"] == "blocked"


def test_daily_move_leaves_a_role_code_in_the_roster():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent("daily", id="VAE02591", date="2026-10-01", tab="1", to="A864-567"))
    assert p["status"] == "ok" and p["roster"] == [] and any("role code" in n for n in p["notes"])
    assert p["day"]  # the day tab still follows


def test_taking_somebody_out_of_the_distribution_leaves_or_clears_the_roster():
    ctx, _ = squad1()
    p = a.plan_link(ctx, intent("daily", id="VAE02854", tab="2", to=None))
    assert p["status"] == "ok" and p["roster"] == [] and len(p["day"]) == 4
    assert any("left as it is" in n for n in p["notes"])
    a.LINK_REMOVE_CLEARS_ROSTER = True
    try:
        ctx, _ = squad1()
        p = a.plan_link(ctx, intent("daily", id="VAE02854", tab="2", to=None))
        assert by_a1(p["roster"]) == {("ROSTER", "E3"): ("A864-128", "")}
    finally:
        a.LINK_REMOVE_CLEARS_ROSTER = False


# ----------------------------------------------------------------- Squad 2 (aircraft layout)
ROSTER2 = [
    ["NO.", "NAME & SURNAME", "ID", "Category", serial(1), serial(2), serial(3)],
    [1, "Lê Hữu Toàn", "VAE01240", "B1", "A611", "A611", "N"],
    [2, "Nguyễn Thị Lan", "VAE03333", "B1", N, N, N],
]


def a611_tab():
    return [
        ["ORD", "NAME AND SURNAME", "ID", "POSITION", "REMARK"],
        [N, "ZONE 128"],
        [1, "Lê Hữu Toàn", "VAE01240", "B1"],
        [N, "ZONE AVI"],
        [],
        [N, "STRUCTURE PAINTING"],
        [1, "Võ Văn Sơn", "VAE08888", "B2"],
    ]


def a326_tab():
    return [["ORD", "NAME AND SURNAME", "ID", "POSITION", "REMARK"], [N, "ZONE 34"], [], []]


def squad2():
    tabs = {"A611-OCT02": a611_tab(), "A326-OCT02": a326_tab()}
    days = [{"tab": "A611-OCT02", "ac": "A611", "date": "2026-10-02"},
            {"tab": "A326-OCT02", "ac": "A326", "date": "2026-10-02"}]
    return ctx_for(1, make_sq(ROSTER2), tabs, days), tabs


def i2(origin="roster", **kw):
    return intent(origin, squad=1, **kw)


def test_aircraft_layout_puts_a_new_aircraft_into_unassigned_on_the_matching_tab():
    ctx, _ = squad2()
    assert ctx["layout"].name == "aircraft"
    p = a.plan_link(ctx, i2(id="VAE03333", kind="code", value="a611"))
    assert p["status"] == "ok" and by_a1(p["roster"]) == {("ROSTER", "F3"): ("", "a611")}
    cells = by_a1(p["day"])
    # appended below the last used row (7): title row 8, person row 9
    assert cells[("A611-OCT02", "B8")] == ("", "UNASSIGNED")
    assert cells[("A611-OCT02", "B9")] == ("", "Nguyễn Thị Lan") and cells[("A611-OCT02", "C9")] == ("", "VAE03333")
    assert {t for t, _ in cells} == {"A611-OCT02"}


def test_aircraft_layout_leaves_a_person_in_their_zone_when_the_aircraft_is_unchanged():
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2(id="VAE01240", kind="code", value="A611", old="A611"))
    assert p["status"] == "noop" and any("already listed under 'ZONE 128'" in n for n in p["notes"])


def test_aircraft_layout_changing_the_aircraft_moves_between_tabs():
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2(id="VAE01240", kind="code", value="A326", old="A611"))
    assert p["status"] == "ok"
    cells = by_a1(p["day"])
    assert cells[("A611-OCT02", "B3")] == ("Lê Hữu Toàn", "") and cells[("A611-OCT02", "C3")] == ("VAE01240", "")
    assert cells[("A326-OCT02", "B3")] == ("", "UNASSIGNED") and cells[("A326-OCT02", "B4")] == ("", "Lê Hữu Toàn")


def test_aircraft_layout_without_a_tab_for_that_aircraft_is_roster_only():
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2(id="VAE03333", kind="code", value="A777"))
    assert p["status"] == "roster_only" and "no day tab for aircraft A777" in p["day_skipped"]
    assert "A611-OCT02, A326-OCT02" in p["day_skipped"]


def test_aircraft_layout_normal_n_removes_from_every_tab_of_that_day():
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2(id="VAE01240", kind="n", old="A611"))
    assert p["status"] == "ok" and set(by_a1(p["day"])) == {("A611-OCT02", c) for c in ("A3", "B3", "C3", "D3")}


def test_aircraft_layout_daily_move_sets_the_aircraft_and_relocates_between_zones():
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2("daily", id="VAE03333", tab="A611-OCT02", to="ZONE AVI"))
    assert p["status"] == "ok" and by_a1(p["roster"]) == {("ROSTER", "F3"): ("", "A611")}
    assert by_a1(p["day"])[("A611-OCT02", "B5")] == ("", "Nguyễn Thị Lan")
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2("daily", id="VAE01240", tab="A611-OCT02", to="ZONE AVI"))
    cells = by_a1(p["day"])
    assert p["roster"] == []  # the roster already says A611: the zone is not kept there
    assert cells[("A611-OCT02", "B3")] == ("Lê Hữu Toàn", "") and cells[("A611-OCT02", "B5")] == ("", "Lê Hữu Toàn")
    # Toàn's row in ZONE 128 was blanked by the plan above (same batch), so it is free for the next person
    p = a.plan_link(ctx, i2("daily", id="VAE03333", tab="A611-OCT02", to="ZONE 128"))
    assert p["status"] == "ok" and by_a1(p["day"])[("A611-OCT02", "B3")] == ("", "Nguyễn Thị Lan")
    # ... and a zone with no free row refuses
    ctx, _ = squad2()
    p = a.plan_link(ctx, i2("daily", id="VAE03333", tab="A611-OCT02", to="ZONE 128"))
    assert p["status"] == "blocked" and "no free row in section 'ZONE 128'" in p["blocked"]


# ----------------------------------------------------------------- entry points
def test_dry_run_reports_per_squad_errors_and_prints_the_cells():
    ctx, _ = squad1()
    real = a.load_context
    a.load_context = lambda index, force=True: ctx if index == 0 else (_ for _ in ()).throw(ValueError("boom"))
    try:
        res = a.dry_run([intent(id="VAE05555", kind="code", value="A864-567"), i2(id="VAE03333", kind="n"),
                         {"id": "x"}], "tester")
    finally:
        a.load_context = real
    assert [p["status"] for p in res["plans"]] == ["ok", "blocked", "blocked"]
    assert "boom" in res["plans"][1]["blocked"] and "squad" in res["plans"][2]["blocked"]
    assert [s["error"] is None for s in res["squads"]] == [True, False]
    text = "\n".join(res["lines"])
    assert "[OK]" in text and "day tab '2'!B8" in text and "roster 'ROSTER'!E6" in text


def test_a_squad_the_user_may_not_edit_is_refused():
    ctx, _ = squad1()
    real_load, real_can = a.load_context, auth.can_edit
    a.load_context = lambda index, force=True: ctx
    auth.can_edit = lambda user, squad=None: False
    try:
        res = a.dry_run([intent(id="VAE05555", kind="n")], "tester")
    finally:
        a.load_context, auth.can_edit = real_load, real_can
    assert res["plans"][0]["status"] == "blocked" and "not allowed" in res["plans"][0]["blocked"]


def test_route_needs_a_login_and_only_plans():
    import app as web

    ctx, _ = squad1()
    real = a.load_context
    a.load_context = lambda index, force=True: ctx
    try:
        c = web.app.test_client()
        body = {"intents": [intent(id="VAE05555", kind="code", value="A864-567")]}
        assert c.post("/api/link/dry-run", json=body).status_code == 401
        users = os.path.join(tempfile.mkdtemp(), "users.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["username", "password"])
        wb.active.append(["tester", "pw"])
        wb.save(users)
        auth.USERS_FILE = users
        auth._cache.update(key=None, users={})
        assert c.post("/api/login", json={"username": "tester", "password": "pw"}).status_code == 200
        r = c.post("/api/link/dry-run", json=body).get_json()
        assert r["ok"] and r["plans"][0]["status"] == "ok" and r["lines"]
        assert c.post("/api/link/dry-run", json={"intents": []}).status_code == 400
        assert c.post("/api/link/dry-run", data="x").status_code == 400
    finally:
        a.load_context = real


if __name__ == "__main__":
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
