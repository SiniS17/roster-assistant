"""Daily Distribution parser tests.

Run:  python tests/test_distribution.py        (or: pytest tests)

The grids below are copied from real screenshots of the squad spreadsheets, not read from the live
sheets: they show the layouts are understood, not that the live data is right. Google is replaced by
a fake source, so no credentials or network are needed.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import distribution as d  # noqa: E402

N = None


def serial(y, m, dd):
    return (date(y, m, dd) - date(1899, 12, 30)).days


# --------------------------------------------------------------------------- fake workbooks
class FakeSource:
    kind, id = "sheets", "fake"

    def __init__(self, title, tab_grids):
        self.title = title
        self.grids = tab_grids  # {tab title: values}, in sheet order

    def tabs(self):
        return list(self.grids)

    def grid(self, tab, with_colors=True):
        return d._rect(self.grids[tab], [])


def load(title, tab_grids):
    """Point the module at one fake spreadsheet and drop anything cached from an earlier one."""
    d._cache.clear()
    d.configured_urls = lambda: ["https://example.invalid/fake"]
    d.open_source = lambda url: FakeSource(title, tab_grids)


# Squad 1 / 4: 1st sheet 'ROSTER' (no month text; real dates over the day columns), day tabs '1'..'16'.
SQUAD1_ROSTER = (
    [[N] * 12 for _ in range(12)]
    + [
        [N, N, N, "T5", "T6", "T7", "CN", "T2", "T3", "T4", "T5", "T6"],
        ["NO", "NAME & SURNAME", "ID"] + [serial(2026, 10, n) for n in range(1, 10)],
        [1, "Nguyễn Thành Vũ", "VAE02589", "TĐ", "TĐ", "TĐ", N, "TĐ", "A877-FM", "TĐ", "TĐ", "TĐ", "TĐ"],
        [2, "Nguyễn Đình Hiệt", "VAE00750", "TĐ", "TĐ", "N", "TĐ", "TĐ", "TĐ", "TĐ", "N", "TĐ", "TĐ"],
        [3, "Trần Hoàng Nhung", "VAE02591", "A864-PPC", "A864-PPC", "A871-PPC", N, "A871-PPC", "A877-PPC", "A877-PPC", "A877-PPC", "A877-PPC"],
        [5, "Hứa Quang Trung", "VAE02481", "A864-FM", "A864-FM", "A871-FM", "N", "A871-FM", "A877-34", "A877-34", "A877-34", "A877-34"],
    ]
)


def squad1_day(n, with_ac=True):
    """A Squad 1 day tab: info block, then two tables side by side with 'VAECO ID' headers."""
    return [
        ["HCM BASE MAINTENANCE CENTER"],
        [N, N, N, N, N, N, N, "DAILY MAINTENANCE DISTRIBUTION"],
        ["A/C:  A864" if with_ac else N, N, N, serial(2026, 10, n), N, N, N, "BCH ĐỘI", "Nguyễn Thành Vũ"],
        [N, "FOREMAN:", "Hứa Quang Trung", "PHONE:", "0937387889", "Thi CAAV", N, "TECH SUPPORT", "#N/A"],
        [N, "CRS C", "Võ Lục Nguyên Thông", "PHONE:", "0909028666", N, N, "DOCK PLANNER:", "Trần Hoàng Nhung"],
        ["ORD", "NAME AND SURNAME", "VAECO ID", "POSITION", "PHONE", "REMARK", N, "ORD", "NAME AND SURNAME", "VAECO ID"],
        [N, "A864-128", N, N, N, N, N, N, "A864-34"],
        [1, "Đào Việt Hải", "VAE00708", "B1 787", "0908630644", N, N, 1, "Hồ Sĩ Út", "VAE02854"],
        [2, "Lộc Đức Hiền", "VAE02379", "B1 787", "0896961686", "Leader/GSGT", N, 2, "Phạm Ngọc Anh", "VAE01348"],
        [N, N, N, N, N, "stray note, not a section"],
        [3, N, "VAE00763", "QM 787", N, N],  # an ID with no name yet
    ]


def squad1_workbook(**kw):
    grids = {"ROSTER": SQUAD1_ROSTER}
    grids.update({str(i): squad1_day(i, **kw) for i in range(1, 17)})
    return grids


# --------------------------------------------------------------------------- tab names
def test_tab_names():
    ref = date(2026, 10, 1)
    cases = {
        "A326-OCT011": (("A326", ""), date(2026, 10, 11)),  # zero-padded day: Oct 11, not skipped
        "A326-OCT010": (("A326", ""), date(2026, 10, 10)),
        "A326-OCT09": (("A326", ""), date(2026, 10, 9)),
        "WO COMP A611-OCT07": (("A611", "WO COMP"), date(2026, 10, 7)),
        "B218-SEP21": (("B218", ""), date(2026, 9, 21)),
        "1": (("", ""), date(2026, 10, 1)),  # number only = day of the roster's month, no aircraft
        "14": (("", ""), date(2026, 10, 14)),
    }
    for tab, (ac_note, day) in cases.items():
        parsed = d.parse_tab_name(tab, ref, ref)
        assert parsed is not None, tab
        assert (d.split_ac_note(parsed[0]), parsed[1]) == (ac_note, day), tab
    for tab in ("32", "0", "notes", "Template", "ROSTER"):
        assert d.parse_tab_name(tab, ref, ref) is None, tab


# --------------------------------------------------------------------------- squad 1 / 4
def test_squad1_lists_every_numeric_tab_with_the_rosters_month():
    load("Squad 1 Roster", squad1_workbook())
    meta = d.meta_for(0, True)
    assert meta["error"] is None
    assert len(meta["days"]) == 16
    assert meta["days"][0] == {"tab": "1", "ac": "", "note": "", "date": "2026-10-01"}
    assert meta["days"][-1]["date"] == "2026-10-16"
    assert meta["ac_known"] == ""  # no aircraft on the tab names: the page shows the date only
    assert meta["warnings"] == []


def test_squad1_day_reads_info_block_and_tables():
    load("Squad 1 Roster", squad1_workbook())
    day = d.build_day(0, "1", True)
    assert day["date"] == "2026-10-01"
    assert day["ac"] == "A864"  # from 'A/C:  A864' on the day tab
    crew = day["crew"]
    assert [(p["name"], p["phone"]) for p in crew["foreman"]] == [("Hứa Quang Trung", "0937387889")]
    assert [p["name"] for p in crew["truc_doi"]] == ["Nguyễn Thành Vũ"]  # 'BCH ĐỘI'
    assert [p["name"] for p in crew["dock_planner"]] == ["Trần Hoàng Nhung"]
    assert "shift_tech" not in crew  # 'TECH SUPPORT: #N/A' means nobody
    titles = [s["title"] for s in day["sections"]]
    assert titles == ["A864-128", "A864-34"]  # the stray REMARK note is not a section
    assert all(s["kind"] == "zone" for s in day["sections"])
    left, right = day["sections"]
    assert [p["id"] for p in left["people"]] == ["VAE00708", "VAE02379", "VAE00763"]
    assert left["people"][0]["phone"] == "0908630644"
    assert left["people"][1]["remark"] == "Leader/GSGT"
    assert left["people"][2]["name"] == ""  # ID but no name yet: still listed
    assert [p["name"] for p in right["people"]] == ["Hồ Sĩ Út", "Phạm Ngọc Anh"]


def test_squad1_day_without_aircraft_has_no_aircraft():
    load("Squad 1 Roster", squad1_workbook(with_ac=False))
    assert d.build_day(0, "3", True)["ac"] == ""


def test_squad1_crew_from_roster_codes_when_day_tab_has_no_labels():
    load("Squad 1 Roster", {"ROSTER": SQUAD1_ROSTER, "7": [["ORD", "NAME AND SURNAME", "VAECO ID"], [N, "A864-128"], [1, "Đào Việt Hải", "VAE00708"]]})
    day = d.build_day(0, "7", True)  # Oct 7 (column 'T4' is Oct 7 in the mock header)
    assert [p["name"] for p in day["crew"].get("truc_doi", [])] == ["Nguyễn Thành Vũ", "Nguyễn Đình Hiệt"]
    assert [p["name"] for p in day["crew"].get("dock_planner", [])] == ["Trần Hoàng Nhung"]


# --------------------------------------------------------------------------- squad 2 / 3
def test_squad3_style_tabs_past_the_9th_are_listed():
    roster = [["ROSTER ĐỘI 3 THÁNG 10.2026"]]
    tabs = {"Doi 3 Thang 10": roster}
    for name in ("A611-OCT06", "WO COMP A611-OCT07", "A326-OCT08", "A326-OCT09", "A326-OCT010", "A326-OCT011", "notes"):
        tabs[name] = [["ORD", "NAME AND SURNAME", "ID"]]
    load("Squad 3 Roster", tabs)
    meta = d.meta_for(0, True)
    assert [x["date"] for x in meta["days"]] == [f"2026-10-{n:02d}" for n in range(6, 12)]
    assert [x["ac"] for x in meta["days"]] == ["A611", "A611", "A326", "A326", "A326", "A326"]
    assert meta["days"][1]["note"] == "WO COMP"


def test_old_layout_still_parses():
    values = [
        ["ORD", "NAME AND SURNAME", "ID", "POSITION", "REMARK"],
        [N, "ZONE 128"],
        [1, "A", "VAE00001", "B1", N],
        [N, "ZONE AVI"],
        [1, "B", "VAE00002", "B2", "x"],
    ]
    secs = d.parse_day(values, [], {})
    assert [(s["title"], s["kind"], len(s["people"])) for s in secs] == [("ZONE 128", "zone", 1), ("ZONE AVI", "zone", 1)]


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
