"""
khdt_review.py
==============
KHDT -> the squads' roster, as a *review* instead of a write.

preview(): runs the usual KHDT matching (engine.mark_roster_grid) against the 1st sheet of each squad's
spreadsheet - the same four sheets the roster page shows - but writes NOTHING. It returns the proposed
changes, one per roster cell: who, which day, what the cell says now, what it would say. The page
highlights them; each person keeps or rejects them in their own browser (nothing is stored on the server).

export(): writes the changes the person kept into the real squad sheets. Every change is checked
against the live sheet first (same employee on that row, same date column, cell still holding the value
the preview saw); anything that moved is skipped and reported instead of being overwritten.

Every change carries a signature (HMAC with the app's secret key), so export only ever writes what
preview() proposed - a hand-made request can't put arbitrary text into the roster.
"""

import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

from googleapiclient.errors import HttpError

import distribution as dist
from engine import find_roster_header_grid, is_black_n, is_course_marker, mark_roster_grid, normalize_id
from roster_view import _text
from sheets_client import get_service, write_roster_updates
from squad_roster import own_rows_cutoff

# The fields that make up a change; the signature covers exactly these.
SIGNED_FIELDS = ("squad", "id", "date", "row", "col", "old", "new", "newColor")
STAT_KEYS = ("marked", "conflicts", "overlaps_combined", "weekend_n", "no_id_match",
             "no_date_overlap", "name_mismatch", "already_marked")


