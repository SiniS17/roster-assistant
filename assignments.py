"""
assignments.py
==============
The link between a squad's roster cell and its Daily Distribution day tab (Phase 3 of "Login and Linked
Editing Plan"). DRY-RUN ONLY: this module reads, plans and reports the exact cells it WOULD write; it has
no function that writes to Google. Phases 4/5 will add the writing behind the same plan objects.

Two kinds of intent go in:

  {"origin": "roster", "squad": 0, "id": "VAE02591", "date": "2026-10-06",
   "kind": "code" | "n" | "forced" | "clear", "value": "A864-34", "old": "<cell text the page saw, optional>"}
      a roster cell is edited (same shape as roster_edit.save()); the day tab follows.

  {"origin": "daily", "squad": 0, "id": "VAE02591", "date": "2026-10-06", "tab": "6",
   "to": "A864-34" | "UNASSIGNED" | null}
      a person is moved into a section of a day tab (null = taken out of the distribution); the roster follows.

A plan is {"status", "blocked", "roster": [writes], "day": [writes], "notes": [...], ...}; a write is
{"sheet": "roster"|"day", "tab", "row", "col", "a1", "old", "new"} (0-indexed row/col).
status: "ok" (both sides), "roster_only" (the day tab could not follow, see notes), "noop" (already
consistent), "blocked" (nothing would be written, see "blocked").

Rules (from the plan, section 3 and 4):
  * Per-squad layout adapters (config.DISTRIBUTION_SQUAD_LAYOUTS): "zone" squads (1/4) keep aircraft + zone
    in the roster and a section with the same title on the day tab; "aircraft" squads (2/3) keep only the
    aircraft in the roster, the zone lives on the day tab, so a roster edit puts the person in an
    UNASSIGNED section until somebody moves them to a zone.
  * Normal N (and clearing a cell) takes the person off that day's distribution. Role codes (TĐ/PPC/FM),
    course markers and shift codes ('@16H00') are not linked.
  * Day-tab writes only fill or clear cell values inside a table's own columns: never insert or delete rows.
    A person goes into the first free row of the section; a missing section is appended at the bottom of a
    table; no free row = the day side cannot follow. Removing someone blanks the whole row (ORD included: a
    row holding only an ORD number would be read by distribution.parse_day as a section title).
  * Locked roster cells (KHDT course marker, red N) are never planned for a write.
  * Roster-origin: the roster is the primary side, the day tab best effort (status "roster_only" when it
    cannot follow, e.g. no day tab for that date: tabs are never created). Daily-origin: all or nothing.
  * One code per cell; two aircraft in a day and '@16H00' shifts are out of scope (dismissed on purpose).

Phase 4 (this file now also WRITES, through commit()): with config.DAILY_WRITE_FORMAT = "database" (the
default) the day side is not the hand-made day tab but a flat tab per aircraft and day, 'A123-OCT29', with
row 1 = Name | VAEID | Function | Zone | remark and one person per row (daily_db.py). Differences from the
rules above, all for that format:
  * a roster edit to 'A123' (or 'A123-34') puts the person on tab 'A123-<MON><DD>' of that date, creating the
    tab when it does not exist; Function = the person's POS value as found on the other tabs of that date
    (kept when already there); Zone = the section title ('A864-34') when the code has a zone, else left
    empty (UNASSIGNED) or as it was. The person leaves their row on every other database tab of that date.
  * Normal N / Clear removes the person from every database tab of that date; removing a row moves the
    rows below up (the tab is a flat table, nothing else is next to it).
  * Hand-made day tabs are never written in this mode, not even when one has the same name: the plan says
    why ("roster_only"). Daily-origin moves only work on database tabs.
commit() writes roster first, then creates missing tabs, then the day cells, and reports a partial failure.
"""

import copy
import logging
import re
from datetime import date as _date

import auth
import daily_db
import distribution as dist
import khdt_review
import roster_edit
import sheets_client
from config import (
    DAILY_WRITE_FORMAT,
    DISTRIBUTION_ROLE_MARKERS,
    DISTRIBUTION_SQUAD_LAYOUTS,
    LINK_REMOVE_CLEARS_ROSTER,
    LINK_UNASSIGNED_TITLE,
)
from engine import is_course_marker, is_red_n, normalize_id

log = logging.getLogger(__name__)

MAX_INTENTS = 200
MAX_APPEND_ROWS = 60  # how far below the last used row a table may be extended (rows the sheet must have)
BLACK = "000000"
AIRCRAFT_RE = re.compile(r"^(?P<ac>[A-Z]{1,3}\d{2,4})(?:\s*[-\u2013]\s*(?P<zone>\S.*))?$")


class Blocked(Exception):
    """The intent cannot be planned at all (the reason is shown to the person)."""


class DaySkip(Exception):
    """The day tab cannot follow (the roster side may still be written)."""


# ------------------------------------------------------------------ small helpers
def a1(row, col):
    letters, n = "", col + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


