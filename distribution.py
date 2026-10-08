"""
distribution.py
================
"Daily Distribution" feature: reads several *other* Google spreadsheets
(view-only access is enough) and turns one day's tab into the
"who goes to which zone" page.

Each configured spreadsheet looks like this:

  1st sheet     General info: A/C, Check, date range, Foreman / Truc doi /
                Dock planner / Shift-Tech supp (+ phone numbers), and a
                phone-number list keyed by employee ID.
  other sheets  One tab per day, named "<A/C>-<MMM><DD>" (e.g. B218-SEP21),
                holding ORD / NAME AND SURNAME / ID / POSITION / REMARK
                tables, split into sections ("ZONE 128", "ZONE 128 @16H00", ...).

Everything is parsed by searching for labels, not by fixed cell addresses, so
small layout changes (moved columns, extra blank rows) don't break it.

If a spreadsheet is really an uploaded .xlsx (the Sheets API refuses those),
it is downloaded through the Drive API and read with openpyxl instead.
"""

import io
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import openpyxl
from googleapiclient.errors import HttpError

from config import DISTRIBUTION_CACHE_SECONDS, DISTRIBUTION_SHEET_URLS
from engine import normalize_id, parse_sheet_date
from sheets_client import make_drive_service, make_readonly_service, parse_sheet_url

MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
TAB_RE = re.compile(r"^\s*(?P<ac>.*?)[\s_\-]*(?P<mon>[A-Za-z]{3})[\s_\-]*(?P<day>\d{1,2})\s*$")
ID_RE = re.compile(r"^[A-Z]{2,5}\d{3,}$")
TIME_RE = re.compile(r"@\s*(\d{1,2})\s*[hH:]\s*(\d{2})")


# ---------------------------------------------------------------- text helpers
def fold(v):
    """Lower-case, accent-free text for label matching ('Trực đội' -> 'truc doi')."""
    s = "" if v is None else str(v)
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", s).strip().lower()


def text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime, date)):
        return ""
    return str(v).strip()


def clean_phone(v):
    """'0982132232' from '0982 132 232', 982132232 (leading 0 lost to a number cell), '+84 98...'."""
    if v is None or isinstance(v, (datetime, date)):
        return ""
    if isinstance(v, (int, float)):
        s = str(int(v))
        if len(s) == 9 and s[0] in "3456789":
            s = "0" + s
    else:
        s = str(v).strip()
        if not re.fullmatch(r"\+?\d[\d\s.\-()]{6,}\d", s):
            return ""
        s = re.sub(r"[\s.\-()]", "", s)
    digits = re.sub(r"\D", "", s)
    return s if 8 <= len(digits) <= 12 else ""


def find_phone_in_text(s):
    m = re.search(r"(\+?\d[\d\s.\-]{7,}\d)", s or "")
    return clean_phone(m.group(1)) if m else ""


def is_red(color):
    if not color:
        return False
    try:
        r, g, b = int(color[-6:-4], 16), int(color[-4:-2], 16), int(color[-2:], 16)
    except ValueError:
        return False
    return r >= 180 and g <= 90 and b <= 90


# ------------------------------------------------------------ data sources
def _rect(values, colors):
    width = max([len(r) for r in values] + [len(r) for r in colors] + [0])
    height = max(len(values), len(colors))
    values = [(list(r) + [None] * width)[:width] for r in values] + [[None] * width for _ in range(height - len(values))]
    colors = [(list(r) + [None] * width)[:width] for r in colors] + [[None] * width for _ in range(height - len(colors))]
    return values, colors


def _quote(title):
    return "'" + title.replace("'", "''") + "'"


