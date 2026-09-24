# KHDT → Roster (website version) — How it works

A small internal website for VAECO. You upload the **KHDT** (training-plan)
Excel file; it's matched against the **Roster**, which now lives in a Google
Sheet, and the matching days get marked directly in that Sheet.

## What you need before running it

**1. The KHDT file** — an `.xlsx` export of the monthly training plan. It
needs a header row (anywhere in the first 30 rows) containing at least these
Vietnamese column headers (exact wording, spacing, and column order don't
matter — they're found by searching):
- `Mã NV` — employee ID
- `Họ tên` — name
- `Bắt đầu` / `Kết thúc` — training start/end date
- `Phòng/đội`, `Tên KĐT`, `Mã lớp học`, `Lí do` are read too, if present

**2. The Roster** — a Google Sheet, not a file upload. It needs a header row
with `ID` and `NAME` (or `NAME & SURNAME`) columns, plus a run of real date
cells across that same row — one per day of the month. Each person's row
below that has their employee ID and one cell per day.

**3. Access to that Sheet.** This tool authenticates as a Google *service
account*, not as you — so the Sheet must be explicitly shared with the
service account's email address (Editor access), the same way you'd share
it with a colleague. See **Setup**, below.

## What the code does to your data, step by step

1. **Finds the header rows automatically** in both the KHDT file and the
   Roster sheet, by searching for the column labels above — not tied to a
   fixed row number, so reordered/reshuffled columns still work.

2. **Matches people by Employee ID.** For every KHDT row, the ID is looked
   up in the Roster. If found, the Name is compared too, only as a sanity
   check — a mismatch is logged as a warning, but the ID is trusted and the
   row is still processed.

3. **Works out which day(s) to mark:**
   - Normally, every day from `Bắt đầu` to `Kết thúc` (inclusive) that
     falls inside the Roster's date range gets marked.
   - **Exception:** if the `Lí do` note pins down one specific day — phrased
     as *"Lên lớp sáng/chiều &lt;date&gt;"* ("attend class in the
     morning/afternoon of &lt;date&gt;") — only that single day is marked,
     even if `Bắt đầu`/`Kết thúc` span a wider range (e.g. a week of
     self-study with one actual class day in it).

4. **Builds the marker text**, e.g. `H ATHK`, `H VHDN CHIỀU` — the course
   abbreviation (edit `COURSE_ABBREVIATIONS` / `COURSE_NAME_ABBREVIATIONS`
   in `config.py`) prefixed with `H`, with `SÁNG`/`CHIỀU` appended when the
   note says which half of the day.

5. **Combines same-day overlaps.** If two different KHDT rows land the same
   person on the same day (typically one morning class, one afternoon
   class), they're written as one combined marker instead of one
   overwriting the other, e.g. `H VHNT SÁNG-VHDN CHIỀU`.

6. **Saturdays and Sundays are always `N`** (day off), regardless of what
   KHDT says — course markers never get written on a weekend. Weekday
   course markers are written in **red**; the weekend `N` is written in
   **black**.

7. **Handles what's already in the cell:**
   - Empty cell → marker is written.
   - Already has the exact course, or a subset of a combined marker → left
     alone (logged as "already marked", not duplicated).
   - Already has a **black** `N` → treated as an ordinary blank day off and
     overwritten with the course (or with `N` again on a weekend) — this
     is not a conflict.
   - Already has a **red** `N` (a guaranteed/protected day off) or some
     unrelated content → by default this is a **conflict**: nothing is
     overwritten, and the intended value is appended instead
     (`existing-new`) so no information is lost. Tick **"Overwrite cells
     that already have content"** on the form to force a plain overwrite
     instead.

8. **A known KHDT date bug is corrected automatically.** Some KHDT date
   cells are stored as `YYYY-DD-MM` (day/month swapped from the usual
   order) rather than `YYYY-MM-DD`. Real Excel date cells are un-swapped
   automatically; plain slash-text dates (`10/09/2026`) are already in
   normal order and read as-is. Anything that still looks implausible
   afterwards (wrong month/year for this Roster) is logged as a `[CHECK]`
   line rather than silently guessed at.

9. **Writes the result straight back to the Google Sheet** — only the
   individual cells that changed, preserving everything else on the sheet
   (formatting, other columns, other rows) untouched.

10. **Produces a downloadable `.xlsx` log** with three tabs: a per-person
    event log (conflicts, overlaps, name mismatches, etc.), a run summary,
    and the raw console log — plus a results page in the browser showing
    the same summary.

Nothing is ever written to KHDT — it's read-only input.

## Setup (Google Sheets access)

1. In Google Cloud Console, create (or reuse) a project, enable the
   **Google Sheets API**, and create a **Service Account**.
2. Create a JSON key for that service account and download it.
3. Open the Roster Google Sheet and **Share** it with the service account's
   email address (looks like `something@project-id.iam.gserviceaccount.com`),
   giving it **Editor** access.
4. Give the app the credentials, either:
   - **Local dev:** save the JSON key file somewhere and set
     `GOOGLE_APPLICATION_CREDENTIALS=./path/to/key.json` in `.env`.
   - **Hosted (e.g. Vercel):** paste the entire JSON key's contents as a
     single-line environment variable `GOOGLE_SERVICE_ACCOUNT_JSON`.
5. Copy `.env.example` to `.env` and fill in the values (also set
   `FLASK_SECRET_KEY` to any random string).

## Running it locally

```
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`, upload the KHDT file, confirm/edit the
Roster Sheet URL (defaults to the one configured in `config.py`), and click
**Run**.

## Configuration

Edit `config.py`:
- `DEFAULT_ROSTER_SHEET_URL` — pre-fills the form; users can still paste a
  different sheet URL (e.g. a different team or month).
- `COURSE_ABBREVIATIONS` / `COURSE_NAME_ABBREVIATIONS` — marker shorthand.
- `MARKER_PREFIX` — defaults to `H`.
- `LOG_COLUMN_HEADERS` / `LOG_EVENT_LABELS` — labels used in the log file.

## Project files

| File | Purpose |
|---|---|
| `app.py` | Flask routes: upload form, `/run` processing + results page |
| `engine.py` | All KHDT-parsing and Roster-matching/marking logic |
| `sheets_client.py` | Google Sheets read/write (service-account auth) |
| `log_workbook.py` | Builds the downloadable `.xlsx` run log |
| `config.py` | Abbreviations, log labels, default Sheet URL |
| `templates/`, `static/` | Upload form + results page |
