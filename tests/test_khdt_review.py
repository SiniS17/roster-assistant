"""KHDT review/export tests: KHDT is matched against the 4 squads' 1st sheets and proposed (not written);
the kept changes are then written back, each re-checked against the live sheet.

Run:  python tests/test_khdt_review.py        (or: pytest tests)

Reuses the mock squads of test_squad_roster.py plus a Squad 4 with empty cells; fake Google source and
a fake writer: no credentials or network needed.
"""

import copy
import io
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import distribution as d  # noqa: E402
import khdt_review  # noqa: E402
import test_squad_roster as base  # noqa: E402

N = None
SECRET = "test-secret"
serial = base.serial

# Squad 4: Vietnamese headers, bare empty cells, Oct 1-4 (Oct 3 = Saturday, Oct 4 = Sunday).
SQUAD4 = [
    ["ROSTER"],
    ["STT", "HỌ VÀ TÊN", "MÃ VAECO"] + [serial(n) for n in (1, 2, 3, 4)],
    [1, "Test Bốn", "VAE07777", "", "", "", ""],
    [2, "Có Sẵn", "VAE07778", "H ATHK", "", "N", "N"],
]


def khdt(eid, start, end=None, code="ATHK/2610/01", note=None, name=None):
    return {"row": 5, "id": eid, "name": name or eid, "doi": None, "course": None, "class_code": code,
            "start": start, "end": end or start, "note": note}


def setup(squad4=None):
    grid4 = copy.deepcopy(squad4 if squad4 is not None else SQUAD4)  # some tests edit the sheet
    sources = base.squads(squad4=base.workbook(4, grid4))
    base.load(sources)
    written = []
    khdt_review.write_roster_updates = lambda sid, gid, updates: written.append((sid, gid, updates))
    khdt_review._tab_gid = lambda sid, title: 7
    return sources, written


def by_key(changes):
    return {(c["id"], c["date"]): c for c in changes}


def test_preview_proposes_changes_per_squad_and_writes_nothing():
    _, written = setup()
    rows = [
        khdt("VAE07777", date(2026, 10, 1), date(2026, 10, 2)),   # Squad 4, empty cells
        khdt("VAE02481", date(2026, 10, 1)),                       # Squad 1, cell already has 'A864-FM'
        khdt("VAE02589", date(2026, 10, 2)),                       # in Squads 1 AND 2: belongs to Squad 1 only
        khdt("VAE09999", date(2026, 10, 2)),                       # reinforcement block of Squad 3: not a squad member
        khdt("VAE00000", date(2026, 10, 2)),                       # nobody
    ]
    r = khdt_review.preview(rows, SECRET)
    ch = by_key(r["changes"])
    assert written == []  # nothing is written

    new1 = ch[("VAE07777", "2026-10-01")]
    assert (new1["squad"], new1["squadName"], new1["old"], new1["new"], new1["newColor"], new1["kind"]) == \
        (3, "Squad 4", "", "H ATHK", "FF0000", "new")
    assert ("VAE07777", "2026-10-02") in ch

    conflict = ch[("VAE02481", "2026-10-01")]
    assert conflict["old"] == "A864-FM" and conflict["new"] == "A864-FM-H ATHK" and conflict["kind"] == "conflict"

    dup = ch[("VAE02589", "2026-10-02")]
    assert dup["squad"] == 0 and dup["old"] == "TĐ"
    assert not any(c["squad"] == 1 for c in r["changes"])  # the Squad 2 copy is ignored

    assert not any(c["id"] == "VAE09999" for c in r["changes"])
    assert r["stats"]["no_id_match"] == 2
    assert [s["changes"] for s in r["squads"]] == [2, 0, 0, 2]


def test_weekend_and_existing_content_rules_still_apply():
    _, _ = setup()
    rows = [
        khdt("VAE07777", date(2026, 10, 3), date(2026, 10, 4)),   # Sat+Sun -> N (black) on empty cells
        khdt("VAE07778", date(2026, 10, 1), date(2026, 10, 3)),   # Oct 1 already 'H ATHK'; Oct 3 black N already
    ]
    ch = by_key(khdt_review.preview(rows, SECRET)["changes"])
    n = ch[("VAE07777", "2026-10-03")]
    assert n["new"] == "N" and n["newColor"] == "000000" and n["kind"] == "new"
    # 'H ATHK' is already there, and black N over black N is no change at all
    assert ("VAE07778", "2026-10-01") not in ch and ("VAE07778", "2026-10-03") not in ch
    # Oct 2 was empty on weekday -> a new marker
    assert ch[("VAE07778", "2026-10-02")]["new"] == "H ATHK"


def test_changes_are_signed_and_tampering_is_detected():
    setup()
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1))], SECRET)
    c = r["changes"][0]
    assert khdt_review.verify(c, SECRET) and not khdt_review.verify(c, "other-secret")
    forged = dict(c, new="rm -rf")
    assert not khdt_review.verify(forged, SECRET)
    assert khdt_review.verify(dict(c, name="Another display name"), SECRET)  # display-only fields aren't signed