class SheetsSource:
    """A native Google Sheet, read through the view-only Sheets API."""

    kind = "sheets"

    def __init__(self, spreadsheet_id):
        self.id = spreadsheet_id
        self.svc = make_readonly_service()
        meta = (
            self.svc.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="properties.title,sheets.properties(sheetId,title,hidden,index)")
            .execute()
        )
        self.title = meta["properties"]["title"]
        self._tabs = [s["properties"]["title"] for s in meta.get("sheets", []) if not s["properties"].get("hidden")]

    def tabs(self):
        return self._tabs

    def grid(self, tab, with_colors=True):
        svc = make_readonly_service()  # fresh client: this runs on worker threads
        rng = _quote(tab)
        vals = (
            svc.spreadsheets()
            .values()
            .get(
                spreadsheetId=self.id,
                range=rng,
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
            .get("values", [])
        )
        if not with_colors:
            return _rect(vals, [])
        fmt = (
            svc.spreadsheets()
            .get(
                spreadsheetId=self.id,
                ranges=[rng],
                fields="sheets.data.rowData.values.effectiveFormat.textFormat.foregroundColor",
            )
            .execute()
        )
        try:
            row_data = fmt["sheets"][0]["data"][0].get("rowData", [])
        except (KeyError, IndexError):
            row_data = []
        colors = []
        for row in row_data:
            crow = []
            for cell in row.get("values", []):
                color = None
                fg = cell.get("effectiveFormat", {}).get("textFormat", {}).get("foregroundColor")
                if fg:
                    r, g, b = (round(fg.get(k, 0) * 255) for k in ("red", "green", "blue"))
                    if (r, g, b) != (0, 0, 0):
                        color = f"{r:02X}{g:02X}{b:02X}"
                crow.append(color)
            colors.append(crow)
        return _rect(vals, colors)


class XlsxSource:
    """An uploaded Excel file stored in Drive: downloaded once, then read with openpyxl."""

    kind = "xlsx"

    def __init__(self, file_id):
        from googleapiclient.http import MediaIoBaseDownload

        self.id = file_id
        drive = make_drive_service()
        self.title = drive.files().get(fileId=file_id, fields="name", supportsAllDrives=True).execute().get("name", file_id)
        buf = io.BytesIO()
        req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        buf.seek(0)
        self.wb = openpyxl.load_workbook(buf, data_only=True)

    def tabs(self):
        return [ws.title for ws in self.wb.worksheets if ws.sheet_state == "visible"]

    def grid(self, tab, with_colors=True):
        ws = self.wb[tab]
        values, colors = [], []
        for row in ws.iter_rows():
            vrow, crow = [], []
            for cell in row:
                vrow.append(cell.value)
                color = None
                c = cell.font.color if cell.font else None
                if c is not None and c.type == "rgb" and isinstance(c.rgb, str) and len(c.rgb) >= 6:
                    rgb = c.rgb[-6:].upper()
                    if rgb != "000000":
                        color = rgb
                crow.append(color)
            values.append(vrow)
            colors.append(crow)
        return _rect(values, colors)


def open_source(url):
    """Open a spreadsheet for reading; falls back to Drive download for uploaded .xlsx files."""
    spreadsheet_id, _ = parse_sheet_url(url)
    try:
        return SheetsSource(spreadsheet_id)
    except HttpError as e:
        if e.resp.status == 400 and "not supported" in str(e).lower():
            return XlsxSource(spreadsheet_id)
        raise


# ------------------------------------------------------------------- caching
_lock = threading.Lock()
_cache = {}


def _cached(key, loader, force=False):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and not force and now - hit[0] < DISTRIBUTION_CACHE_SECONDS:
            return hit[1]
    value = loader()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def configured_urls():
    return [u for u in DISTRIBUTION_SHEET_URLS if u and u.strip()]


def _source(index, force=False):
    urls = configured_urls()
    if not 0 <= index < len(urls):
        raise ValueError(f"No spreadsheet number {index} is configured.")
    return _cached(("src", urls[index]), lambda: open_source(urls[index]), force)


def _grid(index, tab, force=False):
    src = _source(index, force)
    return _cached(("grid", src.id, tab), lambda: src.grid(tab), force)


def _first_sheet_values(index, force=False):
    """Values of the 1st sheet only (labels, contacts, phone book) - no colour lookup needed."""
    src = _source(index, force)
    return _cached(("first", src.id), lambda: src.grid(src.tabs()[0], with_colors=False)[0], force)


# -------------------------------------------------------------- tab names
def parse_tab_name(title, ref=None):
    """'B218-SEP21' -> ('B218', date(2026, 9, 21)); None when it isn't a day tab."""
    m = TAB_RE.match(title or "")
    if not m or m.group("mon").upper() not in MONTHS:
        return None
    month, day = MONTHS[m.group("mon").upper()], int(m.group("day"))
    ref = ref or date.today()
    best = None
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return (m.group("ac").strip(), best) if best else None


# ------------------------------------------------------------ 1st sheet
_LABELS = {
    "ac": {"a/c", "ac", "a/c reg", "a/c registration", "aircraft", "registration", "reg"},
    "check": {"check", "check type", "loai check"},
    "dates": {"date", "dates", "date range", "ngay", "period", "thoi gian"},
    "foreman": {"foreman"},
    "truc_doi": {"truc doi"},
    "dock_planner": {"dock planner"},
    "shift_tech": {"shift / tech supp", "shift/tech supp", "shift / tech support", "shift/tech support", "shift", "tech supp", "tech support"},
}
_LABEL_LOOKUP = {lab: key for key, labs in _LABELS.items() for lab in labs}
_PERSON_KEYS = ("foreman", "truc_doi", "dock_planner", "shift_tech")


def _label_of(cell):
    """('ac', 'B218' or '') when the cell is a label, optionally with the value inline ('A/C: B218')."""
    f = fold(cell)
    if f in _LABEL_LOOKUP:
        return _LABEL_LOOKUP[f], ""
    m = re.match(r"^([a-z/ ]{2,24}?)\s*[:=]\s*(.+)$", text(cell), re.I)
    if m and fold(m.group(1)) in _LABEL_LOOKUP:
        return _LABEL_LOOKUP[fold(m.group(1))], m.group(2).strip()
    return None


def _cell(values, r, c):
    return values[r][c] if 0 <= r < len(values) and 0 <= c < len(values[r]) else None


def _neighbours(values, r, c, right=4, down=1):
    """Candidate value cells for a label at (r, c): to its right first, then just below it.
    Cells that are themselves labels are never offered as values."""
    for k in range(1, right + 1):
        v = _cell(values, r, c + k)
        if text(v) and not _label_of(v):
            yield v
    for k in range(1, down + 1):
        v = _cell(values, r + k, c)
        if text(v) and not _label_of(v):
            yield v


def _person_after(values, r, c, inline):
    """{'name', 'phone'} for a Foreman/Truc doi/... label at (r, c), or None when the name is blank.
    Layouts handled: 'LABEL | name | phone', 'LABEL | name (phone)', 'LABEL: name', and
    'LABEL' with the name (then phone) in the two cells below it."""
    right = [v for v in (_cell(values, r, c + k) for k in range(1, 5)) if text(v) and not _label_of(v)]
    if inline:
        first, rest = inline, right
    elif right:
        first, rest = right[0], right[1:]
    else:
        below = _cell(values, r + 1, c)
        if not text(below) or _label_of(below):
            return None
        first, rest = below, [_cell(values, r + 2, c)]
    if clean_phone(first):  # the only thing next to the label is a phone number: no name
        return None
    phone = find_phone_in_text(str(first)) if re.search(r"\d{8,}", str(first)) else ""
    name = re.sub(r"[\s,;()\-–]*\+?\d[\d\s.\-]{7,}\d\)?\s*$", "", str(first)).strip() if phone else text(first)
    if not phone:
        phone = next((clean_phone(v) for v in rest if clean_phone(v)), "")
    return {"name": name, "phone": phone} if name else None


def _parse_date_range(cells, text_value):
    """Return (from, to, display_text) from two date cells, or from text such as '21-29 SEP 2026'."""
    dates = [d for d in (parse_sheet_date(v) for v in cells) if d]
    if len(dates) >= 2:
        return dates[0], dates[1], ""
    if len(dates) == 1 and not text_value:
        return dates[0], dates[0], ""
    t = text_value or ""
    mon = "|".join(MONTHS)
    m = re.search(rf"(\d{{1,2}})\s*({mon})?[a-z]*\s*(?:-|–|—|~|to)\s*(\d{{1,2}})\s*({mon})[a-z]*\s*,?\s*(\d{{4}})?", t, re.I)
    if m:
        d1, m1, d2, m2, y = m.groups()
        year = int(y) if y else date.today().year
        try:
            end = date(year, MONTHS[m2.upper()], int(d2))
            start = date(year, MONTHS[(m1 or m2).upper()], int(d1))
            if start > end:
                start = date(year - 1, start.month, start.day)
            return start, end, ""
        except (ValueError, KeyError):
            pass
    d_text = [parse_sheet_date(p.strip()) for p in re.split(r"\s*[-–—~]\s*", t)] if t else []
    d_text = [d for d in d_text if d]
    if len(d_text) >= 2:
        return d_text[0], d_text[1], ""
    return None, None, t


def parse_info(values):
    """Everything useful on the 1st sheet: A/C, check, dates, the four contacts, phone book."""
    info = {"ac": "", "check": "", "date_from": None, "date_to": None, "date_text": "", "people": {}}
    phones = {}
    warnings = []

    # Phone book: any row holding an employee ID and a phone-looking cell.
    for row in values:
        id_col = next((i for i, v in enumerate(row) if ID_RE.match(normalize_id(text(v)))), None)
        if id_col is None:
            continue
        order = list(range(id_col + 1, len(row))) + list(range(0, id_col))
        for i in order:
            p = clean_phone(row[i])
            if p:
                phones[normalize_id(text(row[id_col]))] = p
                break

    # Labelled fields.
    for r, row in enumerate(values):
        for c, cell in enumerate(row):
            lab = _label_of(cell)
            if not lab:
                continue
            key, inline = lab
            if key in info["people"] or (key in ("ac", "check") and info[key]):
                continue
            if key in ("ac", "check"):
                info[key] = inline or next((text(v) for v in _neighbours(values, r, c)), "")
            elif key == "dates":
                cands = [v for v in (_cell(values, r, c + k) for k in range(1, 4)) if v not in (None, "")]
                a_, b_, t = _parse_date_range(cands, inline or next((text(v) for v in cands if text(v)), ""))
                if a_:
                    info["date_from"], info["date_to"] = a_, b_
                else:
                    info["date_text"] = t
            elif key in _PERSON_KEYS:
                person = _person_after(values, r, c, inline)
                if person:
                    info["people"][key] = person

    for key, label in (("ac", "A/C"), ("check", "Check")):
        if not info[key]:
            warnings.append(f"{label} not found on the 1st sheet")
    return info, phones, warnings


# ------------------------------------------------------------------- meta
def _meta_for(index, force=False):
    url = configured_urls()[index]
    out = {"index": index, "url": url, "ac": "", "title": "", "check": "", "date_from": None, "date_to": None,
           "date_text": "", "people": {}, "days": [], "warnings": [], "error": None}
    try:
        src = _source(index, force)
        out["title"] = src.title
        tabs = src.tabs()
        if not tabs:
            raise ValueError("The spreadsheet has no visible sheets.")
        info, phones, warnings = parse_info(_first_sheet_values(index, force))
        out["warnings"] = warnings
        out["people"] = info["people"]
        out["check"] = info["check"]
        out["ac"] = info["ac"]
        out["date_text"] = info["date_text"]
        ref = info["date_from"] or date.today()
        out["date_from"] = info["date_from"].isoformat() if info["date_from"] else None
        out["date_to"] = info["date_to"].isoformat() if info["date_to"] else None

        days = []
        for tab in tabs[1:]:
            parsed = parse_tab_name(tab, ref)
            if parsed:
                days.append({"tab": tab, "ac": parsed[0], "date": parsed[1].isoformat()})
        days.sort(key=lambda d: d["date"])
        out["days"] = days
        if not out["ac"] and days:
            out["ac"] = days[0]["ac"]
        if not out["ac"]:
            out["ac"] = src.title
        if not out["date_from"] and days:
            out["date_from"], out["date_to"] = days[0]["date"], days[-1]["date"]
        if not days:
            out["warnings"].append("No day tabs named like 'B218-SEP21' were found")
        out["phones"] = len(phones)
    except Exception as e:  # one bad spreadsheet must not hide the others
        out["error"] = f"{type(e).__name__}: {e}"
        out["ac"] = out["ac"] or f"Sheet {index + 1}"
    return out


def meta_for(index, force=False):
    return _cached(("meta", configured_urls()[index]), lambda: _meta_for(index, force), force)


def build_meta(force=False):
    urls = configured_urls()
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        return list(pool.map(lambda i: meta_for(i, force), range(len(urls))))


# --------------------------------------------------------------- day tabs
_NAME_LABELS = {"name and surname", "name & surname", "name", "ho ten", "ho va ten", "ho & ten", "ten"}
_ID_LABELS = {"id", "ma nv", "ma nhan vien", "emp id", "employee id"}
_POS_LABELS = {"position", "pos", "vi tri", "chuc danh"}
_REMARK_LABELS = {"remark", "remarks", "ghi chu", "note", "notes"}
_PHONE_LABELS = {"phone", "tel", "sdt", "so dien thoai", "phone number", "mobile"}
_ORD_LABELS = {"ord", "stt", "tt", "no", "no."}


def _find_headers(values):
    """Every table header: [{'row': r, 'ord': c|None, 'name': c, 'id': c, 'pos': c|None, ...}].
    A row can hold several headers side by side - a label seen twice starts a new table."""
    headers = []
    for r, row in enumerate(values):
        groups, cols = [], {}
        for c, cell in enumerate(row):
            f = fold(cell)
            if not f:
                continue
            for key, labels in (("name", _NAME_LABELS), ("id", _ID_LABELS), ("pos", _POS_LABELS),
                                ("remark", _REMARK_LABELS), ("phone", _PHONE_LABELS), ("ord", _ORD_LABELS)):
                if f in labels:
                    if key in cols:
                        groups.append(cols)
                        cols = {}
                    cols[key] = c
                    break
        groups.append(cols)
        for g in groups:
            if "name" in g and "id" in g:
                g["row"] = r
                headers.append(g)
    return headers


def _is_person_row(row, cols):
    rid = normalize_id(text(row[cols["id"]])) if cols["id"] < len(row) else ""
    if ID_RE.match(rid):
        return True
    ordv = row[cols["ord"]] if cols.get("ord") is not None and cols["ord"] < len(row) else None
    name = text(row[cols["name"]]) if cols["name"] < len(row) else ""
    return bool(name) and isinstance(ordv, (int, float)) and not rid


def parse_day(values, colors, phones=None):
    phones = phones or {}
    headers = _find_headers(values)
    if not headers:
        raise ValueError("Couldn't find a header row with ID and NAME columns in this tab.")

    sections = []
    for hi, h in enumerate(headers):
        # This table runs until the next header that sits in the same columns.
        end = len(values)
        for h2 in headers[hi + 1:]:
            if h2["name"] == h["name"]:
                end = h2["row"]
                break
        left = min(c for k, c in h.items() if k != "row")
        right = max(c for k, c in h.items() if k != "row")
        current = None
        for r in range(h["row"] + 1, end):
            row = values[r]
            if _is_person_row(row, h):
                if current is None:
                    current = {"title": "", "people": []}
                    sections.append(current)

                def cell(key):
                    c = h.get(key)
                    return row[c] if c is not None and c < len(row) else None

                rid = normalize_id(text(cell("id")))
                rc = h.get("remark")
                color = colors[r][rc] if rc is not None and r < len(colors) and rc < len(colors[r]) else None
                ordv = cell("ord")
                current["people"].append({
                    "ord": int(ordv) if isinstance(ordv, (int, float)) else (len(current["people"]) + 1),
                    "name": text(cell("name")),
                    "id": rid,
                    "pos": text(cell("pos")),
                    "phone": clean_phone(cell("phone")) or phones.get(rid, ""),
                    "remark": text(cell("remark")),
                    "red": is_red(color),
                })
                continue
            cells = [text(row[c]) for c in range(left, min(right + 1, len(row))) if text(row[c])]
            if cells and len(cells[0]) <= 48 and not any(fold(x) in _ID_LABELS | _NAME_LABELS for x in cells):
                current = {"title": re.sub(r"\s+", " ", cells[0]), "people": []}
                sections.append(current)

    out = []
    for s in sections:
        title = s["title"] or "OTHER"
        tm = TIME_RE.search(title)
        out.append({
            "title": title.upper(),
            "kind": "zone" if fold(title).startswith("zone") else "other",
            "time": f"{int(tm.group(1)):02d}H{tm.group(2)}" if tm else None,
            "people": s["people"],
        })
    return out


def build_day(index, tab, force=False):
    meta = meta_for(index, force)
    if meta.get("error"):
        raise ValueError(meta["error"])
    day = next((d for d in meta["days"] if d["tab"] == tab), None)
    if not day:
        raise ValueError(f"Tab '{tab}' is not a day tab of this spreadsheet.")
    _, phones, _ = parse_info(_first_sheet_values(index, force))
    values, colors = _grid(index, tab, force)
    return {
        "index": index,
        "tab": tab,
        "date": day["date"],
        "ac": day["ac"] or meta["ac"],
        "sections": parse_day(values, colors, phones),
    }
