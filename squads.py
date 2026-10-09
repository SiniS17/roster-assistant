"""
squads.py
=========
The Roster page is built from the 1st sheet of every squad spreadsheet (see
SQUAD_SHEET_URLS in config.py) - there is no separate "everyone in one sheet"
roster any more.

Who is a member of a squad
--------------------------
On a squad's 1st sheet, the members are the person rows of its roster table,
read from the top until the FIRST of:

  * a "tăng cường" (reinforcement) row, or
  * the first end of the ORD numbering (ORD is blank/not a number, or it stops
    increasing, e.g. a second list that starts again from 1).

Anything below that point (reinforcements from other squads, phone book, ...)
is not a member of this squad.

When the same person is listed in several squads
------------------------------------------------
They stay in the lowest-numbered squad: Squad 1 wins over Squad 2, Squad 2
over Squad 3, and so on (the order of SQUAD_SHEET_URLS in config.py).

Everything is found by searching for labels (ID / NAME / ORD), not by fixed
cell addresses, in the same spirit as distribution.py.
"""

from concurrent.futures import ThreadPoolExecutor

from config import SQUAD_MEMBER_STOP_LABEL
from distribution import _ORD_LABELS, _find_headers, configured_squads, first_sheet_grid, fold, text
from engine import find_roster_header_grid, normalize_id, normalize_name
from roster_view import build_roster_payload

_STOP = fold(SQUAD_MEMBER_STOP_LABEL)


# ----------------------------------------------------------- member extraction
def _at(row, col):
    return row[col] if col is not None and 0 <= col < len(row) else None


def _roster_header(values):
    """Header of the squad's roster table: {'row', 'id', 'name', 'ord'} (ord may be None)."""
    try:
        row, id_col, name_col, _ = find_roster_header_grid(values)  # ID + NAME + date columns
    except ValueError:
        headers = _find_headers(values)  # no day columns: any table with ID + NAME
        if not headers:
            raise ValueError("Couldn't find a header row with ID and NAME columns on the 1st sheet.")
        h = headers[0]
        return {"row": h["row"], "id": h["id"], "name": h["name"], "ord": h.get("ord")}
    ord_col = next((c for c, v in enumerate(values[row]) if fold(v) in _ORD_LABELS), None)
    return {"row": row, "id": id_col, "name": name_col, "ord": ord_col}


