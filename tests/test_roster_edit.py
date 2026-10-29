"""Roster hand-edit tests (Phase 2): staged edits are re-checked against the live sheet, then written.

Run:  python tests/test_roster_edit.py        (or: pytest tests)

Reuses the mock squads of test_squad_roster.py / test_khdt_review.py with a fake Google source and a fake
writer: no credentials or network needed.
"""

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import openpyxl  # noqa: E402

import auth  # noqa: E402
import roster_edit  # noqa: E402
import test_khdt_review as t  # noqa: E402
import test_squad_roster as base  # noqa: E402

N = None
# Squad 3 with a red N on Phan Minh Khoa's Oct 4 (row 3, column 6).
COLORS3 = [[N] * 7 for _ in range(3)] + [[N, N, N, N, N, N, "FF0000"]]


def setup():
    grid4 = copy.deepcopy(t.SQUAD4)
    sources = base.squads(colors=COLORS3, squad4=base.workbook(4, grid4))
    base.load(sources)
    written = []
    roster_edit.write_roster_updates = lambda sid, gid, updates: written.append((sid, gid, updates))
    roster_edit._tab_gid = lambda sid, title: 7
    auth.can_edit = lambda user, squad=None: True
    return sources, written


def edit(eid, date, kind="code", value="", old="", squad=3, name=None):
    return {"squad": squad, "id": eid, "name": name or eid, "date": date, "old": old, "kind": kind, "value": value}


def skipped(res, squad_pos=0):
    return {(s["id"], s["date"]): s["reason"] for s in res["squads"][squad_pos]["skipped"]}


def test_writes_a_code_a_normal_n_and_a_clear_in_black():
    _, written = setup()
    res = roster_edit.save([
        edit("VAE07777", "2026-10-01", "code", "  a864-fm "),
        edit("VAE07777", "2026-10-02", "n"),
        edit("VAE07778", "2026-10-02", "code", "A611"),
        edit("VAE07778", "2026-10-03", "clear", old="N"),
    ], "tester")
    sq = res["squads"][0]
    assert sq["name"] == "Squad 4" and sq["written"] == 4 and sq["skipped"] == [] and sq["error"] is None
    (sid, gid, updates), = written
    assert (sid, gid) == ("sq4", 7)
    got = sorted((u["row"], u["col"], u["value"], u["color"]) for u in updates)
    assert got == [(2, 3, "a864-fm", "000000"), (2, 4, "N", "000000"), (3, 4, "A611", "000000"), (3, 5, "", "000000")]


def test_locked_cells_are_never_overwritten():
    _, written = setup()
    res = roster_edit.save([
        edit("VAE07778", "2026-10-01", "code", "A611", old="H ATHK"),               # a KHDT course marker
        edit("VAE02012", "2026-10-04", "code", "A611", old="N", squad=2),           # a red N
        edit("VAE07778", "2026-10-01", "clear", old="H ATHK"),
    ], "tester")
    why = {k: v for r in res["squads"] for k, v in skipped({"squads": [r]}).items()}
    assert "locked" in why[("VAE07778", "2026-10-01")] and "locked" in why[("VAE02012", "2026-10-04")]
    assert written == [] and all(s["written"] == 0 for s in res["squads"])


def test_stale_cells_are_skipped():
    sources, written = setup()
    sources[3].grids["ROSTER"][2][3] = "A611"  # somebody typed into VAE07777's Oct 1 after the page loaded
    res = roster_edit.save([edit("VAE07777", "2026-10-01", "code", "A864"), edit("VAE07777", "2026-10-02", "code", "A864")], "t")
    assert res["squads"][0]["written"] == 1
    assert "changed since" in skipped(res)[("VAE07777", "2026-10-01")]
    assert [u["col"] for u in written[0][2]] == [4]


