"""
sheets_client.py
================
Reads/writes the Roster as a Google Sheet instead of an .xlsx file.

Auth: a Google service account. Share the target Sheet with that service
account's email (Editor access), and set ONE of these env vars:
  - GOOGLE_SERVICE_ACCOUNT_JSON  - the full service-account JSON, as a
    single-line string (easiest for Vercel/hosted env vars).
  - GOOGLE_APPLICATION_CREDENTIALS - path to a service-account JSON file
    on disk (easier for local dev).

See HOW_IT_WORKS.md for step-by-step setup instructions.
"""

import json
import os
import re

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_service = None


def get_service():
    global _service
    if _service is not None:
        return _service

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif creds_file:
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    else:
        raise RuntimeError(
            "No Google service-account credentials configured. Set "
            "GOOGLE_SERVICE_ACCOUNT_JSON (or GOOGLE_APPLICATION_CREDENTIALS) - see HOW_IT_WORKS.md."
        )

    _service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return _service


def parse_sheet_url(url):
    """Extract (spreadsheet_id, gid) from a Google Sheets URL."""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if not m:
        raise ValueError("Couldn't find a spreadsheet ID in that URL - check it's a normal Google Sheets link.")
    spreadsheet_id = m.group(1)
    gid_match = re.search(r"[?#&]gid=(\d+)", url)
    gid = int(gid_match.group(1)) if gid_match else 0
    return spreadsheet_id, gid


def _sheet_title_for_gid(service, spreadsheet_id, gid):
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    sheets = meta.get("sheets", [])
    for sheet in sheets:
        props = sheet["properties"]
        if props["sheetId"] == gid:
            return props["title"], props["sheetId"]
    # gid not found (e.g. URL had none) -> fall back to the first tab
    props = sheets[0]["properties"]
    return props["title"], props["sheetId"]


def read_roster_grid(sheet_url):
    """
    Returns (spreadsheet_id, sheet_id, sheet_title, values, colors).
    values/colors are 0-indexed 2D lists of equal shape. Dates come back
    as raw serial numbers (see engine.parse_sheet_date). colors[r][c] is
    a 6-hex-digit string (e.g. "FF0000") or None for default/black text.
    """
    service = get_service()
    spreadsheet_id, gid = parse_sheet_url(sheet_url)
    title, sheet_id = _sheet_title_for_gid(service, spreadsheet_id, gid)

    values_result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=title,
            valueRenderOption="UNFORMATTED_VALUE",
            dateTimeRenderOption="SERIAL_NUMBER",
        )
        .execute()
    )
    values = values_result.get("values", [])

    fmt_result = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            ranges=[title],
            fields="sheets.data.rowData.values.effectiveFormat.textFormat.foregroundColor",
        )
        .execute()
    )
    try:
        row_data = fmt_result["sheets"][0]["data"][0].get("rowData", [])
    except (KeyError, IndexError):
        row_data = []

    colors = []
    for row in row_data:
        crow = []
        for cell in row.get("values", []):
            color = None
            fg = cell.get("effectiveFormat", {}).get("textFormat", {}).get("foregroundColor")
            if fg:
                r = round(fg.get("red", 0) * 255)
                g = round(fg.get("green", 0) * 255)
                b = round(fg.get("blue", 0) * 255)
                if not (r == 0 and g == 0 and b == 0):
                    color = f"{r:02X}{g:02X}{b:02X}"
            crow.append(color)
        colors.append(crow)

    # Normalize both grids to the same rectangular shape.
    width = max((len(r) for r in values), default=0)
    height = max(len(values), len(colors))

    values = [(row + [None] * width)[:width] for row in values]
    while len(values) < height:
        values.append([None] * width)

    colors = [(row + [None] * width)[:width] for row in colors]
    while len(colors) < height:
        colors.append([None] * width)

    return spreadsheet_id, sheet_id, title, values, colors


def write_roster_updates(spreadsheet_id, sheet_id, updates):
    """updates: list of {"row": r, "col": c, "value": v, "color": "RRGGBB"} (0-indexed)."""
    if not updates:
        return
    service = get_service()

    requests = []
    for u in updates:
        color_hex = (u.get("color") or "000000").lstrip("#")
        r = int(color_hex[0:2], 16) / 255
        g = int(color_hex[2:4], 16) / 255
        b = int(color_hex[4:6], 16) / 255
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": u["row"],
                        "endRowIndex": u["row"] + 1,
                        "startColumnIndex": u["col"],
                        "endColumnIndex": u["col"] + 1,
                    },
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {"stringValue": str(u["value"])},
                                    "userEnteredFormat": {
                                        "textFormat": {"foregroundColor": {"red": r, "green": g, "blue": b}}
                                    },
                                }
                            ]
                        }
                    ],
                    "fields": "userEnteredValue,userEnteredFormat.textFormat.foregroundColor",
                }
            }
        )

    CHUNK = 500
    for i in range(0, len(requests), CHUNK):
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests[i : i + CHUNK]}
        ).execute()
