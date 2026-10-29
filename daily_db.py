"""
daily_db.py
===========
The "database" day-sheet format that the edit functions create (Phase 4 of "Login and Linked Editing Plan").

Instead of imitating the hand-made day tabs (info block, two tables side by side, section titles), an edit
writes one flat sheet per aircraft and day:

    tab name   <A/C>-<MON><DD>        e.g. A123-OCT29   (the same pattern distribution.parse_tab_name reads)
    row 1      Name | VAEID | Function | Zone | remark
    row 2 ...  one person per row

  Function  the person's POS (position) value, e.g. 'B1'
  Zone      the zone value, exactly as a section title reads on the hand-made tabs ('A864-34', 'ZONE 128');
            empty = not placed in a zone yet (shown as UNASSIGNED)

This module is pure (no Google calls): the reader (`read_grid`, `to_sections`, used by
distribution.parse_day so the Daily Distribution page shows these tabs), the helpers that change a list of
records (`with_person`, `without_person`) and `diff_writes`, which turns "the tab should now look like this"
into the exact cell writes (the plan objects of assignments.py). sheets_client does the real writing.
"""

import re
from datetime import date

import distribution as dist
from engine import normalize_id

HEADERS = ("Name", "VAEID", "Function", "Zone", "remark")
KEYS = ("name", "id", "pos", "zone", "remark")  # same order as HEADERS
MAX_RECORDS = 500  # a day tab is one aircraft's crew; also keeps the sheet well inside its default size
MAX_ZONE_LEN = 48  # the hand-made tabs treat longer text as a note, not a title

_LABELS = {
    "name": {"name", "ho ten", "ho va ten", "name and surname"},
    "id": {"vaeid", "vae id", "vaeco id", "id"},
    "pos": {"function", "pos", "position"},
    "zone": {"zone"},
    "remark": {"remark", "remarks", "ghi chu", "note", "notes"},
}
_MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


# ------------------------------------------------------------------ names
def tab_name(aircraft, day):
    """('A123', date(2026, 10, 29)) -> 'A123-OCT29'; days below 10 are zero-padded ('A611-OCT06')."""
    ac = re.sub(r"\s+", "", str(aircraft or "")).upper()
    if not ac:
        raise ValueError("the aircraft is empty")
    return f"{ac}-{_MON[day.month - 1]}{day.day:02d}"


def a1(row, col):
    letters, n = "", col + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


# ------------------------------------------------------------------ reader
def header_map(row):
    """{key: column} when `row` is this format's header row (Name, VAEID, Function, Zone [, remark]), else None.
    Order does not matter and the labels are matched ignoring case and accents; all four of name, VAEID,
    Function and Zone must be there, so a hand-made tab is never mistaken for this format."""
    cols = {}
    for c, cell in enumerate(row or []):
        f = dist.fold(cell)
        for key, labels in _LABELS.items():
            if f in labels and key not in cols:
                cols[key] = c
                break
    return cols if all(k in cols for k in ("name", "id", "pos", "zone")) else None


def read_grid(values):
    """None when `values` is not a database-style tab, else {"cols": {key: col}, "records": [...]} where a
    record is {"row", "name", "id", "pos", "zone", "remark"} (row is 0-indexed). Only rows 2.. count; a row
    needs a name or an ID."""
    if not values:
        return None
    cols = header_map(values[0])
    if cols is None:
        return None
    records = []
    for r in range(1, len(values)):
        row = values[r]

        def cell(key, row=row):
            c = cols.get(key)
            return dist.text(row[c]) if c is not None and c < len(row) else ""

        rec = {"row": r, "name": cell("name"), "id": normalize_id(cell("id")), "pos": cell("pos"),
               "zone": re.sub(r"\s+", " ", cell("zone")), "remark": cell("remark")}
        if rec["name"] or rec["id"]:
            records.append(rec)
    return {"cols": cols, "records": records}