def test_moved_employee_or_unknown_date_is_skipped():
    sources, written = setup()
    res = roster_edit.save([
        edit("VAE01240", "2026-10-01", "code", "A1", squad=3),   # a Squad 2 person sent as Squad 4
        edit("VAE07777", "2026-12-25", "code", "A1"),             # not a date column
    ], "t")
    why = skipped(res)
    assert "no longer on this squad" in why[("VAE01240", "2026-10-01")]
    assert "not on the sheet" in why[("VAE07777", "2026-12-25")]
    assert written == []


def test_values_that_are_not_allowed():
    _, written = setup()
    bad = {"": "empty", "N": "Normal N", "n": "Normal N", "H ATHK": "KHDT only", "x" * 41: "longer than"}
    cells = [("VAE07777", "2026-10-01"), ("VAE07777", "2026-10-02"), ("VAE07777", "2026-10-03"),
             ("VAE07777", "2026-10-04"), ("VAE07778", "2026-10-02")]  # one cell each: the last edit of a cell wins
    res = roster_edit.save([edit(i, d, "code", v) for (i, d), v in zip(cells, bad)], "t")
    assert written == [] and len(res["squads"][0]["skipped"]) == len(bad)
    reasons = " | ".join(s["reason"] for s in res["squads"][0]["skipped"])
    assert all(word in reasons for word in bad.values())


def test_no_change_is_not_written_and_the_last_edit_of_a_cell_wins():
    _, written = setup()
    res = roster_edit.save([
        edit("VAE07778", "2026-10-03", "n", old="N"),                    # already a black N
        edit("VAE07777", "2026-10-01", "code", "A1"),
        edit("VAE07777", "2026-10-01", "code", "A2"),
    ], "t")
    assert "no change" in skipped(res)[("VAE07778", "2026-10-03")]
    assert [u["value"] for u in written[0][2]] == ["A2"]


def test_invalid_entries_are_counted_and_the_limit_is_enforced():
    setup()
    res = roster_edit.save([{"id": "VAE07777"}, {"squad": "x", "id": "a", "date": "2026-10-01", "kind": "code"},
                            edit("VAE07777", "bad-date"), edit("VAE07777", "2026-10-01", "boom")], "t")
    assert res["invalid"] == 4 and res["squads"] == []
    try:
        roster_edit.save([edit("VAE07777", "2026-10-01")] * (roster_edit.MAX_EDITS + 1), "t")
    except ValueError as e:
        assert "Too many" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_a_squad_the_user_may_not_edit_is_refused():
    _, written = setup()
    auth.can_edit = lambda user, squad=None: squad != 3
    res = roster_edit.save([edit("VAE07777", "2026-10-01", "code", "A1")], "t")
    assert "not allowed" in res["squads"][0]["error"] and written == []


def test_an_unwritable_squad_is_reported():
    setup()

    def boom(*a):
        raise RuntimeError("quota")

    roster_edit.write_roster_updates = boom
    res = roster_edit.save([edit("VAE07777", "2026-10-01", "code", "A1")], "t")
    assert res["squads"][0]["written"] == 0 and "quota" in res["squads"][0]["error"]


def test_route_needs_a_login_and_then_writes():
    import app as web

    _, written = setup()
    c = web.app.test_client()
    body = {"edits": [edit("VAE07777", "2026-10-01", "code", "A864")]}
    assert c.post("/api/roster/save", json=body).status_code == 401
    users = os.path.join(tempfile.mkdtemp(), "users.xlsx")
    wb = openpyxl.Workbook()
    wb.active.append(["username", "password"])
    wb.active.append(["tester", "pw"])
    wb.save(users)
    auth.USERS_FILE = users
    auth._cache.update(key=None, users={})
    real_can_edit = auth.can_edit
    assert c.post("/api/login", json={"username": "tester", "password": "pw"}).status_code == 200
    r = c.post("/api/roster/save", json=body).get_json()
    assert r["ok"] and r["squads"][0]["written"] == 1 and len(written) == 1
    assert c.post("/api/roster/save", json={"edits": []}).status_code == 400
    assert c.post("/api/roster/save", data="x").status_code == 400
    auth.can_edit = real_can_edit


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
