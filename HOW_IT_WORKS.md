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

## Roster page (built from the squads, read-only)

There is no single "everyone in one sheet" roster any more. The Roster page is
built from the **1st sheet of each squad spreadsheet** (`SQUAD_SHEET_URLS` in
`config.py`: Squad 1 to Squad 4).

**Who is in a squad.** On the 1st sheet, the roster table (header with `ORD`,
`NAME AND SURNAME`, `ID`, ...) lists the members from the top down until the
FIRST of these:
- a **"tăng cường"** row (reinforcements from elsewhere - matched ignoring
  accents/case, so `TĂNG CƯỜNG` works; a person's own REMARK mentioning it does
  not count), or
- the **first end of the ORD numbering** (ORD blank / not a number, or it stops
  increasing, e.g. a second list starting again at 1).

Everything below that point is not a member of that squad.

**If a person is in more than one squad** they stay in the lowest-numbered one
(Squad 1 beats 2, 2 beats 3, 3 beats 4). The page shows a note with how many
people that affected.

The day columns (dates in the header row) come from each squad's own 1st
sheet; the page shows the union of all squads' days. A squad that can't be read
is reported in the note bar and the other squads still show. Side menu →
**Roster** always returns to this all-squads view; the Squad filter at the top
narrows it to one squad.

## Daily Distribution page (read-only)

Side menu → **Daily Distribution** (or open `/#distribution`). It reads the
same squad spreadsheets - tabs are labelled `Squad 1 · <A/C>`... - and shows who goes to
which zone on a chosen day. It never writes to them.

**The crew strip comes from the roster.** For the chosen day, anyone in that
squad whose roster cell for that day contains **`TĐ`** is *Trực đội*, **`FM`** is
*Foreman*, and **`PPC`** is *Dock planner* (the code is matched as its own word,
ignoring accents/case; several people can hold one role; phones come from the
squad's phone book). The codes live in `CREW_ROSTER_CODES` in `config.py`.
*Shift / Tech supp* is still the label on the squad's 1st sheet.

**Each spreadsheet is expected to look like this**
- **1st sheet** - general info. Found by label, so exact cells don't matter:
  `A/C`, `CHECK`, `DATE` (e.g. `21-29 SEP 2026`, or two date cells),
  `FOREMAN`, `TRỰC ĐỘI`, `DOCK PLANNER`, `SHIFT / TECH SUPP` (name, then phone
  next to it or below it), plus any rows that hold an employee ID and a phone
  number - that is the phone book used for the PHONE column.
- **Every other sheet** - one day, named `<A/C>-<MMM><DD>` (e.g. `B218-SEP21`).
  It holds `ORD / NAME AND SURNAME / ID / POSITION / REMARK` tables split by
  section rows (`ZONE 128`, `ZONE 128 @16H00`, `ZONE AVI`, `STRUCTURE PAINTING`...).
  `ZONE ...` sections fill the left column (`@16H00`-style ones get a sun/moon
  icon); the right column always lists Structure Sheet Metal / Composite /
  Painting and Cabin, showing "No personnel assigned" until a section with that
  name has people. A red REMARK in the sheet stays red on the page.
- Sheets that don't match the name pattern (notes, templates) are ignored.

**Setup**
1. Ask each owner to share their spreadsheet with the service-account email as
   **Viewer** (the same bot email already used for the Roster; it only needs
   view access here - the page asks Google for read-only scopes).
2. Put the links in `SQUAD_SHEET_URLS` in `config.py` (named `Squad 1` ...
   `Squad 4`; the order is the priority order), or set the `SQUAD_SHEET_URLS`
   environment variable (one URL per line or comma-separated, first = Squad 1) -
   the variable wins if both are set. The old `DISTRIBUTION_SHEET_URLS`
   variable is still read as a fallback.
3. Enable the **Google Drive API** in the same Google Cloud project *only if*
   some of those files are uploaded `.xlsx` files that were opened in Google
   Sheets (the Sheets API can't read those; the page then downloads them
   through Drive instead). Native Google Sheets need nothing extra.

A spreadsheet that can't be read shows a `!` on its tab with the reason; the
others keep working. Data is cached for `DISTRIBUTION_CACHE_SECONDS` (60 s);
the reload button always fetches fresh data.

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

Then open `http://localhost:5000`. For a KHDT run, use side menu → **KHDT → Roster**,
upload the KHDT file, paste the URL of the Google Sheet to update (it needs `Main`
and `temp` tabs - there is no built-in default any more), and click **Run**.

Tests (no Google access needed): `python -m unittest discover -s tests -v`

## Configuration

Edit `config.py`:
- `SQUAD_SHEET_URLS` — the squad spreadsheets, `Squad 1` ... `Squad 4`, in
  priority order (see "Roster page" above).
- `SQUAD_MEMBER_STOP_LABEL` — the text that ends a squad's member list
  (`tăng cường`).
- `CREW_ROSTER_CODES` — roster codes that make someone Trực đội (`TĐ`), Foreman
  (`FM`) or Dock planner (`PPC`) on the Daily Distribution page.
- `COURSE_ABBREVIATIONS` / `COURSE_NAME_ABBREVIATIONS` — marker shorthand.
- `MARKER_PREFIX` — defaults to `H`.
- `LOG_COLUMN_HEADERS` / `LOG_EVENT_LABELS` — labels used in the log file.

## Project files

| File | Purpose |
|---|---|
| `app.py` | Flask routes: roster page, `/run`, `/api/roster`, `/api/distribution*` |
| `engine.py` | All KHDT-parsing and Roster-matching/marking logic |
| `sheets_client.py` | Google Sheets read/write (service-account auth) |
| `squads.py` | Roster page: squad members from each 1st sheet, Squad 1→4 priority merge |
| `distribution.py` | Daily Distribution: reads the squad spreadsheets, parses info + day tabs |
| `log_workbook.py` | Builds the downloadable `.xlsx` run log |
| `config.py` | Squad sheet URLs, abbreviations, log labels |
| `tests/` | Unit tests for `squads.py` (synthetic grids, no Google access) |
| `templates/`, `static/` | Upload form + results page |
