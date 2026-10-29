"""
auth.py
=======
Simple login for the write routes (Phase 1 of "Login and Linked Editing Plan").

Accounts live in an Excel file (Database/users.xlsx). People log in with their employee ID: the
file's columns are Name | ID | Password (a plain username | password file also works; "Name" is
optional and is what the page shows after login). It is re-read
whenever its modified time or size changes, so accounts can be added or removed without a restart.
Passwords are plain text in that file (the plan's choice for now): keep it out of git (.gitignore)
and out of reach of normal users. Proper hashing comes with the PostgreSQL users table (Step 8).

What is protected: every route that writes (decorate it with @login_required). Every GET stays open.

can_edit(user, squad) is the single seam where roles slot in later: today every logged-in user
may edit every squad.
"""

import hmac
import os
import threading
import time
from functools import wraps

from flask import Blueprint, jsonify, request, session

# Settings (kept here for Phase 1; move to config.py if more of them appear).
USERS_FILE = os.environ.get("AUTH_USERS_FILE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "Database", "users.xlsx")
MAX_FAILS = 5          # wrong passwords allowed ...
FAIL_WINDOW = 300      # ... within this many seconds, per (client address, username)

bp = Blueprint("auth", __name__)


class UsersFileError(Exception):
    """The accounts file is missing or unreadable."""


# ------------------------------------------------------------------ accounts file
_lock = threading.Lock()
_cache = {"key": None, "users": {}}


def _fold(name):
    return str(name or "").strip().casefold()


def _cell_text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)  # a numeric password typed into Excel
    return str(v)


def load_users():
    """{folded ID/username: (name to show, password)}; cached until the file changes."""
    path = USERS_FILE
    try:
        st = os.stat(path)
    except OSError:
        raise UsersFileError("No user accounts are set up yet (run tools/make_users.py).")
    key = (path, st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["users"]
    import openpyxl

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
        wb.close()
    except Exception as e:  # noqa: BLE001
        raise UsersFileError(f"Couldn't read the accounts file: {type(e).__name__}: {e}")
    users, ucol, ncol, pcol, start = {}, None, None, None, 0
    for i, row in enumerate(rows[:10]):
        heads = [_fold(c) for c in row]
        uh = next((h for h in ("id", "username") if h in heads), None)
        if uh and "password" in heads:
            ucol, pcol, start = heads.index(uh), heads.index("password"), i + 1
            ncol = heads.index("name") if "name" in heads else None
            break
    if ucol is None:
        raise UsersFileError("The accounts file needs a header row with 'ID' (or 'username') and 'password'.")
    for row in rows[start:]:
        uid = _cell_text(row[ucol] if ucol < len(row) else None).strip()
        pw = _cell_text(row[pcol] if pcol < len(row) else None)
        name = _cell_text(row[ncol] if ncol is not None and ncol < len(row) else None).strip() or uid
        if uid and pw:
            users.setdefault(_fold(uid), (name, pw))  # the first row wins on a duplicate ID
    with _lock:
        _cache["key"], _cache["users"] = key, users
    return users


def verify(username, password):
    """The name to show (the file's Name, else the ID) when the pair is right, else None."""
    try:
        users = load_users()
    except UsersFileError:
        return None
    name, pw = users.get(_fold(username), ("", None))
    # Always compare something, so a wrong username and a wrong password take about the same time.
    ok = hmac.compare_digest(str(password or "").encode("utf-8"), (pw if pw is not None else "\0").encode("utf-8"))
    return name if (ok and pw is not None) else None


# ------------------------------------------------------------------ session helpers
def current_user():
    """The logged-in person's display name, or None. An account removed from the file is logged out at once."""
    uid = session.get("uid")
    if not uid:
        return None
    try:
        entry = load_users().get(uid)
    except UsersFileError:
        entry = None
    if not entry:
        session.clear()
        return None
    return entry[0]


def can_edit(user, squad=None):
    """Seam for roles (Step 8 of plan_for_sql.md): for now every logged-in user may edit every squad."""
    return bool(user)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return jsonify(ok=False, error="Please log in first."), 401
        return fn(*args, **kwargs)

    return wrapper


# ------------------------------------------------------------------ brute-force brake
_fails = {}


def _client_key(username):
    return (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(), _fold(username))


def _recent_fails(key, now):
    _fails[key] = [t for t in _fails.get(key, []) if now - t < FAIL_WINDOW]
    return len(_fails[key])


# ------------------------------------------------------------------ routes
@bp.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(silent=True) or {}
    username, password = str(body.get("username") or ""), str(body.get("password") or "")
    if not username.strip() or not password:
        return jsonify(ok=False, error="Enter your username and password."), 400
    key, now = _client_key(username), time.time()
    if _recent_fails(key, now) >= MAX_FAILS:
        return jsonify(ok=False, error="Too many wrong attempts. Wait a few minutes and try again."), 429
    try:
        load_users()
    except UsersFileError as e:
        return jsonify(ok=False, error=str(e)), 503
    name = verify(username, password)
    if not name:
        _fails.setdefault(key, []).append(now)
        return jsonify(ok=False, error="Wrong username or password."), 401
    _fails.pop(key, None)
    session.clear()
    session["uid"] = _fold(username)
    session.permanent = True
    return jsonify(ok=True, user=name)


@bp.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify(ok=True)


@bp.route("/api/me", methods=["GET"])
def api_me():
    user = current_user()
    return jsonify(ok=True, user=user, canEdit=can_edit(user))
