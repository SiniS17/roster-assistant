"""Login tests (Phase 1 of the Login and Linked Editing Plan).

Run:  python tests/test_auth.py        (or: pytest tests)

A temporary users.xlsx and the Flask test client: no credentials or network needed.
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import openpyxl  # noqa: E402

import app as web  # noqa: E402
import auth  # noqa: E402


def write_users(path, rows, header=("username", "password")):
    wb = openpyxl.Workbook()
    ws = wb.active
    if header:
        ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    st = os.stat(path)  # make the change visible even on a coarse file clock
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000 * write_users.n))
    write_users.n += 1


write_users.n = 1


def setup(rows=(("admin", "s3cret"), ("Kip", 12345))):
    path = os.path.join(tempfile.mkdtemp(), "users.xlsx")
    write_users(path, rows)
    auth.USERS_FILE = path
    auth._cache.update(key=None, users={})
    auth._fails.clear()
    return path, web.app.test_client()


def login(c, u="admin", p="s3cret"):
    return c.post("/api/login", json={"username": u, "password": p})


def test_login_me_logout():
    _, c = setup()
    assert c.get("/api/me").get_json()["user"] is None
    r = login(c)
    assert r.status_code == 200 and r.get_json()["user"] == "admin"
    me = c.get("/api/me").get_json()
    assert me["user"] == "admin" and me["canEdit"] is True
    assert c.post("/api/logout").get_json()["ok"]
    assert c.get("/api/me").get_json() == {"ok": True, "user": None, "canEdit": False}


def test_wrong_credentials_and_empty_fields():
    _, c = setup()
    assert login(c, "admin", "nope").status_code == 401
    assert login(c, "ghost", "s3cret").status_code == 401
    assert login(c, "admin", "S3CRET").status_code == 401  # passwords are case-sensitive
    assert c.post("/api/login", json={"username": "admin"}).status_code == 400
    assert c.post("/api/login", data="not json").status_code == 400
    assert c.get("/api/me").get_json()["user"] is None


def test_username_is_case_insensitive_and_numeric_passwords_work():
    _, c = setup()
    r = login(c, "  KIP ", "12345")  # Excel stores 12345 as a number
    assert r.status_code == 200 and r.get_json()["user"] == "Kip"  # shown as written in the file


def test_write_routes_need_a_login_and_reads_stay_open():
    _, c = setup()
    assert c.post("/api/khdt/export", json={"changes": [{"a": 1}]}).status_code == 401
    assert c.post("/run", data={}).status_code == 401
    assert c.get("/").status_code == 200
    # preview writes nothing: it is open (it fails on the missing file, not on a login)
    assert c.post("/api/khdt/preview", data={}).status_code == 400
    login(c)
    # past the guard: the route's own validation answers
    r = c.post("/api/khdt/export", json={"changes": []})
    assert r.status_code == 400 and "no kept changes" in r.get_json()["error"]
    assert c.post("/run", data={}).status_code in (302, 400)  # its own 'choose a file' message, not 401
    c.post("/api/logout")
    assert c.post("/api/khdt/export", json={"changes": [{"a": 1}]}).status_code == 401


def test_name_id_password_layout_logs_in_with_the_id():
    path, c = setup()
    write_users(path, [("Phan Minh Khoa", "VAE02012", "abc"), ("Trần Đức Trung", "VAE03274", 123)],
                header=("Name", "ID", "Password"))
    r = login(c, "vae02012", "abc")  # ID is case-insensitive
    assert r.status_code == 200 and r.get_json()["user"] == "Phan Minh Khoa"  # shows the Name
    assert c.get("/api/me").get_json()["user"] == "Phan Minh Khoa"
    assert login(c, "Phan Minh Khoa", "abc").status_code == 401  # the name is not a username
    assert login(c, "VAE03274", "123").status_code == 200  # numeric password


def test_repo_accounts_file_has_a_readable_layout():
    repo_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Database", "users.xlsx")
    if not os.path.exists(repo_file):
        return
    auth.USERS_FILE = repo_file
    auth._cache.update(key=None, users={})
    users = auth.load_users()
    assert users and all(name and pw for name, pw in users.values())


def test_accounts_file_is_re_read_when_it_changes():
    path, c = setup()
    assert login(c, "new", "pw").status_code == 401
    write_users(path, [("admin", "s3cret"), ("new", "pw")])
    assert login(c, "new", "pw").status_code == 200  # no restart needed


def test_removed_account_is_logged_out_at_once():
    path, c = setup()
    login(c, "Kip", "12345")
    assert c.get("/api/me").get_json()["user"] == "Kip"
    write_users(path, [("admin", "s3cret")])
    assert c.get("/api/me").get_json()["user"] is None
    assert c.post("/api/khdt/export", json={"changes": [{"a": 1}]}).status_code == 401


def test_missing_or_malformed_accounts_file():
    path, c = setup()
    os.remove(path)
    r = login(c)
    assert r.status_code == 503 and "make_users" in r.get_json()["error"]
    write_users(path, [("admin", "s3cret")], header=("name", "pass"))
    r = login(c)
    assert r.status_code == 503 and "username" in r.get_json()["error"]


def test_too_many_wrong_passwords_are_slowed_down():
    _, c = setup()
    for _ in range(auth.MAX_FAILS):
        assert login(c, "admin", "bad").status_code == 401
    assert login(c, "admin", "s3cret").status_code == 429  # even the right one waits
    auth._fails.clear()
    assert login(c).status_code == 200


def test_failed_attempts_expire():
    _, c = setup()
    for _ in range(auth.MAX_FAILS):
        login(c, "admin", "bad")
    key = next(iter(auth._fails))
    auth._fails[key] = [time.time() - auth.FAIL_WINDOW - 1] * auth.MAX_FAILS
    assert login(c).status_code == 200


def test_make_users_script_creates_a_working_file():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
    import make_users

    path = os.path.join(tempfile.mkdtemp(), "Database", "users.xlsx")
    assert make_users.main(["--file", path, "--username", "boss", "--password", "pw1"]) == 0
    assert make_users.main(["--file", path]) == 1  # refuses to overwrite
    auth.USERS_FILE = path
    auth._cache.update(key=None, users={})
    assert auth.verify("boss", "pw1") == "boss" and auth.verify("boss", "x") is None


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok   ", name)
            except Exception as e:  # noqa: BLE001
                failed += 1
                print("FAIL ", name, "->", type(e).__name__, e)
    sys.exit(1 if failed else 0)
