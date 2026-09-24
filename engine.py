"""
engine.py
================
All the KHDT-vs-Roster matching/marking logic, ported from the original
desktop tool's main.py. Two changes from that version:

  1. The Roster side no longer reads/writes an .xlsx with openpyxl - it
     operates on a plain in-memory grid (a 2D list of values, a 2D list
     of font-color strings) so the exact same matching logic can run
     against data pulled from a Google Sheet.
  2. Instead of saving a workbook, mark_roster_grid() returns a list of
     "cell updates" (row, col, value, color) for the caller to push back
     to the Sheet via the Sheets API in one batch.

KHDT is unchanged: it's still an uploaded .xlsx, read with openpyxl.

See HOW_IT_WORKS.md for the full plain-language explanation of what this
does to your files/sheet.
"""

import re
import unicodedata
from datetime import date, datetime, timedelta

import openpyxl

from config import (
    COURSE_ABBREVIATIONS,
    COURSE_NAME_ABBREVIATIONS,
    LOG_COLUMN_HEADERS,
    LOG_EVENT_LABELS,
    MARKER_PREFIX,
)

# ==========================================================================
# CONFIG — safe to edit
# ==========================================================================

DEFAULT_FORCE_OVERWRITE = False

# Font colors used for values this tool writes (hex, no "#").
MARKER_FONT_COLOR = "FF0000"  # red
WEEKEND_FONT_COLOR = "000000"  # black

# How many months on either side of the Roster's own month we tolerate
# before flagging a KHDT date as implausible (see check_date_plausible).
MONTH_SWAP_TOLERANCE = 1

# ==========================================================================
# Text / date helpers (unchanged from the desktop tool)
# ==========================================================================


