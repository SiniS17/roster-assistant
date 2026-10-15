"""
squad_roster.py
===============
The main roster page, built ONLY from the 1st sheet of each squad's spreadsheet
(the same four spreadsheets the Daily Distribution page reads - DISTRIBUTION_SHEET_URLS
in config.py, named by DISTRIBUTION_SHEET_NAMES). It does not read the old Main/temp sheet.

Read-only: it uses the view-only Sheets scope, so a Viewer share is enough.

For each squad the 1st sheet is a roster (header row with ID + NAME and one real date per day
column). The squads are merged into one table:
  - one row per employee, with the squad's name in an "Đội" column (the page's Đội filter picks a squad);
  - the day columns are the union of every squad's dates;
  - only rows with a real employee ID are kept, and a squad's list stops at the "NV TĂNG CƯỜNG"
    (reinforcement staff) block - those people already appear in their own squad's sheet;
  - an employee found in more than one squad is shown once, in the first squad (a note says so);
  - a squad that can't be read is skipped and reported; the others still show.
"""

from concurrent.futures import ThreadPoolExecutor

import distribution as dist
from engine import find_roster_header_grid
from roster_view import build_roster_payload

TEAM_HEADER = "Đội"


def own_rows_cutoff(values, header_row):
    """First row that is NOT one of the squad's own people: the 'NV TĂNG CƯỜNG' (reinforcement staff) row,
    or the end of the sheet. Everything from there down belongs to other squads (or is a summary)."""
    return next(
        (r for r in range(header_row + 1, len(values))
         if any("tang cuong" in dist.fold(v) for v in values[r] if isinstance(v, str))),
        len(values),
    )


def _squad_roster(index, force=False):
    """One squad's roster payload (own employees only), cached like the distribution data."""
    url = dist.configured_urls()[index]

    def load():
        src = dist._source(index, force)
        title = src.tabs()[0]
        values, colors = dist.first_sheet_grid(index, force, src)
        payload = build_roster_payload(title, values, colors, lenient=True)
        header_row = find_roster_header_grid(values, lenient=True)[0]
        cutoff = own_rows_cutoff(values, header_row)
        payload["employees"] = [
            e for e in payload["employees"] if e["row"] < cutoff and dist.ID_RE.match(e["id"] or "")
        ]
        return payload

    return dist._cached(("squad-roster", url), load, force)


def build_squads_roster(force=False):
    """The combined roster payload for the roster page (same shape as roster_view.build_roster_payload)."""
    urls, names = dist.configured_urls(), dist.configured_names()
    if not urls:
        raise ValueError("No squad spreadsheets are configured (DISTRIBUTION_SHEET_URLS in config.py).")

    def one(i):
        try:
            return _squad_roster(i, force), None
        except Exception as e:  # one unreadable squad must not hide the others
            return None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        results = list(pool.map(one, range(len(urls))))

    errors = [{"name": names[i], "error": err} for i, (p, err) in enumerate(results) if err]
    good = [(i, p) for i, (p, _) in enumerate(results) if p]
    if not good:
        raise ValueError("Couldn't read any squad roster. " + " | ".join(f"{e['name']}: {e['error']}" for e in errors))

    dates = sorted({d for _, p in good for d in p["dates"]})
    pos = {d: n for n, d in enumerate(dates)}

    # Info columns shown under each name: the squad, then every other labelled column the squads have.
    headers = [TEAM_HEADER]
    for _, p in good:
        for h in p["info_headers"]:
            if dist.fold(h) != dist.fold(TEAM_HEADER) and h not in headers:
                headers.append(h)

    employees, seen, duplicates = [], {}, 0
    for i, p in good:
        own_cols = {h: c for c, h in enumerate(p["info_headers"])}
        for e in p["employees"]:
            if e["id"] in seen:
                duplicates += 1
                continue
            seen[e["id"]] = names[i]
            cells, colors = [""] * len(dates), [None] * len(dates)
            for d, v, c in zip(p["dates"], e["cells"], e["colors"]):
                cells[pos[d]], colors[pos[d]] = v, c
            info = [names[i]] + [e["info"][own_cols[h]] if h in own_cols else "" for h in headers[1:]]
            employees.append({"row": len(employees), "id": e["id"], "name": e["name"], "info": info,
                              "cells": cells, "colors": colors})

    warnings = []
    if duplicates:
        warnings.append(f"{duplicates} employee(s) listed in more than one squad are shown once, in the first squad.")

    return {
        "ok": True,
        "view": "squads",
        "title": "Squads",
        "info_headers": headers,
        "dates": dates,
        "cols": list(range(len(dates))),
        "employees": employees,
        "tabs": [],
        "gid": "",
        "pending": 0,
        "changed": {},
        "sheet_url": urls[good[0][0]],
        "sources": [{"name": names[i], "url": urls[i], "employees": len(p["employees"]) if p else 0,
                     "error": err} for i, (p, err) in enumerate(results)],
        "errors": errors,
        "warnings": warnings,
    }