# ------------------------------------------------------------------ signing
def sign(change, secret):
    payload = json.dumps([change.get(k) for k in SIGNED_FIELDS], ensure_ascii=False, separators=(",", ":"))
    return hmac.new(str(secret).encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def verify(change, secret):
    try:
        return hmac.compare_digest(sign(change, secret), str(change.get("sig", "")))
    except Exception:  # noqa: BLE001 - a malformed change is simply not valid
        return False


# ------------------------------------------------------------------ reading
def _load_squad(index, force=True):
    """One squad's 1st sheet with its header located (same reading as the roster page)."""
    src = dist._source(index, force)
    title = src.tabs()[0]
    values, colors = dist.first_sheet_grid(index, force, src)
    header_row, id_col, name_col, date_cols = find_roster_header_grid(values, lenient=True)
    return {
        "src": src, "title": title, "values": values, "colors": colors,
        "header_row": header_row, "id_col": id_col, "name_col": name_col, "date_cols": date_cols,
        "cutoff": own_rows_cutoff(values, header_row),
    }


def _own_ids(sq, claimed):
    """IDs of the squad's own people (above the reinforcement block) that no earlier squad already has."""
    own = set()
    for r in range(sq["header_row"] + 1, sq["cutoff"]):
        row = sq["values"][r]
        rid = normalize_id(_text(row[sq["id_col"]])) if sq["id_col"] < len(row) else ""
        if dist.ID_RE.match(rid) and rid not in claimed:
            own.add(rid)
    return own


def _color(c):
    return (c or "000000").upper().lstrip("#")[-6:]


def _kind(old, old_color, new):
    """new = empty cell; update = a course marker extended; dayoff = a black N replaced;
    conflict = something else was in the cell (or a guaranteed-day-off red N) and is replaced/appended to."""
    if old == "":
        return "new"
    if is_black_n(old, old_color):
        return "dayoff"
    if is_course_marker(old) and is_course_marker(new):
        return "update"
    return "conflict"


# ------------------------------------------------------------------ preview
def preview(khdt_rows, secret, force=False):
    """Run KHDT against the four squads' sheets and return the proposed changes (nothing is written).

    -> {"changes": [...signed...], "stats": {...}, "log": [...], "event_log": {...}, "squads": [...]}
    """
    urls, names = dist.configured_urls(), dist.configured_names()
    if not urls:
        raise ValueError("No squad spreadsheets are configured (DISTRIBUTION_SHEET_URLS in config.py).")

    def load(i):
        try:
            return _load_squad(i, True), None
        except Exception as e:  # noqa: BLE001 - one unreadable squad must not hide the others
            return None, f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        loaded = list(pool.map(load, range(len(urls))))
    if not any(sq for sq, _ in loaded):
        raise ValueError("Couldn't read any squad roster. " + " | ".join(
            f"{names[i]}: {err}" for i, (_, err) in enumerate(loaded)))

    log_lines, event_log = [], {}
    log_lines.append(f"Loaded {len(khdt_rows)} KHDT rows")
    stats = dict.fromkeys(STAT_KEYS, 0)
    changes, squads, claimed = [], [], set()

    for i, (sq, err) in enumerate(loaded):
        info = {"index": i, "name": names[i], "employees": 0, "changes": 0, "error": err, "editable": True}
        squads.append(info)
        if sq is None:
            log_lines.append(f"[WARN] {names[i]} couldn't be read ({err}) - its people can't be matched")
            continue
        info["editable"] = getattr(sq["src"], "kind", "sheets") == "sheets"
        if not info["editable"]:
            log_lines.append(f"[WARN] {names[i]} is an uploaded Excel file: its changes can be reviewed but not exported")

        own = _own_ids(sq, claimed)
        claimed |= own
        info["employees"] = len(own)
        rows = [r for r in khdt_rows if r["id"] in own]
        log_lines.append(f"{names[i]}: '{sq['title']}' ({len(own)} people) - {len(rows)} KHDT row(s) match")
        if not rows:
            continue

        # Only the squad's own rows: the reinforcement block below belongs to other squads.
        cut = sq["cutoff"]
        squad_stats, updates = mark_roster_grid(
            rows, sq["values"][:cut], sq["colors"][:cut], force=force, log=log_lines.append,
            event_log=event_log, lenient=True,
        )
        for k in STAT_KEYS:
            if k != "no_id_match":
                stats[k] += squad_stats.get(k, 0)

        by_col = {c: d for d, c in sq["date_cols"].items()}
        for u in updates:
            r, c = u["row"], u["col"]
            row = sq["values"][r]
            old = _text(row[c]) if c < len(row) else ""
            old_color = sq["colors"][r][c] if c < len(sq["colors"][r]) else None
            new, new_color = str(u["value"]), _color(u.get("color"))
            if old == new.strip() and _color(old_color) == new_color:
                continue  # the cell already says exactly this
            change = {
                "squad": i, "squadName": names[i],
                "id": normalize_id(_text(row[sq["id_col"]])), "name": _text(row[sq["name_col"]]),
                "date": by_col[c].isoformat(), "row": r, "col": c,
                "old": old, "oldColor": old_color, "new": new, "newColor": new_color,
                "kind": _kind(old, old_color, new),
            }
            change["sig"] = sign(change, secret)
            changes.append(change)
            info["changes"] += 1

    stats["no_id_match"] = sum(1 for r in khdt_rows if r["id"] not in claimed)
    changes.sort(key=lambda c: (c["squad"], c["row"], c["col"]))
    log_lines.append(f"Proposed {len(changes)} cell change(s) - nothing has been written to the sheets")
    return {"changes": changes, "stats": stats, "log": log_lines, "event_log": event_log, "squads": squads}


# ------------------------------------------------------------------ export
def _drop_caches():
    with dist._lock:
        dist._cache.clear()


def _tab_gid(spreadsheet_id, title):
    meta = get_service().spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties(sheetId,title)").execute()
    for s in meta.get("sheets", []):
        if s["properties"]["title"] == title:
            return s["properties"]["sheetId"]
    raise ValueError(f"Tab '{title}' not found any more.")


def _stale_reason(sq, col_of_date, c):
    """Why a change can't be written safely any more (None = fine to write)."""
    r, col = c["row"], c["col"]
    if not (sq["header_row"] < r < sq["cutoff"]):
        return "that row is no longer part of the roster"
    row = sq["values"][r]
    if normalize_id(_text(row[sq["id_col"]])) != c["id"]:
        return "the employee is no longer on that row"
    if col_of_date.get(c["date"]) != col:
        return "the date columns moved"
    cur = _text(row[col]) if col < len(row) else ""
    if cur != c["old"]:
        return f"the cell changed since the preview (now '{cur}')"
    return None


def _export_squad(index, changes):
    names = dist.configured_names()
    res = {"squad": index, "name": names[index] if 0 <= index < len(names) else f"Squad {index + 1}",
           "written": 0, "skipped": [], "error": None}
    try:
        if not 0 <= index < len(names):
            raise ValueError("Unknown squad.")
        sq = _load_squad(index, True)  # a fresh read: the check must see the sheet as it is now
        if getattr(sq["src"], "kind", "sheets") != "sheets":
            raise ValueError("This squad's file is an uploaded Excel (.xlsx), which can't be edited through "
                             "Google Sheets - convert it to a Google Sheet first.")
        col_of_date = {d.isoformat(): c for d, c in sq["date_cols"].items()}
        updates = []
        for c in changes:
            why = _stale_reason(sq, col_of_date, c)
            if why:
                res["skipped"].append({"id": c["id"], "name": c.get("name", ""), "date": c["date"], "reason": why})
            else:
                updates.append({"row": c["row"], "col": c["col"], "value": c["new"], "color": c["newColor"]})
        if updates:
            write_roster_updates(sq["src"].id, _tab_gid(sq["src"].id, sq["title"]), updates)
            res["written"] = len(updates)
    except HttpError as e:
        if e.resp.status in (401, 403):
            res["error"] = ("No permission to edit this spreadsheet - share it with the service account as "
                            "Editor (Viewer is enough for reading only).")
        else:
            res["error"] = f"HttpError {e.resp.status}: {e}"
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def export(changes, secret):
    """Write the kept changes into the squads' sheets. -> {"squads": [...], "invalid": n}"""
    valid = [c for c in changes if verify(c, secret)]
    by_squad = {}
    for c in valid:
        by_squad.setdefault(c["squad"], []).append(c)
    out = {"squads": [_export_squad(i, cs) for i, cs in sorted(by_squad.items())],
           "invalid": len(changes) - len(valid)}
    _drop_caches()  # the page reloads straight after: it must see what was just written
    return out
