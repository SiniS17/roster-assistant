"""Main-roster tests: the roster page is built from the 1st sheet of the 4 squads' spreadsheets.

Run:  python tests/test_squad_roster.py        (or: pytest tests)

Four mock spreadsheets (laid out like the squad screenshots, not the live sheets) and a fake Google
source: no credentials or network needed.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import distribution as d  # noqa: E402
import squad_roster  # noqa: E402

N = None
URLS = [f"https://example.invalid/squad{i}" for i in range(1, 5)]


def serial(dd, m=10):
    return (date(2026, m, dd) - date(1899, 12, 30)).days


class FakeSource:
    kind = "sheets"

    def __init__(self, sid, grids, colors=None):
        self.id, self.title, self.grids, self.color_grids = sid, sid, grids, colors or {}

    def tabs(self):
        return list(self.grids)

    def grid(self, tab, with_colors=True):
        return d._rect(self.grids[tab], self.color_grids.get(tab, []))


def day_tab():
    return [["ORD", "NAME AND SURNAME", "VAECO ID"]]


# Squad 1: the name header is hidden under the logo (empty cell), dates Oct 1-3.
SQUAD1 = [
    ["ROSTER"],
    ["NO", N, "ID"] + [serial(n) for n in (1, 2, 3)],
    [1, "Nguyễn Thành Vũ", "VAE02589", "TĐ", "TĐ", "N"],
    [2, "Hứa Quang Trung", "VAE02481", "A864-FM", "A864-FM", "A871-FM"],
]
# Squad 2: has a Category column; also lists VAE02589 (a duplicate of Squad 1's person), dates Oct 1-3.
SQUAD2 = [
    ["ROSTER"],
    ["NO.", "NAME & SURNAME", "ID", "Category"] + [serial(n) for n in (1, 2, 3)],
    [1, "Nguyễn Thành Vũ", "VAE02589", "B1", "A1", "A1", "A1"],
    [2, "Lê Hữu Toàn", "VAE01240", "B1", "A611", "A611", "N"],
]
# Squad 3: dates Oct 2-4, a reinforcement block and summary rows below the crew.
SQUAD3 = [
    ["ROSTER ĐỘI 3 THÁNG 10.2026"],
    ["CHECK AIRBUS"],
    ["NO.", "NAME & SURNAME", "ID", "Category"] + [serial(n) for n in (2, 3, 4)],
    [1, "Phan Minh Khoa", "VAE02012", "B1", "TĐ", "TĐ", "N"],
    [2, "Trần Đức Trung", "VAE03274", "B1/FM", "A326-FM", "A326-FM", "A326-FM"],
    [N, "NV TĂNG CƯỜNG"],
    [1, "Người Tăng Cường", "VAE09999", "B1", "N", "N", "N"],
    [N, "Nhân lực thiếu", N, N, 3, 4, 5],
]


def load(sources):
    d._cache.clear()
    d.configured_urls = lambda: list(URLS)

    def open_source(url):
        s = sources[URLS.index(url)]
        if isinstance(s, Exception):
            raise s
        return s

    d.open_source = open_source


def workbook(i, roster, colors=None):
    return FakeSource(f"sq{i}", {"ROSTER": roster, "1": day_tab()}, {"ROSTER": colors} if colors else None)


def squads(**kw):
    return [
        workbook(1, SQUAD1),
        workbook(2, SQUAD2),
        workbook(3, SQUAD3, kw.get("colors")),
        kw.get("squad4", ValueError("boom: not shared with the service account")),
    ]


def test_merges_the_four_first_sheets():
    load(squads())
    p = squad_roster.build_squads_roster(force=True)
    assert p["ok"] and p["view"] == "squads"
    assert p["dates"] == [f"2026-10-{n:02d}" for n in (1, 2, 3, 4)]  # union of every squad's dates
    assert p["info_headers"] == ["Đội", "Category"]
    ids = [e["id"] for e in p["employees"]]
    # Squad 1, then 2 (its duplicate of VAE02589 dropped), then 3 (reinforcement + summary rows dropped)
    assert ids == ["VAE02589", "VAE02481", "VAE01240", "VAE02012", "VAE03274"]
    assert p["employees"][0]["info"] == ["Squad 1", ""]  # the duplicate stays in the first squad
    assert any("1 employee" in w for w in p["warnings"])


def test_squad1_name_header_hidden_under_the_logo():
    load(squads())
    p = squad_roster.build_squads_roster(force=True)
    e = p["employees"][0]
    assert e["name"] == "Nguyễn Thành Vũ"  # read from the column left of ID
    assert e["cells"] == ["TĐ", "TĐ", "N", ""]  # Oct 4 isn't in Squad 1's dates: blank


def test_cells_align_to_the_union_of_dates_and_keep_colors():
    # font colours of Squad 3's grid: red on row 3 ('Phan Minh Khoa'), column 4 (his Oct 2 cell)
    colors = [[N] * 7 for _ in range(3)] + [[N, N, N, N, "FF0000", N, N]]
    load(squads(colors=colors))
    p = squad_roster.build_squads_roster(force=True)
    khoa = next(e for e in p["employees"] if e["id"] == "VAE02012")
    assert khoa["info"] == ["Squad 3", "B1"]
    assert khoa["cells"] == ["", "TĐ", "TĐ", "N"]  # Squad 3 starts on Oct 2
    assert khoa["colors"][1] == "FF0000" and khoa["colors"][2] is None


def test_unreadable_squad_is_reported_and_the_rest_still_show():
    load(squads())
    p = squad_roster.build_squads_roster(force=True)
    assert [x["name"] for x in p["errors"]] == ["Squad 4"]
    assert "boom" in p["errors"][0]["error"]
    assert [s["name"] for s in p["sources"] if not s["error"]] == ["Squad 1", "Squad 2", "Squad 3"]
    assert p["sheet_url"] == URLS[0]


def test_api_roster_serves_the_squads_and_never_needs_the_khdt_sheet():
    import app as web

    load(squads())
    client = web.app.test_client()
    j = client.get("/api/roster?refresh=1").get_json()  # no url/gid: the squads, not the KHDT sheet
    assert j["ok"] and j["view"] == "squads" and len(j["employees"]) == 5
    assert j["tabs"] == [] and j["errors"][0]["name"] == "Squad 4"


def test_every_squad_failing_is_an_error():
    load([ValueError("a"), ValueError("b"), ValueError("c"), ValueError("d")])
    try:
        squad_roster.build_squads_roster(force=True)
    except ValueError as e:
        assert "Couldn't read any squad roster" in str(e)
    else:
        raise AssertionError("expected ValueError")


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
