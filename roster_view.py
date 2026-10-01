"""
roster_view.py
==============
Turns the in-memory Roster grid (from sheets_client.read_roster_grid) into a
compact JSON payload for the roster page, and lists the Sheet's tabs.
"""

from engine import find_roster_header_grid, normalize_id
from sheets_client import get_service


def list_tabs(spreadsheet_id):
    """Visible tabs of the spreadsheet as [{"title": ..., "gid": ...}]."""
    service = get_service()
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title,hidden)")
        .execute()
    )
    return [
        {"title": s["properties"]["title"], "gid": s["properties"]["sheetId"]}
        for s in meta.get("sheets", [])
        if not s["properties"].get("hidden")
    ]


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def build_roster_payload(title, values, colors):
    header_row, id_col, name_col, date_cols = find_roster_header_grid(values)
    ordered = sorted(date_cols.items())  # [(date, col), ...]
    first_date_col = min(date_cols.values())
    header = values[header_row]

    # Any labelled column left of the first date (position, group, ...) is
    # shown as small secondary text under the employee name.
    skip = {"stt", "tt", "no", "no.", "#"}
    info_cols = [
        c
        for c in range(first_date_col)
        if c not in (id_col, name_col)
        and _text(header[c] if c < len(header) else "")
        and _text(header[c]).lower() not in skip
    ]

    employees = []
    for r in range(header_row + 1, len(values)):
        row = values[r]
        rid = _text(row[id_col]) if id_col < len(row) else ""
        name = _text(row[name_col]) if name_col < len(row) else ""
        if not rid and not name:
            continue
        crow = colors[r] if r < len(colors) else []
        employees.append(
            {
                "row": r,
                "id": normalize_id(rid),
                "name": name,
                "info": [_text(row[c]) if c < len(row) else "" for c in info_cols],
                "cells": [_text(row[c]) if c < len(row) else "" for _, c in ordered],
                "colors": [(crow[c] if c < len(crow) else None) for _, c in ordered],
            }
        )

    return {
        "title": title,
        "info_headers": [_text(header[c]) for c in info_cols],
        "dates": [d.isoformat() for d, _ in ordered],
        "cols": [c for _, c in ordered],
        "employees": employees,
    }


def tab_url(spreadsheet_id, gid):
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit?gid={gid}"


def find_tab(tabs, name):
    """Case-insensitive lookup of a tab by title."""
    for t in tabs:
        if t["title"].strip().lower() == name.lower():
            return t
    return None


def rebuild_temp(spreadsheet_id, source_gid):
    """
    Make the 'temp' tab an exact copy (values, colours, formatting) of the
    source tab. Any existing 'temp' tab is replaced, keeping its position.
    Returns the sheetId of the fresh temp tab.
    """
    service = get_service()
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title,index)")
        .execute()
    )
    props = [s["properties"] for s in meta.get("sheets", [])]
    src = next(p for p in props if p["sheetId"] == source_gid)
    old = next((p for p in props if p["title"].strip().lower() == "temp"), None)

    requests = []
    index = src["index"] + 1
    title = "temp"
    if old is not None:
        index = old["index"]
        title = old["title"]
        requests.append({"deleteSheet": {"sheetId": old["sheetId"]}})
    requests.append(
        {"duplicateSheet": {"sourceSheetId": source_gid, "insertSheetIndex": index, "newSheetName": title}}
    )
    resp = service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
    return resp["replies"][-1]["duplicateSheet"]["properties"]["sheetId"]


def _cell_map(payload):
    out = {}
    for e in payload["employees"]:
        key = e["id"] or e["name"]
        for d, v in zip(payload["dates"], e["cells"]):
            out[f"{key}|{d}"] = v
    return out


def diff_main_temp(main_payload, temp_payload):
    """
    Cells whose value in temp differs from Main.
    Returns {"<id>|<YYYY-MM-DD>": <value in Main>} (Main value is '' for new entries).
    """
    main = _cell_map(main_payload)
    changed = {}
    for key, tv in _cell_map(temp_payload).items():
        mv = main.get(key, "")
        if mv.strip() != tv.strip():
            changed[key] = mv
    return changed