def _cell(values, r, c):
    return values[r][c] if 0 <= r < len(values) and 0 <= c < len(values[r]) else None


def _set(values, r, c, v):
    """Set a cell, growing the grid when the row/column is past the data the API returned."""
    while len(values) <= r:
        values.append([])
    row = values[r]
    if len(row) <= c:
        row.extend([None] * (c + 1 - len(row)))
    row[c] = v if v != "" else None


def title_key(s):
    """Section titles compare ignoring case, accents, spacing and the kind of dash."""
    return re.sub(r"\s*[-\u2013\u2014]\s*", "-", dist.fold(s))


def role_tokens():
    return {dist.fold(m) for m in DISTRIBUTION_ROLE_MARKERS.values() if dist.fold(m)}


def parse_code(value):
    """Classify a roster cell: empty | n | course | role | aircraft (+aircraft, zone) | other."""
    t = re.sub(r"\s+", " ", str(value or "")).strip()
    if not t:
        return {"kind": "empty", "text": ""}
    if t.upper() == "N":
        return {"kind": "n", "text": t}
    if is_course_marker(t):
        return {"kind": "course", "text": t}
    if "@" in t:  # '@16H00' shifts are not linked
        return {"kind": "other", "text": t}
    if set(re.split(r"[^a-z0-9]+", dist.fold(t))) & role_tokens():
        return {"kind": "role", "text": t}
    m = AIRCRAFT_RE.match(t.upper())
    if m:
        zone = (m.group("zone") or "").strip() or None
        return {"kind": "aircraft", "text": t.upper(), "aircraft": m.group("ac"), "zone": zone}
    return {"kind": "other", "text": t}


# ------------------------------------------------------------------ layout adapters
class ZoneLayout:
    """Squads 1/4: roster 'A864-34' <-> section 'A864-34' on the (numbered) day tab."""

    name = "zone"
    relocate = True  # a roster change moves the person to the section matching the new code

    def tab_for(self, days, code):
        if not days:
            return None, "there is no day tab for that date"
        return days[0]["tab"], None

    def section_for(self, code):
        """Title of the section the person belongs in, or None (= the UNASSIGNED section)."""
        return f"{code['aircraft']}-{code['zone']}" if code.get("zone") else None

    def roster_code(self, title, tab_ac, live):
        """(code to write in the roster | None = leave it, note | None) for a person placed under `title`."""
        if title is None:  # no zone: keep the aircraft only
            ac = live.get("aircraft") if live["kind"] == "aircraft" else tab_ac
            return (ac, None) if ac else (None, "no aircraft is known for this tab; roster left as it is")
        c = parse_code(title)
        if c["kind"] == "aircraft":
            return c["text"], None
        return None, f"section '{title}' has no aircraft code; roster left as it is"


class AircraftLayout:
    """Squads 2/3: roster 'A611'; the zone only exists on the day tab ('A611-OCT06' > 'ZONE 128')."""

    name = "aircraft"
    relocate = False  # a person already listed in some zone of the right tab stays where they are

    def tab_for(self, days, code):
        if not days:
            return None, "there is no day tab for that date"
        same = [d for d in days if dist.fold(d["ac"]) == dist.fold(code["aircraft"])]
        if same:
            return same[0]["tab"], None
        return None, (f"there is no day tab for aircraft {code['aircraft']} on that date "
                      f"(tabs that day: {', '.join(d['tab'] for d in days)})")

    def section_for(self, code):
        return None  # the zone is chosen on the day tab later

    def roster_code(self, title, tab_ac, live):
        if not tab_ac:
            return None, "no aircraft is known for this tab; roster left as it is"
        if live["kind"] == "aircraft" and live["aircraft"] == tab_ac.upper():
            return None, None  # the roster already names this aircraft (zone is not kept in the roster)
        return tab_ac.upper(), None


LAYOUTS = {"zone": ZoneLayout(), "aircraft": AircraftLayout()}


def layout_for(index):
    names = list(DISTRIBUTION_SQUAD_LAYOUTS or [])
    name = names[index] if index < len(names) else "aircraft"
    if name not in LAYOUTS:
        raise ValueError(f"Unknown layout '{name}' for squad {index + 1} (use 'zone' or 'aircraft').")
    return LAYOUTS[name]


# ------------------------------------------------------------------ locating cells on a day tab
def _is_blank(values, r, table):
    return all(not dist.text(_cell(values, r, c)) for k, c in table["cols"].items() if k != "ord")


