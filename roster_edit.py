"""
roster_edit.py
==============
Hand edits of the squads' roster (Phase 2 of "Login and Linked Editing Plan").

The page stages edits in the browser; save() writes them into the squads' real 1st sheets. It reuses
the checks of the KHDT export: each squad's sheet is re-read fresh and every edit is verified before
anything is written.

An edit is {squad, id, name, date (YYYY-MM-DD), old, kind, value}:
  kind 'code'  - an aircraft code (free text such as 'A864-FM'), written in black
  kind 'n'     - a normal day off: black 'N'
  kind 'clear' - empty the cell

An edit is skipped (and reported, never forced) when
  - the employee is no longer on that squad's own rows, or the date column is not on the sheet,
  - the cell text is no longer what the page saw (somebody else changed it),
  - the cell is LOCKED: a KHDT course marker ('H ...') or a red N (guaranteed day off) - KHDT owns those,
  - the new value is not allowed (empty code, a course marker, a bare 'N' typed as a code, too long),
  - it would change nothing.
The editor can therefore never write a red N or an 'H ...' marker.

Who may edit which squad is decided by auth.can_edit(user, squad): the seam for roles.
"""

import logging
import re

from googleapiclient.errors import HttpError

import auth
import distribution as dist
from engine import is_course_marker, is_red_n, normalize_id
from khdt_review import _drop_caches, _load_squad, _tab_gid
from roster_view import _text
from sheets_client import write_roster_updates

log = logging.getLogger(__name__)

MAX_EDITS = 3000
MAX_CODE_LEN = 40
KINDS = ("code", "n", "clear")
BLACK = "000000"


def new_value(edit):
    """The text an edit would write; ValueError (with a readable reason) when it isn't allowed."""
    kind = edit.get("kind")
    if kind == "n":
        return "N"
    if kind == "clear":
        return ""
    if kind != "code":
        raise ValueError("unknown kind of edit")
    v = re.sub(r"\s+", " ", str(edit.get("value") or "")).strip()
    if not v:
        raise ValueError("the code is empty")
    if len(v) > MAX_CODE_LEN:
        raise ValueError(f"the code is longer than {MAX_CODE_LEN} characters")
    if v.upper() == "N":
        raise ValueError("use 'Normal N' for a day off")
    if is_course_marker(v):
        raise ValueError("course markers ('H ...') come from KHDT only")
    return v


def _row_of(sq, emp_id):
    for r in range(sq["header_row"] + 1, sq["cutoff"]):
        row = sq["values"][r]
        if sq["id_col"] < len(row) and normalize_id(_text(row[sq["id_col"]])) == emp_id:
            return r
    return None


def check(sq, col_of_date, edit):
    """(update dict, None) when the edit may be written now, else (None, reason)."""
    r = _row_of(sq, normalize_id(edit.get("id")))
    if r is None:
        return None, "the employee is no longer on this squad's roster"
    col = col_of_date.get(str(edit.get("date")))
    if col is None:
        return None, "that date is not on the sheet"
    row = sq["values"][r]
    live = _text(row[col]) if col < len(row) else ""
    crow = sq["colors"][r] if r < len(sq["colors"]) else []
    color = crow[col] if col < len(crow) else None
    if live != str(edit.get("old") if edit.get("old") is not None else "").strip():
        return None, f"the cell changed since you opened it (now '{live}')"
    if is_course_marker(live):
        return None, "locked: a KHDT course marker"
    if is_red_n(live, color):
        return None, "locked: guaranteed day off (red N)"
    try:
        value = new_value(edit)
    except ValueError as e:
        return None, str(e)
    if value == live:
        return None, "no change"
    return {"row": r, "col": col, "value": value, "color": BLACK}, None


def _save_squad(index, edits, user):
    names = dist.configured_names()
    res = {"squad": index, "name": names[index] if 0 <= index < len(names) else f"Squad {index + 1}",
           "written": 0, "skipped": [], "error": None}
    try:
        if not 0 <= index < len(names):
            raise ValueError("Unknown squad.")
        if not auth.can_edit(user, index):
            raise ValueError("You are not allowed to edit this squad.")
        sq = _load_squad(index, True)  # fresh read: the checks must see the sheet as it is now
        if getattr(sq["src"], "kind", "sheets") != "sheets":
            raise ValueError("This squad's file is an uploaded Excel (.xlsx), which can't be edited through "
                             "Google Sheets - convert it to a Google Sheet first.")
        col_of_date = {d.isoformat(): c for d, c in sq["date_cols"].items()}
        updates = []
        for e in edits:
            update, why = check(sq, col_of_date, e)
            if why:
                res["skipped"].append({"id": e.get("id", ""), "name": e.get("name", ""),
                                       "date": e.get("date", ""), "reason": why})
            else:
                updates.append(update)
        if updates:
            write_roster_updates(sq["src"].id, _tab_gid(sq["src"].id, sq["title"]), updates)
            res["written"] = len(updates)
            log.info("roster edit by %s: %s, %d cell(s)", user, res["name"], len(updates))
    except HttpError as e:
        if e.resp.status in (401, 403):
            res["error"] = ("No permission to edit this spreadsheet - share it with the service account as "
                            "Editor (Viewer is enough for reading only).")
        else:
            res["error"] = f"HttpError {e.resp.status}: {e}"
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def save(edits, user):
    """Write the staged edits. -> {"squads": [{name, written, skipped, error}], "invalid": n}"""
    if len(edits) > MAX_EDITS:
        raise ValueError(f"Too many edits at once ({len(edits)}); the limit is {MAX_EDITS}.")
    by_squad, invalid = {}, 0
    for e in edits:
        try:
            squad = int(e["squad"])
            ok = e.get("kind") in KINDS and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("date", ""))) and e.get("id")
        except (KeyError, TypeError, ValueError):
            ok = False
        if not ok:
            invalid += 1
            continue
        by_squad.setdefault(squad, {})[(normalize_id(e["id"]), e["date"])] = e  # the last edit of a cell wins
    out = {"squads": [_save_squad(i, list(es.values()), user) for i, es in sorted(by_squad.items())],
           "invalid": invalid}
    _drop_caches()  # the page reloads straight after: it must see what was just written
    return out