def strip_accents(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(s):
    if not s:
        return ""
    s = strip_accents(str(s)).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_id(s):
    if s is None:
        return ""
    return str(s).strip().upper()


def parse_khdt_date(value):
    """
    Parse a KHDT date cell into a date object (or None).

    KHDT's date columns are stored in YYYY-DD-MM order (day and month
    swapped from the usual convention). Real Excel date cells get their
    day/month fields swapped back; slash-separated text ("10/09/2026") is
    already in normal DD/MM/YYYY order; hyphenated text ("2026-11-09")
    follows the file's YYYY-DD-MM convention.
    """
    if value is None:
        return None

    if isinstance(value, (datetime, date)):
        d = value.date() if isinstance(value, datetime) else value
        try:
            return date(d.year, d.day, d.month)
        except ValueError:
            return d

    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
        for fmt in ("%Y-%d-%m",):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
    return None


def parse_sheet_date(value):
    """
    Parse a Roster (Google Sheet) date cell into a date object (or None).

    Sheets dates come back from the API either as a serial day-number
    (days since 1899-12-30, same epoch Excel uses) when read with
    dateTimeRenderOption=SERIAL_NUMBER, or as plain DD/MM/YYYY text if the
    cell is just typed text. Both are handled here. Unlike KHDT, the
    Roster's own dates are assumed correct (no day/month swap bug here).
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return date(1899, 12, 30) + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None
    if isinstance(value, (datetime, date)):
        return value.date() if isinstance(value, datetime) else value
    if isinstance(value, str):
        v = value.strip()
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
            try:
                return datetime.strptime(v, fmt).date()
            except ValueError:
                continue
    return None


def check_date_plausible(d, expected_year, expected_month, log, context=""):
    if d is None:
        return
    if d.year == expected_year and abs((d.month - expected_month) % 12) <= MONTH_SWAP_TOLERANCE:
        return
    log(f"[CHECK] {context}: date {d} looks outside the expected {expected_year}-{expected_month:02d} window - please verify")


def extract_note_date(note, expected_year):
    """
    "Lí do" sometimes pins a broad KHDT date range down to ONE actual class
    day, phrased as "Lên lớp chiều 8/9/2026" ("attend class in the
    afternoon of <date>"). Deliberately narrow: only triggers right after
    "Lên lớp" so it doesn't fire on unrelated dates mentioned in passing.
    """
    if not note:
        return None
    text = str(note)
    m = re.search(r"lên\s*lớp.{0,20}?(\d{1,2})/(\d{1,2})/(\d{2,4})", text, re.IGNORECASE)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def abbreviate_course_name(course_name):
    if not course_name:
        return None
    first_line = " ".join(str(course_name).strip().splitlines()[0].split())
    if not first_line:
        return None
    normalized_name = normalize_name(first_line)
    for full_name, abbreviation in COURSE_NAME_ABBREVIATIONS.items():
        if normalize_name(full_name) == normalized_name:
            return abbreviation
    stop_words = {
        "a", "an", "and", "for", "in", "of", "on", "part", "the", "to",
        "va", "ve", "và", "về", "của", "cho", "trong",
    }
    stop_words = {normalize_name(word) for word in stop_words}
    tokens = re.findall(r"[A-Za-zÀ-ỹ0-9]+(?:[/+.-][A-Za-zÀ-ỹ0-9]+)*", first_line)
    meaningful = [token for token in tokens if normalize_name(token) not in stop_words]
    if not meaningful:
        return first_line[:24]
    pieces = []
    for token in meaningful[:8]:
        normalized_token = strip_accents(token)
        if any(character.isdigit() for character in token) or token.isupper() or len(token) <= 4:
            pieces.append(normalized_token.upper())
        else:
            pieces.append(normalized_token[0].upper())
    return " ".join(pieces)[:24].rstrip()


def is_course_marker(value):
    if not isinstance(value, str):
        return False
    return value.strip().upper().startswith(f"{MARKER_PREFIX.upper()} ")


def is_n_value(value):
    return isinstance(value, str) and value.strip().upper() == "N"


def is_black_n(value, color):
    """color: hex string (no '#'), or None/'' meaning default (black) text."""
    if not is_n_value(value):
        return False
    if not color:
        return True
    return color.upper().lstrip("#")[-6:] == WEEKEND_FONT_COLOR.upper()


def is_red_n(value, color):
    if not is_n_value(value):
        return False
    if not color:
        return False
    return color.upper().lstrip("#")[-6:] == MARKER_FONT_COLOR.upper()


def append_to_existing(existing, addition):
    if existing in (None, ""):
        return addition
    if is_course_marker(existing):
        return combine_markers([existing, addition])
    return f"{str(existing).strip()}-{addition}"


def _marker_sort_key(marker):
    normalized = normalize_name(marker)
    if "sang" in normalized:
        return 0
    if "chieu" in normalized:
        return 1
    return 2


def marker_parts(marker):
    if not marker:
        return []
    marker = re.sub(r"\s+", " ", str(marker).strip())
    prefix = f"{MARKER_PREFIX} "
    body = marker[len(prefix):] if marker.upper().startswith(prefix.upper()) else marker
    parts = []
    for part in body.split("-"):
        part = part.strip()
        if not part:
            continue
        if part.upper().startswith(prefix.upper()):
            part = part[len(prefix):].strip()
        if part:
            parts.append(part)
    return parts


def combine_markers(markers):
    unique = []
    seen = set()
    for marker in markers:
        for part in marker_parts(marker):
            key = part.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(part)
    if not unique:
        return ""
    unique.sort(key=_marker_sort_key)
    return f"{MARKER_PREFIX} {'-'.join(unique)}".strip()


def record_log_event(event_log, name, employee_id, event, reason, event_date=None, details=None):
    if event_log is None:
        return
    if isinstance(event_date, datetime):
        event_date = event_date.date()
    name = str(name or "").strip()
    employee_id = normalize_id(employee_id)
    key = (name, employee_id, event_date)
    record = event_log.setdefault(
        key,
        {"name": name, "id": employee_id, "date": event_date, "events": [], "reasons": [], "details": []},
    )
    if event and event not in record["events"]:
        record["events"].append(event)
    if reason and reason not in record["reasons"]:
        record["reasons"].append(str(reason))
    if details and details not in record["details"]:
        record["details"].append(str(details))


def build_marker(class_code, course_name, note):
    label = None
    if class_code:
        code = str(class_code)
        parts = code.rsplit("/", 2)
        base = parts[0] if len(parts) >= 2 else code
        label = COURSE_ABBREVIATIONS.get(base, base)
    elif course_name:
        label = abbreviate_course_name(course_name)
    if not label:
        label = "?"
    marker = f"{MARKER_PREFIX} {label}".strip()
    note_l = normalize_name(note) if note else ""
    if "sang" in note_l and "sang" not in normalize_name(marker):
        marker += " SÁNG"
    elif "chieu" in note_l or "chiều" in (note or "").lower():
        marker += " CHIỀU"
    return marker


# ==========================================================================
# KHDT (.xlsx upload) — unchanged from the desktop tool
# ==========================================================================


def find_khdt_header(ws):
    wanted = {
        "name": ("họ tên", "ho ten"),
        "id": ("mã nv", "ma nv"),
        "doi": ("phòng/đội", "phong/doi"),
        "course": ("tên kđt", "ten kdt"),
        "class_code": ("mã lớp học", "ma lop hoc"),
        "start": ("bắt đầu", "bat dau"),
        "end": ("kết thúc", "ket thuc"),
        "note": ("lí do", "lý do", "ly do"),
    }
    for r in range(1, min(ws.max_row, 30) + 1):
        row_vals = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str):
                row_vals[c] = normalize_name(v)
        if not row_vals:
            continue
        found = {}
        for key, aliases in wanted.items():
            norm_aliases = [normalize_name(a) for a in aliases]
            for c, norm in row_vals.items():
                if any(a in norm for a in norm_aliases):
                    found[key] = c
                    break
        if "id" in found and "name" in found and "start" in found:
            return r, found
    raise ValueError("Could not find the KHDT header row (looked for 'Mã NV' / 'Họ tên' / 'Bắt đầu').")


def load_khdt(file_obj_or_path):
    wb = openpyxl.load_workbook(file_obj_or_path, data_only=True)
    ws = wb.worksheets[0]
    header_row, cols = find_khdt_header(ws)

    rows = []
    for r in range(header_row + 1, ws.max_row + 1):
        emp_id = ws.cell(row=r, column=cols["id"]).value
        if not emp_id:
            continue
        name = ws.cell(row=r, column=cols["name"]).value
        doi = ws.cell(row=r, column=cols.get("doi", 0)).value if cols.get("doi") else None
        course = ws.cell(row=r, column=cols.get("course", 0)).value if cols.get("course") else None
        class_code = ws.cell(row=r, column=cols.get("class_code", 0)).value if cols.get("class_code") else None
        start_raw = ws.cell(row=r, column=cols["start"]).value
        end_raw = ws.cell(row=r, column=cols.get("end", cols["start"])).value if cols.get("end") else start_raw
        note = ws.cell(row=r, column=cols.get("note", 0)).value if cols.get("note") else None

        start = parse_khdt_date(start_raw)
        end = parse_khdt_date(end_raw)
        if end is None:
            end = start

        rows.append(
            {
                "row": r, "id": normalize_id(emp_id), "name": name, "doi": doi,
                "course": course, "class_code": class_code, "start": start, "end": end, "note": note,
            }
        )
    return rows


# ==========================================================================
# Roster (Google Sheet, as an in-memory grid) — new
# ==========================================================================
# A "grid" here is just:
#   values: list[list[Any]]   - row-major, values[r][c]
#   colors: list[list[str|None]] - same shape, each cell's font color as a
#            hex string with no leading "#" (e.g. "FF0000"), or None/"" for
#            the sheet's default (black) text.
# Both are 0-indexed here (unlike the openpyxl version, which was 1-indexed).


def find_roster_header_grid(values):
    """Locate the header row (has 'ID' + 'NAME' columns) and day-columns."""
    max_scan = min(len(values), 30)
    for r in range(max_scan):
        row = values[r]
        id_col = None
        name_col = None
        for c, v in enumerate(row):
            if not isinstance(v, str):
                continue
            norm = normalize_name(v)
            if norm == "id":
                id_col = c
            elif ("name" in norm and "surname" in norm) or norm == "name":
                name_col = c
        if id_col is not None and name_col is not None:
            date_cols = {}
            for c, v in enumerate(row):
                d = parse_sheet_date(v)
                if d is not None:
                    date_cols[d] = c
            if date_cols:
                return r, id_col, name_col, date_cols
    raise ValueError("Could not find the Roster header row (looked for 'ID' + 'NAME' columns plus date columns).")


def mark_roster_grid(khdt_rows, values, colors, force=False, log=print, event_log=None):
    """
    Same algorithm as the desktop tool's mark_roster(), adapted to read
    from/write to in-memory `values`/`colors` grids instead of an openpyxl
    worksheet. Returns (stats, updates) where updates is a list of
    {"row": r, "col": c, "value": v, "color": hex_or_None} - every cell
    that actually needs to change on the live Sheet (0-indexed).
    """
    header_row, id_col, name_col, date_cols = find_roster_header_grid(values)

    sample_dates = sorted(date_cols.keys())
    expected_year = sample_dates[0].year
    months = [d.month for d in sample_dates]
    expected_month = max(set(months), key=months.count)

    id_to_row = {}
    id_to_name = {}
    for r in range(header_row + 1, len(values)):
        row = values[r]
        rid = row[id_col] if id_col < len(row) else None
        if not rid:
            continue
        norm = normalize_id(rid)
        id_to_row[norm] = r
        id_to_name[norm] = row[name_col] if name_col < len(row) else None

    def cell_value(r, c):
        row = values[r] if r < len(values) else []
        return row[c] if c < len(row) else None

    def cell_color(r, c):
        row = colors[r] if r < len(colors) else []
        return row[c] if c < len(row) else None

    stats = {
        "marked": 0, "conflicts": 0, "overlaps_combined": 0, "weekend_n": 0,
        "no_id_match": 0, "no_date_overlap": 0, "name_mismatch": 0, "already_marked": 0,
    }
    assignments = {}

    for entry in khdt_rows:
        eid = entry["id"]
        if eid not in id_to_row:
            stats["no_id_match"] += 1
            continue

        roster_row = id_to_row[eid]
        roster_name = id_to_name.get(eid)
        if normalize_name(entry["name"]) and normalize_name(entry["name"]) != normalize_name(roster_name):
            stats["name_mismatch"] += 1
            record_log_event(
                event_log, entry["name"], eid, LOG_EVENT_LABELS["name_mismatch"],
                f"KHDT name: {entry['name']}; Roster name: {roster_name}",
            )
            log(f"[WARN] ID {eid} matched but names differ: KHDT='{entry['name']}' vs Roster='{roster_name}' (row {entry['row']})")

        start, end = entry["start"], entry["end"]
        if start is None:
            record_log_event(event_log, entry["name"], eid, LOG_EVENT_LABELS["skipped"], "No usable start date", details=f"KHDT row {entry['row']}")
            log(f"[SKIP] {entry['name']} ({eid}): no usable start date (KHDT row {entry['row']})")
            continue
        if end is None or end < start:
            end = start
        ctx = f"{entry['name']} ({eid}), KHDT row {entry['row']}"
        check_date_plausible(start, expected_year, expected_month, log, ctx + " [start]")
        check_date_plausible(end, expected_year, expected_month, log, ctx + " [end]")

        note_date = extract_note_date(entry["note"], expected_year)
        if note_date is not None and (note_date != start or note_date != end):
            record_log_event(
                event_log, entry["name"], eid, LOG_EVENT_LABELS["note"], str(entry["note"]).strip(),
                event_date=note_date, details=f"Date was pinned to {note_date} instead of the range {start}..{end}",
            )
            log(f"[NOTE DATE] {entry['name']} ({eid}): range was {start}..{end}, but Lí do pins it to {note_date} -> marking that day only (KHDT row {entry['row']})")
            start = end = note_date

        marker = build_marker(entry["class_code"], entry["course"], entry["note"])

        d = start
        matched_any_day = False
        while d <= end:
            if d in date_cols:
                matched_any_day = True
                col = date_cols[d]
                key = (roster_row, d)
                assignments.setdefault(key, []).append(
                    {"marker": marker, "name": entry["name"], "id": eid, "row": entry["row"], "column": col}
                )
            d += timedelta(days=1)

        if not matched_any_day:
            stats["no_date_overlap"] += 1
            record_log_event(
                event_log, entry["name"], eid, LOG_EVENT_LABELS["no_date_overlap"],
                f"{start}..{end} does not fall in the roster's date range", details=f"KHDT row {entry['row']}",
            )
            log(f"[NO OVERLAP] {entry['name']} ({eid}): {start}..{end} doesn't fall in this Roster's date range (KHDT row {entry['row']})")

    updates = []

    for (roster_row, d), entries in assignments.items():
        col = entries[0]["column"]
        existing = cell_value(roster_row, col)
        existing_color = cell_color(roster_row, col)
        markers = [item["marker"] for item in entries]
        combined = combine_markers(markers)

        if len(set(m.casefold() for m in markers)) > 1:
            stats["overlaps_combined"] += 1
            record_log_event(
                event_log, entries[0]["name"], entries[0]["id"], LOG_EVENT_LABELS["overlap"],
                f"Courses combined: {', '.join(markers)} -> {combined}", event_date=d,
                details=f"KHDT rows: {', '.join(str(i['row']) for i in entries)}",
            )
            log(f"[OVERLAP] {entries[0]['name']} ({entries[0]['id']}) {d}: combined {', '.join(markers)} -> '{combined}'")

        if d.weekday() >= 5:
            weekend_value = "N"
            if is_black_n(existing, existing_color):
                record_log_event(
                    event_log, entries[0]["name"], entries[0]["id"], LOG_EVENT_LABELS["overwrite_day_off"],
                    "Existing black N was overwritten with N", event_date=d, details=f"KHDT row {entries[0]['row']}",
                )
                log(f"[OVERWRITE DAY OFF] {entries[0]['name']} ({entries[0]['id']}) {d}: existing black N was overwritten with N (KHDT row {entries[0]['row']})")
            elif existing not in (None, "") and not is_course_marker(existing):
                event_label = LOG_EVENT_LABELS["guarantee_day_off_conflict"] if is_red_n(existing, existing_color) else LOG_EVENT_LABELS["conflict"]
                existing_description = (
                    "Existing red N (guaranteed day off); wanted: N" if is_red_n(existing, existing_color)
                    else f"Existing cell: {existing}; wanted: N"
                )
                stats["conflicts"] += 1
                record_log_event(event_log, entries[0]["name"], entries[0]["id"], event_label, existing_description, event_date=d, details=f"KHDT row {entries[0]['row']}")
                log(
                    f"[{'GUARANTEE DAY OFF CONFLICT' if is_red_n(existing, existing_color) else 'CONFLICT'}] "
                    f"{entries[0]['name']} ({entries[0]['id']}) {d}: cell already has '{existing}', wanted 'N'; "
                    f"{'appended N instead' if not force else 'overwrote it'} (KHDT row {entries[0]['row']})"
                )
                if not force:
                    weekend_value = append_to_existing(existing, "N")
            updates.append({"row": roster_row, "col": col, "value": weekend_value, "color": WEEKEND_FONT_COLOR})
            stats["marked"] += 1
            stats["weekend_n"] += 1
            continue

        combined_with_existing = combined
        if is_black_n(existing, existing_color):
            record_log_event(
                event_log, entries[0]["name"], entries[0]["id"], LOG_EVENT_LABELS["overwrite_day_off"],
                f"Existing black N was overwritten with {combined}", event_date=d, details=f"KHDT row {entries[0]['row']}",
            )
            log(f"[OVERWRITE DAY OFF] {entries[0]['name']} ({entries[0]['id']}) {d}: existing black N was overwritten with '{combined}' (KHDT row {entries[0]['row']})")
        elif existing not in (None, ""):
            if is_course_marker(existing):
                existing_parts = {p.casefold() for p in marker_parts(existing)}
                new_parts = marker_parts(combined)
                already_present = [p for p in new_parts if p.casefold() in existing_parts]
                if already_present:
                    stats["already_marked"] += 1
                    record_log_event(
                        event_log, entries[0]["name"], entries[0]["id"], LOG_EVENT_LABELS["already_marked"],
                        f"Already present, not duplicated: {', '.join(already_present)}", event_date=d,
                        details=f"Existing cell: {existing}; KHDT rows: {', '.join(str(i['row']) for i in entries)}",
                    )
                    log(f"[ALREADY MARKED] {entries[0]['name']} ({entries[0]['id']}) {d}: {', '.join(already_present)} already present in '{existing}' - skipped, not duplicated")
                combined_with_existing = combine_markers([existing, combined])
                if combined_with_existing == existing:
                    continue
            elif is_red_n(existing, existing_color):
                stats["conflicts"] += 1
                record_log_event(
                    event_log, entries[0]["name"], entries[0]["id"], LOG_EVENT_LABELS["guarantee_day_off_conflict"],
                    f"Existing red N (guaranteed day off); wanted: {combined}", event_date=d, details=f"KHDT row {entries[0]['row']}",
                )
                log(f"[GUARANTEE DAY OFF CONFLICT] {entries[0]['name']} ({entries[0]['id']}) {d}: cell already has red N, wanted '{combined}'; {'appended course instead' if not force else 'overwrote it'} (KHDT row {entries[0]['row']})")
                if not force:
                    combined_with_existing = append_to_existing(existing, combined)
            elif not force:
                stats["conflicts"] += 1
                record_log_event(
                    event_log, entries[0]["name"], entries[0]["id"], LOG_EVENT_LABELS["conflict"],
                    f"Existing cell: {existing}; wanted: {combined}", event_date=d, details=f"KHDT row {entries[0]['row']}",
                )
                log(f"[CONFLICT] {entries[0]['name']} ({entries[0]['id']}) {d}: cell already has '{existing}', wanted '{combined}'; appended course instead (KHDT row {entries[0]['row']})")
                combined_with_existing = append_to_existing(existing, combined)

        updates.append({"row": roster_row, "col": col, "value": combined_with_existing, "color": MARKER_FONT_COLOR})
        stats["marked"] += 1

    return stats, updates