def locate_day(values):
    """Where everything sits on a day tab, mirroring distribution.parse_day (same headers, same person and
    section rules) but keeping row numbers: {"tables": [{cols, left, right, end, open_end, sections:[
    {title, title_row, first_row, stop, people:[{row, id, name}]}]}]}."""
    headers = dist._find_headers(values)
    tables = []
    for hi, h in enumerate(headers):
        end = len(values)
        for h2 in headers[hi + 1:]:
            if h2["name"] == h["name"]:
                end = h2["row"]
                break
        cols = {k: c for k, c in h.items() if k != "row"}
        table = {"header_row": h["row"], "cols": cols, "left": min(cols.values()), "right": max(cols.values()),
                 "end": end, "open_end": end == len(values), "sections": []}
        current = None
        for r in range(h["row"] + 1, end):
            row = values[r]
            if dist._is_person_row(row, h):
                if current is None:
                    current = {"title": "", "title_row": None, "first_row": r, "people": []}
                    table["sections"].append(current)
                current["people"].append({
                    "row": r,
                    "id": normalize_id(dist.text(_cell(values, r, h["id"]))),
                    "name": dist.text(_cell(values, r, h["name"])),
                })
                continue
            filled = [(c, dist.text(row[c])) for c in range(table["left"], min(table["right"] + 1, len(row)))
                      if dist.text(row[c])]
            cells = [t for _, t in filled]
            if (filled and filled[0][0] <= h["name"] and len(cells[0]) <= 48
                    and not any(dist.fold(x) in dist._ID_LABELS | dist._NAME_LABELS for x in cells)):
                current = {"title": re.sub(r"\s+", " ", cells[0]), "title_row": r, "first_row": r + 1, "people": []}
                table["sections"].append(current)
        secs = table["sections"]
        for i, s in enumerate(secs):
            nxt = secs[i + 1] if i + 1 < len(secs) else None
            s["stop"] = (nxt["title_row"] if nxt["title_row"] is not None else nxt["first_row"]) if nxt else end
        tables.append(table)
    return {"tables": tables}


def _free_rows(values, table, sec):
    """Rows inside the section's own bounds where a person can be written (all data columns blank)."""
    start = sec["title_row"] + 1 if sec["title_row"] is not None else sec["first_row"]
    rows = list(range(start, sec["stop"]))
    if table["open_end"] and sec is table["sections"][-1]:
        rows += range(sec["stop"], sec["stop"] + MAX_APPEND_ROWS)  # below the data the API returned
    return [r for r in rows if _is_blank(values, r, table)]


def _last_used(values, table):
    last = table["header_row"]
    for r in range(table["header_row"] + 1, table["end"]):
        if any(dist.text(_cell(values, r, c)) for c in range(table["left"], table["right"] + 1)):
            last = r
    return last


def _find_section(loc, title):
    for t in loc["tables"]:
        for s in t["sections"]:
            if s["title"] and title_key(s["title"]) == title_key(title):
                return t, s
    return None, None


def _find_person(loc, emp_id):
    """[(table, section, person)] for every row carrying this ID."""
    return [(t, s, p) for t in loc["tables"] for s in t["sections"] for p in s["people"] if p["id"] == emp_id]


# ------------------------------------------------------------------ context (what a plan reads)
def _ac_of_tab(ctx, day):
    if day.get("ac"):
        return day["ac"]
    info, _, _ = dist.parse_info(_grid(ctx, day["tab"]))
    return info["ac"]


def _grid(ctx, tab):
    """A private copy of the day tab's values, so planned writes of earlier intents are seen by later ones."""
    g = ctx["_grids"]
    if tab not in g:
        values, _colors = ctx["day_grid"](tab)
        g[tab] = copy.deepcopy(values)
    return g[tab]


def make_context(index, sq, days, day_grid, phones=None, layout=None):
    """sq: a squad as khdt_review._load_squad returns it (values, colors, header_row, id_col, name_col,
    date_cols, cutoff, title). days: distribution meta 'days' ([{tab, ac, date}]). day_grid(tab) -> (values, colors)."""
    sq = dict(sq)
    sq["values"] = copy.deepcopy(sq["values"])
    sq["colors"] = copy.deepcopy(sq["colors"])
    return {"index": index, "sq": sq, "days": days, "day_grid": day_grid, "phones": phones or {},
            "layout": layout or layout_for(index), "_grids": {},
            "col_of_date": {d.isoformat(): c for d, c in sq["date_cols"].items()}}


def load_context(index, force=True):
    """The real thing: fresh read of the squad's roster, its day-tab list and (lazily) its day tabs."""
    sq = khdt_review._load_squad(index, force)
    meta = dist.meta_for(index, force)
    if meta.get("error"):
        raise ValueError(meta["error"])
    src = sq["src"]
    _, phones, _ = dist.parse_info(dist._first_sheet_values(index, force, src))
    return make_context(index, sq, meta["days"], lambda tab: dist._grid(index, tab, force, src), phones)


# ------------------------------------------------------------------ building writes
def _roster_write(ctx, update, old):
    return {"sheet": "roster", "tab": ctx["sq"]["title"], "row": update["row"], "col": update["col"],
            "a1": a1(update["row"], update["col"]), "old": old, "new": update["value"],
            "color": update.get("color") or BLACK}