def test_unreadable_squad_is_reported_not_fatal():
    sources = base.squads()  # Squad 4 fails to open
    base.load(sources)
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1))], SECRET)
    assert r["changes"] == [] and r["stats"]["no_id_match"] == 1
    assert r["squads"][3]["error"] and any("Squad 4" in line and "WARN" in line for line in r["log"])


def test_export_writes_kept_changes_to_the_right_sheet_and_tab():
    _, written = setup()
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1), date(2026, 10, 2)),
                             khdt("VAE02481", date(2026, 10, 1))], SECRET)
    out = khdt_review.export(r["changes"], SECRET)
    assert out["invalid"] == 0
    assert {s["name"]: s["written"] for s in out["squads"]} == {"Squad 1": 1, "Squad 4": 2}
    sheets = {sid: (gid, ups) for sid, gid, ups in written}
    assert set(sheets) == {"sq1", "sq4"} and sheets["sq4"][0] == 7
    assert sorted((u["row"], u["col"], u["value"], u["color"]) for u in sheets["sq4"][1]) == \
        [(2, 3, "H ATHK", "FF0000"), (2, 4, "H ATHK", "FF0000")]
    assert sheets["sq1"][1][0]["value"] == "A864-FM-H ATHK"


def test_export_skips_cells_changed_since_the_preview():
    sources, written = setup()
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1), date(2026, 10, 2))], SECRET)
    sources[3].grids["ROSTER"][2][3] = "A611"  # somebody typed into Oct 1 after the preview
    out = khdt_review.export(r["changes"], SECRET)
    sq4 = out["squads"][0]
    assert sq4["written"] == 1 and len(sq4["skipped"]) == 1
    assert sq4["skipped"][0]["date"] == "2026-10-01" and "changed since the preview" in sq4["skipped"][0]["reason"]
    assert [u["col"] for u in written[0][2]] == [4]


def test_export_skips_when_the_employee_moved_to_another_row():
    sources, written = setup()
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1))], SECRET)
    g = sources[3].grids["ROSTER"]
    g[2], g[3] = g[3], g[2]  # two people swapped rows
    out = khdt_review.export(r["changes"], SECRET)
    assert out["squads"][0]["written"] == 0 and "no longer on that row" in out["squads"][0]["skipped"][0]["reason"]
    assert written == []


def test_export_refuses_forged_changes():
    _, written = setup()
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1))], SECRET)
    forged = dict(r["changes"][0], new="anything I like")
    out = khdt_review.export([forged], SECRET)
    assert out["invalid"] == 1 and out["squads"] == [] and written == []


def test_export_reports_a_squad_it_cannot_edit():
    _, written = setup()
    r = khdt_review.preview([khdt("VAE07777", date(2026, 10, 1))], SECRET)

    def boom(*a):
        raise RuntimeError("quota")

    khdt_review.write_roster_updates = boom
    out = khdt_review.export(r["changes"], SECRET)
    assert out["squads"][0]["written"] == 0 and "quota" in out["squads"][0]["error"]


def test_routes_preview_then_export():
    import openpyxl

    import app as web

    _, written = setup()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["STT", "Mã NV", "Họ tên", "Phòng/Đội", "Tên KĐT", "Mã lớp học", "Bắt đầu", "Kết thúc", "Lí do"])
    # KHDT dates are YYYY-DD-MM: '2026-01-10' is 1 Oct, '2026-02-10' is 2 Oct.
    ws.append([1, "VAE07777", "Test Bốn", "D4", "An toàn hàng không", "ATHK/2610/01", "2026-01-10", "2026-02-10", None])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    client = web.app.test_client()
    j = client.post("/api/khdt/preview", data={"khdt_file": (buf, "khdt.xlsx")},
                    content_type="multipart/form-data").get_json()
    assert j["ok"] and j["file"] == "khdt.xlsx" and len(j["changes"]) == 2 and j["log_b64"]
    assert written == []
    assert {c["date"] for c in j["changes"]} == {"2026-10-01", "2026-10-02"}

    # export writes to the sheets, so it needs a login (auth.py)
    assert client.post("/api/khdt/export", json={"changes": j["changes"][:1]}).status_code == 401
    import tempfile

    import auth
    users = os.path.join(tempfile.mkdtemp(), "users.xlsx")
    ub = openpyxl.Workbook()
    ub.active.append(["username", "password"])
    ub.active.append(["tester", "pw"])
    ub.save(users)
    auth.USERS_FILE = users
    auth._cache.update(key=None, users={})
    assert client.post("/api/login", json={"username": "tester", "password": "pw"}).status_code == 200

    k = client.post("/api/khdt/export", json={"changes": j["changes"][:1]}).get_json()
    assert k["ok"] and k["squads"][0]["written"] == 1 and len(written) == 1

    assert client.post("/api/khdt/export", json={"changes": []}).status_code == 400
    assert client.post("/api/khdt/preview", data={}).status_code == 400


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
