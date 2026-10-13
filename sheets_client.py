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

import httplib2
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

try:
    from google_auth_httplib2 import AuthorizedHttp
except ImportError:  # pragma: no cover - ships with google-api-python-client
    AuthorizedHttp = None

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
# The Daily Distribution page only ever READS other teams' spreadsheets, so it
# asks Google for view-only scopes (a Viewer share is enough).
READONLY_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
DRIVE_READONLY_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_service = None
_creds_cache = {}

# httplib2 >= 0.32 refuses any gzip response that expands more than 100x ("DecodeRatioError: Amplification
# ratio 232.8 ..."). A big sheet whose formatted-but-empty cells come back as {} is legitimately that
# compressible (Squad 2: 63 KB -> 14.7 MB), so the ratio check is switched off (0 = off). The absolute
# hard limit stays on, so a real decompression bomb is still stopped.
DECODE_LIMIT_RATIO = 0
DECODE_LIMIT_HARD = 512 << 20  # 512 MB


def _http(creds):
    """An authorised httplib2 client with the relaxed decode limits (old httplib2 versions: defaults)."""
    try:
        base = httplib2.Http(decode_limit_ratio=DECODE_LIMIT_RATIO, decode_limit_hard=DECODE_LIMIT_HARD)
    except TypeError:  # httplib2 older than the decode-limit options
        base = httplib2.Http()
    return AuthorizedHttp(creds, http=base) if AuthorizedHttp else None


def _build(api, version, scopes):
    creds = _credentials(scopes)
    http = _http(creds)
    if http is None:
        return build(api, version, credentials=creds, cache_discovery=False)
    return build(api, version, http=http, cache_discovery=False)


def _credentials(scopes):
    """Service-account credentials for the given scopes (cached per scope set)."""
    key = tuple(scopes)
    if key in _creds_cache:
        return _creds_cache[key]

    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

    if creds_json:
        creds_json = creds_json.strip()
        # Vercel's env-var UI (and some copy/paste paths) sometimes wraps
        # the whole value in an extra pair of quotes, or leaves it as
        # multi-line pretty JSON with real newlines - both break json.loads
        # with an opaque "char 0" error. Give a clearer diagnosis instead.
        if len(creds_json) >= 2 and creds_json[0] == '"' and creds_json[-1] == '"':
            creds_json = creds_json[1:-1]
        try:
            info = json.loads(creds_json)
        except json.JSONDecodeError as e:
            preview = f"{len(creds_json)} chars, starts with {creds_json[:12]!r}" if creds_json else "EMPTY"
            raise RuntimeError(
                f"GOOGLE_SERVICE_ACCOUNT_JSON is set but is not valid JSON ({preview}). "
                "Make sure you pasted the MINIFIED one-line JSON (see HOW_IT_WORKS.md), "
                "with no extra surrounding quotes, and that you redeployed after setting it."
            ) from e
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    elif creds_file:
        creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
    else:
        raise RuntimeError(
            "No Google service-account credentials configured. Set "
            "GOOGLE_SERVICE_ACCOUNT_JSON (or GOOGLE_APPLICATION_CREDENTIALS) - see HOW_IT_WORKS.md."
        )

    _creds_cache[key] = creds
    return creds


def get_service():
    global _service
    if _service is None:
        _service = _build("sheets", "v4", SCOPES)
    return _service


def make_readonly_service():
    """A NEW view-only Sheets client (clients aren't thread-safe, so callers on threads build their own)."""
    return _build("sheets", "v4", READONLY_SCOPES)


def make_drive_service():
    """A NEW view-only Drive client, used to download spreadsheets that are really uploaded .xlsx files."""
    return _build("drive", "v3", DRIVE_READONLY_SCOPES)


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