def _day_write(tab, r, c, old, new):
    return {"sheet": "day", "tab": tab, "row": r, "col": c, "a1": a1(r, c), "old": old, "new": new}


def _clear_row(values, tab, table, r):
    """Blank every filled cell of the row inside the table's columns (ORD too, see the module docstring)."""
    return [_day_write(tab, r, c, dist.text(_cell(values, r, c)), "")
            for c in table["cols"].values() if dist.text(_cell(values, r, c))]


def _person_cells(ctx, tab, values, table, sec, r, emp):
    """Writes that fill row r of `table` with the employee (ORD only when its cell is blank)."""
    cols, out = table["cols"], []
    if "ord" in cols and not dist.text(_cell(values, r, cols["ord"])):
        nums = [v for v in (_cell(values, p["row"], cols["ord"]) for p in sec["people"]) if isinstance(v, (int, float))]
        out.append(_day_write(tab, r, cols["ord"], "", str(int(max(nums)) + 1 if nums else len(sec["people"]) + 1)))
    out.append(_day_write(tab, r, cols["name"], "", emp["name"]))
    out.append(_day_write(tab, r, cols["id"], "", emp["id"]))
    phone = ctx["phones"].get(emp["id"], "")
    if "phone" in cols and phone:
        out.append(_day_write(tab, r, cols["phone"], "", phone))
    return out


def _sec_id(table, sec):
    """A section's identity that survives re-reading the grid (locate_day builds fresh dicts every time)."""
    return (table["left"], sec["title_row"], sec["first_row"])


def _removal(ctx, plan, tab, emp, keep=None):
    """Writes that take the employee off one day tab (every row carrying the ID, except in section `keep`
    = a _sec_id)."""
    values = _grid(ctx, tab)
    loc = locate_day(values)
    out = []
    for table, sec, p in _find_person(loc, emp["id"]):
        if keep is not None and _sec_id(table, sec) == keep:
            continue
        out += _clear_row(values, tab, table, p["row"])
        plan["notes"].append(f"day tab '{tab}': removed from '{sec['title'] or '(no title)'}' (row {p['row'] + 1})")
    return out


def _place(ctx, plan, tab, title, emp, relocate, may_create):
    """Writes that put the employee under `title` on `tab` (first free row of that section, or a new section
    appended at the bottom of a table). DaySkip when it cannot be done without inserting rows."""
    values = _grid(ctx, tab)
    loc = locate_day(values)
    table, sec = _find_section(loc, title)
    present = _find_person(loc, emp["id"])
    if sec is not None and any(s is sec for _, s, _ in present):
        plan["notes"].append(f"day tab '{tab}': already listed under '{sec['title']}'")
        return _removal(ctx, plan, tab, emp, keep=_sec_id(table, sec)) if relocate else []
    if present and not relocate:
        plan["notes"].append(f"day tab '{tab}': already listed under '{present[0][1]['title'] or '(no title)'}'; "
                             "the zone is left as it is")
        return []
    out = _removal(ctx, plan, tab, emp) if present else []
    if sec is not None:
        free = _free_rows(values, table, sec)
        if not free:
            raise DaySkip(f"no free row in section '{sec['title']}' on tab '{tab}' (rows are never inserted)")
        out += _person_cells(ctx, tab, values, table, sec, free[0], emp)
        plan["notes"].append(f"day tab '{tab}': added to '{sec['title']}' (row {free[0] + 1})")
        return out
    if not may_create:
        raise DaySkip(f"section '{title}' does not exist on tab '{tab}'")
    best = None
    for t in loc["tables"]:
        last = _last_used(values, t)
        rows = (last + 1, last + 2)
        if t["open_end"] or rows[1] < t["end"]:
            if all(_is_blank(values, r, t) and not dist.text(_cell(values, r, t["cols"]["name"])) for r in rows):
                if best is None or last < best[0]:
                    best = (last, t)
    if best is None:
        raise DaySkip(f"no room to add a section '{title}' on tab '{tab}' (rows are never inserted)")
    last, t = best
    title_row, person_row = last + 1, last + 2
    out.append(_day_write(tab, title_row, t["cols"]["name"], "", title))
    fake = {"people": []}
    out += _person_cells(ctx, tab, values, t, fake, person_row, emp)
    plan["notes"].append(f"day tab '{tab}': new section '{title}' appended at row {title_row + 1} "
                         "(the sheet needs rows down to that point)")
    return out


def _days_on(ctx, date_iso):
    return [d for d in ctx["days"] if d["date"] == date_iso]


# ------------------------------------------------------------------ database-style day tabs (Phase 4)
def _db_mode():
    return DAILY_WRITE_FORMAT == "database"


def _real_tab(ctx, tab):
    """The tab's real name when the spreadsheet already has it (tab names are case-insensitive), else None."""
    return next((d["tab"] for d in ctx["days"] if dist.fold(d["tab"]) == dist.fold(tab)), None)