def _ord_number(v):
    """The ORD value as an int, or None when the cell is blank / not a number."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v) if float(v).is_integer() else None
    s = text(v).rstrip(".")
    return int(s) if s.isdigit() else None


def _is_stop_row(row, header, rid):
    """True for a "tăng cường" row. A person's own REMARK may mention it, so the label only counts
    when the row has no employee ID, or when it sits in the ORD / ID / NAME column."""
    for c, v in enumerate(row):
        if isinstance(v, str) and _STOP in fold(v):
            if not rid or c in (header["ord"], header["id"], header["name"]):
                return True
    return False


def extract_squad_members(values):
    """Members of one squad from its 1st sheet grid: [{'row', 'ord', 'id', 'name'}, ...] (row is 0-indexed)."""
    h = _roster_header(values)
    members, prev_ord = [], None
    for r in range(h["row"] + 1, len(values)):
        row = values[r]
        rid = normalize_id(text(_at(row, h["id"])))
        name = text(_at(row, h["name"]))
        if _is_stop_row(row, h, rid):
            break
        if h["ord"] is not None:
            n = _ord_number(_at(row, h["ord"]))
            if n is None or (prev_ord is not None and n <= prev_ord):
                break  # the ORD numbering ended (or started over) for the first time
            prev_ord = n
            if not rid and not name:
                continue  # a numbered but empty slot
        elif not rid:
            break  # no ORD column: the list ends at the first row without an ID
        members.append({"row": r, "ord": prev_ord, "id": rid, "name": name})
    return members


# ------------------------------------------------------------ priority merge
def _person_key(m):
    return m["id"] or "name:" + normalize_name(m["name"])


def combine_squads(squads):
    """
    squads: [(squad name, members), ...] in priority order (Squad 1 first).
    Returns (people, conflicts, duplicates):
      people     - every person once, each in the first squad that lists them
                   (the member dict plus 'squad'),
      conflicts  - [{'id', 'name', 'kept', 'dropped': [squad, ...]}] for people listed in several squads,
      duplicates - {squad: n} rows ignored because the same person appears twice in that squad.
    """
    owner, people, conflicts, duplicates = {}, [], {}, {}
    for squad, members in squads:
        seen_here = set()
        for m in members:
            key = _person_key(m)
            if key in seen_here:
                duplicates[squad] = duplicates.get(squad, 0) + 1
                continue
            seen_here.add(key)
            if key in owner:
                c = conflicts.setdefault(key, {"id": m["id"], "name": m["name"], "kept": owner[key], "dropped": []})
                c["dropped"].append(squad)
                continue
            owner[key] = squad
            people.append({**m, "squad": squad})
    return people, list(conflicts.values()), duplicates


# ------------------------------------------------------------- roster payload
def _load_squad(index, name, url, force):
    out = {"name": name, "url": url, "title": "", "members": [], "payload": None, "warnings": [], "error": None}
    try:
        title, values, colors = first_sheet_grid(index, force)
        out["title"] = title
        out["members"] = extract_squad_members(values)
        try:
            out["payload"] = build_roster_payload(title, values, colors)
        except ValueError:
            out["warnings"].append(f"{name}: no day columns found on the 1st sheet - members are listed without roster days.")
    except Exception as e:  # one bad spreadsheet must not hide the others
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def build_squads_payload(force=False):
    """The roster grid for the Roster page, in the same JSON shape as roster_view.build_roster_payload."""
    squads = configured_squads()
    if not squads:
        raise ValueError("No squad spreadsheets are configured - add them to SQUAD_SHEET_URLS in config.py.")
    with ThreadPoolExecutor(max_workers=min(8, len(squads))) as pool:
        loaded = list(pool.map(lambda a: _load_squad(a[0], a[1][0], a[1][1], force), enumerate(squads)))
    readable = [s for s in loaded if not s["error"]]
    if not readable:
        raise ValueError("None of the squad spreadsheets could be read: " + "; ".join(f"{s['name']}: {s['error']}" for s in loaded))

    people, conflicts, duplicates = combine_squads([(s["name"], s["members"]) for s in readable])

    # One date axis for everybody: the union of the squads' days (ISO strings sort chronologically).
    all_dates = sorted({d for s in readable if s["payload"] for d in s["payload"]["dates"]})
    pos = {d: i for i, d in enumerate(all_dates)}
    info_headers = ["Squad"]
    for s in readable:
        for h in (s["payload"] or {}).get("info_headers", []):
            if h and h not in info_headers:
                info_headers.append(h)

    payload_of = {s["name"]: s["payload"] for s in readable if s["payload"]}
    by_row = {name: {e["row"]: e for e in pl["employees"]} for name, pl in payload_of.items()}
    employees = []
    for n, p in enumerate(people):
        src = by_row.get(p["squad"], {}).get(p["row"])
        cells, colors = [""] * len(all_dates), [None] * len(all_dates)
        info = {}
        if src:
            payload = payload_of[p["squad"]]
            info = dict(zip(payload["info_headers"], src["info"]))
            for local, d in enumerate(payload["dates"]):
                cells[pos[d]] = src["cells"][local]
                colors[pos[d]] = src["colors"][local]
        employees.append({
            "row": n,
            "squad": p["squad"],
            "id": p["id"],
            "name": p["name"],
            "info": [p["squad"]] + [info.get(h, "") for h in info_headers[1:]],
            "cells": cells,
            "colors": colors,
        })

    notes = [f"{s['name']} couldn't be read ({s['error']})" for s in loaded if s["error"]]
    notes += [w for s in readable for w in s["warnings"]]
    if conflicts:
        who = "1 person is" if len(conflicts) == 1 else f"{len(conflicts)} people are"
        notes.append(f"{who} listed in more than one squad - each stays in the lowest-numbered squad.")
    notes += [f"{squad}: {k} duplicate row(s) ignored." for squad, k in duplicates.items()]

    return {
        "title": "All squads",
        "info_headers": info_headers,
        "dates": all_dates,
        "cols": list(range(len(all_dates))),
        "employees": employees,
        "view": "squads",
        "pending": 0,
        "changed": {},
        "tabs": [],
        "gid": "",
        "sheet_url": readable[0]["url"],
        "squads": [{"name": s["name"], "url": s["url"], "members": len(s["members"]), "error": s["error"]} for s in loaded],
        "conflicts": conflicts,
        "notes": notes,
    }
