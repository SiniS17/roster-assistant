"""
app.py
================
Website version of the KHDT -> Roster tool.

GET /            roster page (reads the built-in default Roster Google Sheet)
GET /api/roster  roster grid as JSON (?url=<sheet url>&gid=<tab id>)
POST /run        KHDT upload. Changes go to the 'temp' tab, never straight into 'Main'.
                  With the page's fetch() call it answers JSON;
                 a plain browser form post still gets the old result page.

See HOW_IT_WORKS.md for what this does to your files/sheet, and the
"Setup" section of that file for the Google service-account steps.
"""

import base64
import io
import os

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from config import DEFAULT_ROSTER_SHEET_URL
from engine import load_khdt, mark_roster_grid
from log_workbook import write_log_workbook
from roster_view import build_roster_payload, diff_main_temp, find_tab, list_tabs, rebuild_temp, tab_url
from sheets_client import parse_sheet_url, read_roster_grid, write_roster_updates

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


def _wants_json():
    return request.headers.get("X-Requested-With") == "fetch"


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", default_sheet_url=DEFAULT_ROSTER_SHEET_URL)


@app.route("/api/roster", methods=["GET"])
def api_roster():
    sheet_url = (request.args.get("url") or "").strip() or DEFAULT_ROSTER_SHEET_URL
    gid = (request.args.get("gid") or "").strip()
    try:
        spreadsheet_id, _ = parse_sheet_url(sheet_url)
        tabs = list_tabs(spreadsheet_id)
        main_tab, temp_tab = find_tab(tabs, "main"), find_tab(tabs, "temp")
        if not gid.isdigit() and main_tab:
            gid = str(main_tab["gid"])  # open on Main unless a tab was asked for
        if gid.isdigit():
            sheet_url = tab_url(spreadsheet_id, gid)
        _, sheet_id, title, values, colors = read_roster_grid(sheet_url)
        payload = build_roster_payload(title, values, colors)
    except Exception as e:
        return jsonify(ok=False, error=f"{type(e).__name__}: {e}"), 400

    # Compare Main with temp (best effort - never blocks the roster itself).
    payload["view"] = title.strip().lower()
    payload["pending"] = 0
    payload["changed"] = {}
    if main_tab and temp_tab and payload["view"] in ("main", "temp"):
        try:
            other_tab = temp_tab if payload["view"] == "main" else main_tab
            _, _, o_title, o_values, o_colors = read_roster_grid(tab_url(spreadsheet_id, other_tab["gid"]))
            other = build_roster_payload(o_title, o_values, o_colors)
            main_p, temp_p = (payload, other) if payload["view"] == "main" else (other, payload)
            changed = diff_main_temp(main_p, temp_p)
            payload["pending"] = len(changed)
            if payload["view"] == "temp":
                payload["changed"] = changed
        except Exception:
            pass

    payload.update(
        ok=True,
        tabs=tabs,
        gid=sheet_id,
        sheet_url=f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={sheet_id}",
    )
    return jsonify(payload)


@app.route("/run", methods=["POST"])
def run():
    khdt_file = request.files.get("khdt_file")
    sheet_url = (request.form.get("sheet_url") or "").strip() or DEFAULT_ROSTER_SHEET_URL
    force = request.form.get("force") == "on"
    keep = request.form.get("keep") == "on"

    def fail(message, status=400):
        if _wants_json():
            return jsonify(ok=False, error=message), status
        flash(message)
        return redirect(url_for("index"))

    if not khdt_file or khdt_file.filename == "":
        return fail("Please choose a KHDT .xlsx file.")

    log_lines = []
    event_log = {}

    try:
        khdt_rows = load_khdt(khdt_file.stream)
        log_lines.append(f"Loaded {len(khdt_rows)} KHDT rows from {khdt_file.filename}")

        spreadsheet_id, _ = parse_sheet_url(sheet_url)
        tabs = list_tabs(spreadsheet_id)
        main_tab, temp_tab = find_tab(tabs, "main"), find_tab(tabs, "temp")
        if not main_tab:
            raise ValueError("Couldn't find a tab named 'Main' in that spreadsheet - rename the live roster tab to 'Main'.")

        # Base = Main (fresh start) or the current temp (keep earlier temp changes).
        use_temp_base = keep and temp_tab is not None
        base_tab = temp_tab if use_temp_base else main_tab
        _, _, title, values, colors = read_roster_grid(tab_url(spreadsheet_id, base_tab["gid"]))
        log_lines.append(f"Loaded Roster tab '{title}' ({len(values)} rows x {len(values[0]) if values else 0} cols)")

        stats, updates = mark_roster_grid(
            khdt_rows, values, colors, force=force, log=log_lines.append, event_log=event_log
        )

        if use_temp_base:
            temp_gid = temp_tab["gid"]
        else:
            temp_gid = rebuild_temp(spreadsheet_id, main_tab["gid"])
            log_lines.append("Reset tab 'temp' to a fresh copy of 'Main'")
        sheet_id = temp_gid
        if updates:
            write_roster_updates(spreadsheet_id, temp_gid, updates)
        log_lines.append(f"Wrote {len(updates)} cell change(s) to tab 'temp' - 'Main' was not touched")
    except Exception as e:
        return fail(f"Error: {type(e).__name__}: {e}")

    log_buffer = io.BytesIO()
    write_log_workbook(log_buffer, event_log, log_lines, stats)
    log_b64 = base64.b64encode(log_buffer.getvalue()).decode("ascii")

    if _wants_json():
        return jsonify(
            ok=True,
            stats=stats,
            log=log_lines,
            log_b64=log_b64,
            gid=sheet_id,
            sheet_url=sheet_url,
            updated=[[u["row"], u["col"]] for u in updates],
        )

    return render_template(
        "result.html",
        stats=stats,
        log_lines=log_lines,
        sheet_url=sheet_url,
        log_b64=log_b64,
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