def _db_tabs(ctx, date_iso):
    """[(tab, db)] for the day tabs of that date that are in the database layout (hand-made ones are skipped)."""
    out = []
    for d in _days_on(ctx, date_iso):
        db = daily_db.read_grid(_grid(ctx, d["tab"]))
        if db is not None:
            out.append((d["tab"], db))
    return out


def _function_of(ctx, emp_id, date_iso):
    """The person's POS value as listed on any day tab of that date ('' when nobody lists them); database
    tabs (what the edit functions wrote last) come before hand-made ones."""
    days = sorted(_days_on(ctx, date_iso), key=lambda d: daily_db.read_grid(_grid(ctx, d["tab"])) is None)
    for d in days:
        try:
            sections = dist.parse_day(_grid(ctx, d["tab"]), [])
        except ValueError:  # a tab without a table
            continue
        for s in sections:
            for p in s["people"]:
                if p["id"] == emp_id and p["pos"]:
                    return p["pos"]
    return ""


def _db_remove(ctx, plan, tab, emp):
    values = _grid(ctx, tab)
    db = daily_db.read_grid(values)
    if db is None:
        return []
    records, n = daily_db.without_person(db["records"], emp["id"])
    if not n:
        return []
    plan["notes"].append(f"day tab '{tab}': removed from the tab")
    return daily_db.diff_writes(tab, values, records, db["cols"])


def _db_place(ctx, plan, tab, emp, zone, date_iso):
    """Writes that list the employee on database tab `tab` (created when the spreadsheet has none of that
    name). zone None = keep the zone as it is. DaySkip when the tab exists in another layout."""
    existing = _real_tab(ctx, tab)
    if existing:
        values = _grid(ctx, existing)
        db = daily_db.read_grid(values)
        if db is None:
            raise DaySkip(f"tab '{existing}' already exists in the hand-made layout; it is left as it is "
                          "(only Name | VAEID | Function | Zone | remark tabs are written)")
        tab, records, cols = existing, db["records"], db["cols"]
    else:
        values, records, cols = [], [], None
        plan["create_tabs"].append({"tab": tab, "date": date_iso, "ac": tab.split("-")[0]})
    pos = next((r["pos"] for r in records if r["id"] == emp["id"] and r["pos"]), "") or _function_of(ctx, emp["id"], date_iso)
    try:
        new, what = daily_db.with_person(records, emp, zone, pos)
    except ValueError as e:
        raise DaySkip(str(e))
    if what is None:
        plan["notes"].append(f"day tab '{tab}': already listed, nothing to change")
        return []
    plan["notes"].append(f"day tab '{tab}': {'new tab created, ' if not existing else ''}person {what}"
                         + (f" (zone '{zone}')" if zone else ""))
    return daily_db.diff_writes(tab, values, new, cols)


# ------------------------------------------------------------------ roster -> daily
def _roster_to_db(ctx, plan, intent, emp, new):
    """The day side of a roster edit when the day tabs are database-style (see the module docstring)."""
    date_iso, out = intent["date"], []
    tabs = _db_tabs(ctx, date_iso)
    if new["kind"] in ("empty", "n"):
        for tab, _db in tabs:
            out += _db_remove(ctx, plan, tab, emp)
        if not out:
            plan["notes"].append("not listed on any database day tab that day: nothing to remove")
        return out
    if new["kind"] != "aircraft":
        plan["notes"].append(f"'{new['text']}' is a {new['kind']} code: not linked to the Daily Distribution")
        return out
    day = _date.fromisoformat(date_iso)
    tab = daily_db.tab_name(new["aircraft"], day)
    zone = f"{new['aircraft']}-{new['zone']}" if new.get("zone") else None
    placed = _db_place(ctx, plan, tab, emp, zone, date_iso)  # may raise DaySkip: then nothing is removed either
    for other, _db in tabs:  # a person is on one aircraft per day
        if dist.fold(other) != dist.fold(tab):
            out += _db_remove(ctx, plan, other, emp)
    return out + placed


def _from_roster(ctx, intent, plan, emp, live):
    sq, layout = ctx["sq"], ctx["layout"]
    edit = dict(intent)
    if edit.get("old") is None:
        edit["old"] = live["raw"]
    update, why = roster_edit.check(sq, ctx["col_of_date"], edit)
    if why and why != "no change":
        raise Blocked(why)
    if update:
        plan["roster"].append(_roster_write(ctx, update, live["raw"]))
    new = parse_code(update["value"] if update else live["raw"])
    dates_days = _days_on(ctx, intent["date"])
    n_notes, n_create = len(plan["notes"]), len(plan["create_tabs"])
    try:
        out = []
        if _db_mode():
            out = _roster_to_db(ctx, plan, intent, emp, new)
        elif new["kind"] in ("empty", "n"):
            for d in dates_days:
                out += _removal(ctx, plan, d["tab"], emp)
            if not out:
                plan["notes"].append("not listed on any day tab that day: nothing to remove")
        elif new["kind"] != "aircraft":
            plan["notes"].append(f"'{new['text']}' is a {new['kind']} code: not linked to the Daily Distribution")
        else:
            tab, why = layout.tab_for(dates_days, new)
            if tab is None:
                raise DaySkip(why)
            if update:  # the aircraft changed: take the person off the other tabs of that day
                for d in dates_days:
                    if d["tab"] != tab:
                        out += _removal(ctx, plan, d["tab"], emp)
            out += _place(ctx, plan, tab, layout.section_for(new) or LINK_UNASSIGNED_TITLE, emp,
                          relocate=layout.relocate, may_create=True)
        plan["day"] += out
    except DaySkip as s:
        del plan["notes"][n_notes:]  # notes about writes that will not happen would mislead
        del plan["create_tabs"][n_create:]
        plan["day_skipped"] = str(s)
        plan["notes"].append(f"day tab not updated: {s}")


