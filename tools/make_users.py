"""Create Database/users.xlsx with one admin account.

Run from the repo root:
    python tools/make_users.py                       # user 'admin', random password (printed once)
    python tools/make_users.py --username kip --password "S0me-pass"
    python tools/make_users.py --force               # replace an existing file

More accounts: open the file in Excel and add rows (username | password); no restart needed.
The file holds plain-text passwords: it is in .gitignore, keep it that way.
"""

import argparse
import os
import secrets
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import auth  # noqa: E402
from openpyxl import Workbook  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default=None, help="default: a random one, printed once")
    ap.add_argument("--file", default=auth.USERS_FILE)
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    a = ap.parse_args(argv)

    if os.path.exists(a.file) and not a.force:
        print(f"{a.file} already exists. Add accounts in Excel, or use --force to replace it.", file=sys.stderr)
        return 1
    password = a.password or secrets.token_urlsafe(9)
    os.makedirs(os.path.dirname(os.path.abspath(a.file)), exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "users"
    ws.append(["username", "password"])
    ws.append([a.username, password])
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 28
    wb.save(a.file)
    print(f"Created {a.file}\n  username: {a.username}\n  password: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