def to_sections(records, phones=None, unassigned="UNASSIGNED"):
    """Records -> the sections distribution.parse_day returns ({title, kind, time, people}), one per zone in
    order of first appearance; people without a zone go in `unassigned`."""
    phones = phones or {}
    order, by_title = [], {}
    for rec in records:
        title = (rec["zone"] or unassigned).upper()
        if title not in by_title:
            by_title[title] = []
            order.append(title)
        people = by_title[title]
        people.append({"ord": len(people) + 1, "name": rec["name"], "id": rec["id"], "pos": rec["pos"],
                       "phone": phones.get(rec["id"], ""), "remark": rec["remark"], "red": False})
    out = []
    for title in order:
        tm = dist.TIME_RE.search(title)
        out.append({
            "title": title,
            "kind": "zone" if dist.fold(title).startswith("zone") or dist.ZONE_TITLE_RE.match(title) else "other",
            "time": f"{int(tm.group(1)):02d}H{tm.group(2)}" if tm else None,
            "people": by_title[title],
        })
    return out


# ------------------------------------------------------------------ changing records (pure)
def without_person(records, emp_id):
    """(records without that ID, number removed)."""
    kept = [r for r in records if r["id"] != emp_id]
    return kept, len(records) - len(kept)


def with_person(records, emp, zone=None, pos=""):
    """(new records, note). The person is added at the end, or updated in place when already listed.
    `zone` None = leave an existing zone alone (a new row then has none); '' = clear it; text = set it.
    An existing Function / remark is never overwritten (`pos` only fills a blank Function)."""
    zone = None if zone is None else re.sub(r"\s+", " ", str(zone)).strip()
    if zone is not None and len(zone) > MAX_ZONE_LEN:
        raise ValueError(f"the zone is longer than {MAX_ZONE_LEN} characters")
    out = [dict(r) for r in records]
    for r in out:
        if r["id"] == emp["id"]:
            before = dict(r)
            if zone is not None:
                r["zone"] = zone
            if not r["pos"] and pos:
                r["pos"] = pos
            if not r["name"]:
                r["name"] = emp["name"]
            return out, (None if r == before else "updated")
    if len(out) >= MAX_RECORDS:
        raise ValueError(f"the tab already lists {MAX_RECORDS} people")
    out.append({"row": None, "name": emp["name"], "id": emp["id"], "pos": pos, "zone": zone or "", "remark": ""})
    return out, "added"


# ------------------------------------------------------------------ records -> cell writes
def grid_of(records, cols=None):
    """{(row, col): text} for the data rows (row 0 is the header) of the given records."""
    cols = cols or {k: i for i, k in enumerate(KEYS)}
    cells = {}
    for i, rec in enumerate(records):
        for key in KEYS:
            if key in cols:
                cells[(i + 1, cols[key])] = str(rec.get(key) or "")
    return cells


def diff_writes(tab, values, records, cols=None):
    """Cell writes that turn the tab's current data rows into `records` (header row untouched). Everything
    below the last record is blanked, so removing a person moves the rows below up. A write is
    {"sheet": "day", "tab", "row", "col", "a1", "old", "new"}; a tab that does not exist yet has no `values`."""
    cols = cols or {k: i for i, k in enumerate(KEYS)}
    want = grid_of(records, cols)
    height = max(len(values or []), len(records) + 1)
    writes = []
    for r in range(1, height):
        for key in KEYS:
            if key not in cols:
                continue
            c = cols[key]
            old = dist.text(values[r][c]) if values and r < len(values) and c < len(values[r]) else ""
            new = want.get((r, c), "")
            if old != new:
                writes.append({"sheet": "day", "tab": tab, "row": r, "col": c, "a1": a1(r, c), "old": old, "new": new})
    return writes


def new_tab_rows():
    """The first row of a tab this module creates."""
    return [list(HEADERS)]


def date_of(tab, ref=None):
    """The date a day tab's name stands for (None when it is not a day tab)."""
    parsed = dist.parse_tab_name(tab, ref or date.today())
    return parsed[1] if parsed else None