# ------------------------------------------------------------------ daily -> roster
def _from_daily(ctx, intent, plan, emp, live, color):
    sq, layout = ctx["sq"], ctx["layout"]
    tab = str(intent.get("tab") or "")
    day = next((d for d in ctx["days"] if d["tab"] == tab and d["date"] == intent["date"]), None)
    if day is None:
        raise Blocked(f"'{tab}' is not a day tab for {intent['date']}")
    to = intent.get("to")
    to = None if to in (None, "") else str(to).strip()
    db_mode = _db_mode()
    if db_mode and daily_db.read_grid(_grid(ctx, tab)) is None:
        raise Blocked(f"'{tab}' is a hand-made day tab: only Name | VAEID | Function | Zone | remark tabs can be edited")
    try:
        if to is None:  # taken out of the distribution
            plan["day"] += _db_remove(ctx, plan, tab, emp) if db_mode else _removal(ctx, plan, tab, emp)
            if LINK_REMOVE_CLEARS_ROSTER and live["kind"] == "aircraft":
                update, why = roster_edit.check(sq, ctx["col_of_date"], {
                    "id": emp["id"], "date": intent["date"], "old": live["raw"], "kind": "clear"})
                if why:
                    raise Blocked(why)
                plan["roster"].append(_roster_write(ctx, update, live["raw"]))
            else:
                plan["notes"].append(f"roster cell left as it is ('{live['text'] or 'empty'}')")
            return
        unassigned = title_key(to) == title_key(LINK_UNASSIGNED_TITLE)
        title = LINK_UNASSIGNED_TITLE if unassigned else to
        # Roster side first: a locked or unusable cell stops everything (all or nothing).
        if live["kind"] == "course" or is_red_n(live["text"], color):
            raise Blocked("locked: " + ("a KHDT course marker" if live["kind"] == "course" else "guaranteed day off (red N)"))
        if live["kind"] == "other":
            raise Blocked(f"the roster cell holds '{live['text']}', not an aircraft code - fix the roster first")
        if live["kind"] == "role":
            plan["notes"].append(f"roster cell '{live['text']}' is a role code: left as it is")
        else:
            want, note = layout.roster_code(None if unassigned else title, _ac_of_tab(ctx, day), live)
            if note:
                plan["notes"].append(note)
            if want and want != live["text"]:
                if live["kind"] == "n":
                    plan["notes"].append("replaces a normal day off (N) in the roster")
                update, why = roster_edit.check(
                    sq, ctx["col_of_date"], {"id": emp["id"], "date": intent["date"], "old": live["raw"],
                                             "kind": "code", "value": want})
                if why and why != "no change":
                    raise Blocked(why)
                if update:
                    plan["roster"].append(_roster_write(ctx, update, live["raw"]))
        if db_mode:
            plan["day"] += _db_place(ctx, plan, tab, emp, "" if unassigned else title, intent["date"])
        else:
            plan["day"] += _place(ctx, plan, tab, title, emp, relocate=True, may_create=unassigned)
    except DaySkip as s:
        raise Blocked(str(s))


# ------------------------------------------------------------------ plan + commit
def _apply(ctx, plan):
    """Let later intents of the same batch see what this plan would write."""
    sq = ctx["sq"]
    for w in plan["roster"]:
        _set(sq["values"], w["row"], w["col"], w["new"])
        _set(sq["colors"], w["row"], w["col"], None if w.get("color", BLACK) == BLACK else w["color"])
    for t in plan["create_tabs"]:  # later intents of the batch see the new tab (header row only)
        if _real_tab(ctx, t["tab"]) is None:
            ctx["_grids"][t["tab"]] = daily_db.new_tab_rows()
            ctx["days"].append({"tab": t["tab"], "ac": t["ac"], "note": "", "date": t["date"]})
    for w in plan["day"]:
        _set(_grid(ctx, w["tab"]), w["row"], w["col"], w["new"])


def plan_link(ctx, intent, commit=True):
    """One intent -> a plan (see the module docstring). Never raises for a bad intent: it comes back blocked."""
    plan = {"intent": dict(intent), "squad": ctx["index"], "squadName": dist.configured_names()[ctx["index"]]
            if ctx["index"] < len(dist.configured_names()) else f"Squad {ctx['index'] + 1}",
            "layout": ctx["layout"].name, "status": None, "blocked": None, "id": "", "name": "",
            "roster": [], "day": [], "notes": [], "create_tabs": []}
    try:
        origin, date_iso = intent.get("origin"), str(intent.get("date") or "")
        if origin not in ("roster", "daily"):
            raise Blocked("unknown origin (use 'roster' or 'daily')")
        sq = ctx["sq"]
        eid = normalize_id(intent.get("id"))
        r = roster_edit._row_of(sq, eid)
        if r is None:
            raise Blocked("the employee is not on this squad's roster")
        col = ctx["col_of_date"].get(date_iso)
        if col is None:
            raise Blocked("that date is not on the roster sheet")
        emp = {"id": eid, "name": dist.text(_cell(sq["values"], r, sq["name_col"]))}
        plan["id"], plan["name"] = eid, emp["name"]
        raw = dist.text(_cell(sq["values"], r, col))
        live = dict(parse_code(raw), raw=raw)  # raw = the cell exactly as roster_edit.check compares it
        color = _cell(sq["colors"], r, col)
        if origin == "roster":
            _from_roster(ctx, intent, plan, emp, live)
        else:
            _from_daily(ctx, intent, plan, emp, live, color)
        if not plan["roster"] and not plan["day"] and not plan["create_tabs"]:
            plan["status"] = "noop"
        elif plan.get("day_skipped"):
            plan["status"] = "roster_only"
        else:
            plan["status"] = "ok"
    except Blocked as b:
        plan.update(status="blocked", blocked=str(b), roster=[], day=[], notes=[], create_tabs=[])
    if commit and plan["status"] != "blocked":
        _apply(ctx, plan)
    return plan


def plan_batch(ctx, intents):
    """Plan several intents of one squad in order; each sees the writes planned before it."""
    return [plan_link(ctx, i) for i in intents]


# ------------------------------------------------------------------ entry points
def _plan_intents(intents, user=None):
    """Plan every intent against freshly read sheets (nothing is written).
    -> (plans in the order given, [{squad, name, error}], {squad index: context})"""
    if len(intents) > MAX_INTENTS:
        raise ValueError(f"Too many intents at once ({len(intents)}); the limit is {MAX_INTENTS}.")
    names = dist.configured_names()
    plans = [None] * len(intents)
    by_squad = {}
    for n, it in enumerate(intents):
        try:
            by_squad.setdefault(int(it["squad"]), []).append((n, it))
        except (KeyError, TypeError, ValueError):
            plans[n] = {"intent": it, "status": "blocked", "blocked": "missing or invalid 'squad'", "roster": [],
                        "day": [], "notes": [], "create_tabs": [], "id": str(it.get("id", "")), "name": "",
                        "squad": None, "squadName": "", "layout": ""}
    squads, ctxs = [], {}
    for index, items in sorted(by_squad.items()):
        info = {"squad": index, "name": names[index] if 0 <= index < len(names) else f"Squad {index + 1}", "error": None}
        squads.append(info)
        try:
            if not 0 <= index < len(names):
                raise ValueError("Unknown squad.")
            if user is not None and not auth.can_edit(user, index):
                raise ValueError("You are not allowed to edit this squad.")
            ctx = load_context(index, True)
            ctxs[index] = ctx
            for n, it in items:
                plans[n] = plan_link(ctx, it)
        except Exception as e:  # noqa: BLE001 - one unreadable squad must not hide the others
            info["error"] = f"{type(e).__name__}: {e}"
            ctxs.pop(index, None)
            for n, it in items:
                plans[n] = {"intent": it, "status": "blocked", "blocked": info["error"], "roster": [],
                            "day": [], "notes": [], "create_tabs": [], "id": str(it.get("id", "")), "name": "",
                            "squad": index, "squadName": info["name"], "layout": ""}
    return plans, squads, ctxs


def dry_run(intents, user=None):
    """Plan every intent against freshly read sheets. Nothing is written anywhere.
    -> {"plans": [... in the order given ...], "squads": [{name, error}], "lines": [text]}"""
    plans, squads, _ = _plan_intents(intents, user)
    return {"plans": plans, "squads": squads, "lines": format_plans(plans)}


# ------------------------------------------------------------------ writing (Phase 4)
def _squad_writes(plans):
    """The cells and tabs of the plans that may be written, later writes of one cell winning:
    (roster updates, tabs to create [{tab, ...}], {tab: [cell writes]})."""
    roster, create, day = {}, {}, {}
    for p in plans:
        if p is None or p["status"] in ("blocked", "noop"):
            continue
        for w in p["roster"]:
            roster[(w["row"], w["col"])] = {"row": w["row"], "col": w["col"], "value": w["new"], "color": w.get("color", BLACK)}
        for t in p.get("create_tabs", []):
            create.setdefault(t["tab"], t)
        for w in p["day"]:
            day.setdefault(w["tab"], {})[(w["row"], w["col"])] = {"row": w["row"], "col": w["col"], "value": w["new"]}
    return list(roster.values()), list(create.values()), {t: list(c.values()) for t, c in day.items()}


def _write_squad(ctx, plans):
    """Write one squad: roster cells first, then the missing day tabs, then the day cells. A failure stops
    the remaining steps and is reported with what had already been written (no rollback: Sheets has none)."""
    res = {"squad": ctx["index"], "name": "",
           "roster_written": 0, "day_written": 0, "created_tabs": [], "partial": False, "error": None}
    try:
        if DAILY_WRITE_FORMAT != "database":
            raise ValueError("Writing is only available for the database day-tab format "
                             "(config.DAILY_WRITE_FORMAT = 'database').")
        src = ctx["sq"].get("src")
        if src is None or getattr(src, "kind", "sheets") != "sheets":
            raise ValueError("This squad's file is an uploaded Excel (.xlsx), which can't be edited through "
                             "Google Sheets - convert it to a Google Sheet first.")
        roster, create, day = _squad_writes(plans)
        if roster:
            sheets_client.write_roster_updates(src.id, khdt_review._tab_gid(src.id, ctx["sq"]["title"]), roster)
            res["roster_written"] = len(roster)
        for t in create:
            try:
                sheets_client.add_sheet(src.id, t["tab"], daily_db.HEADERS)
            except sheets_client.TabExists:
                raise ValueError(f"The tab '{t['tab']}' was created by somebody else a moment ago; nothing was "
                                 "written to it. Reload and try again.")
            res["created_tabs"].append(t["tab"])
        for tab, cells in day.items():
            sheets_client.write_cells(src.id, tab, cells)
            res["day_written"] += len(cells)
    except Exception as e:  # noqa: BLE001
        res["error"] = _explain(e)
        res["partial"] = bool(res["roster_written"] or res["created_tabs"] or res["day_written"])
    return res


def _explain(e):
    from googleapiclient.errors import HttpError

    if isinstance(e, HttpError) and e.resp.status in (401, 403):
        return ("No permission to edit this spreadsheet - share it with the service account as Editor "
                "(Viewer is enough for reading only).")
    return f"{type(e).__name__}: {e}"


def commit(intents, user=None):
    """Plan fresh, then write what is plannable (Phase 4): the roster cells first, then the database day
    tabs. Blocked intents are reported and skipped, never forced. Squads are independent of each other.
    -> {"plans", "squads": [{squad, name, roster_written, day_written, created_tabs, partial, error}], "lines"}"""
    plans, squads, ctxs = _plan_intents(intents, user)
    names = dist.configured_names()
    results = []
    for info in squads:
        index = info["squad"]
        if info["error"]:
            results.append({"squad": index, "name": info["name"], "roster_written": 0, "day_written": 0,
                            "created_tabs": [], "partial": False, "error": info["error"]})
            continue
        mine = [p for p in plans if p is not None and p.get("squad") == index]
        res = _write_squad(ctxs[index], mine)
        res["name"] = names[index] if index < len(names) else f"Squad {index + 1}"
        if res["error"]:
            log.warning("link save, %s: %s (partial=%s)", res["name"], res["error"], res["partial"])
        else:
            log.info("link save by %s: %s, roster %d, day %d, new tabs %s", user, res["name"],
                     res["roster_written"], res["day_written"], res["created_tabs"])
        results.append(res)
    khdt_review._drop_caches()  # the page reloads straight after: it must see what was just written
    return {"plans": plans, "squads": results, "lines": format_plans(plans)}


# ------------------------------------------------------------------ printing
def format_plans(plans):
    lines = []
    for p in plans:
        it = p["intent"]
        head = f"{p.get('id') or it.get('id', '?')} {p.get('name', '')}".strip()
        lines.append(f"[{p['status'].upper()}] {p.get('squadName', '')} - {head} - {it.get('date', '?')} "
                     f"({it.get('origin', '?')} edit)")
        if p["blocked"]:
            lines.append(f"    blocked: {p['blocked']}")
        for t in p.get("create_tabs", []):
            lines.append(f"    new tab '{t['tab']}' with the header row {' | '.join(daily_db.HEADERS)}")
        for w in p["roster"]:
            lines.append(f"    roster '{w['tab']}'!{w['a1']}: {w['old']!r} -> {w['new']!r}"
                         + (" (red)" if w.get("color") == "FF0000" else ""))
        for w in p["day"]:
            lines.append(f"    day tab '{w['tab']}'!{w['a1']}: {w['old']!r} -> {w['new']!r}")
        for n in p["notes"]:
            lines.append(f"    note: {n}")
    return lines
