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

## Roster page (read-only, built from the 4 squads' spreadsheets)

The main page (`/`) no longer reads the KHDT sheet's Main tab. It is built from the **1st
sheet of each squad's spreadsheet** - the same four spreadsheets as Daily Distribution
(`DISTRIBUTION_SHEET_URLS` / `DISTRIBUTION_SHEET_NAMES` in `config.py`) - using view-only
access (a Viewer share is enough).

- One row per employee; the **Đội** filter picks a squad (Squad 1 ... Squad 4). The day
  columns are the union of every squad's dates.
- A squad's 1st sheet needs a header row with `ID` + `NAME` and a real date per day column. If
  the NAME header can't be read (Squad 1's sits under the logo), the column just left of `ID`
  is used.
- Only rows with an employee ID are kept, and a squad's list stops at the `NV TĂNG CƯỜNG`
  (reinforcement) row, so summary rows and borrowed staff don't appear.
- Someone listed in two squads is shown once, in the first squad (the page says so).
- A squad that can't be read is skipped and named in a yellow bar; the other squads still show.
- The reload button refetches (otherwise a 60 s cache applies). "Open Google Sheet" opens the
  filtered squad's spreadsheet.

## KHDT -> Roster: review first, export when you are happy

The KHDT upload (side menu -> **KHDT -> Roster**) no longer writes to the old Main/temp sheet. It
proposes changes to the **same four squad sheets the roster page shows**:

1. **Run.** The KHDT file is matched against each squad's 1st sheet with the usual rules (markers,
   weekend `N`, conflicts, `--force`). Nothing is written to Google Sheets. The squad sheets are read
   fresh, and someone listed in two squads belongs to the first one (as on the page).
2. **Review.** Every cell that would change is highlighted on the roster: dashed + flickering green =
   undecided, solid green = kept, dotted grey = rejected, amber outline = it would replace or extend
   something that is already in the cell. Click a highlighted box for **Keep / Reject / Undecided**
   (a multi-day box acts on all its days), or use the **Review list** (filter, search, per-cell
   buttons) and the bulk buttons **Keep undecided / Reject undecided**. "Only changed rows" hides
   everyone else.
3. **Your decisions are yours alone.** They (and the proposed changes) are stored in this browser's
   `localStorage`, so a reload keeps them, while other people and other devices/browsers see the plain
   roster. Nothing about the review is stored on the server. Clearing the browser's site data or pressing
   **Discard** forgets it.
4. **Export.** **Export N kept -> sheets** writes only the kept cells into the real squad sheets (the 1st
   sheet of each of the four spreadsheets; each must be shared with the service account as **Editor**).
   Before writing, every cell is re-read: if the employee moved to another row, the date column moved, or
   somebody edited the cell after the run, that cell is **skipped and reported**, never overwritten. The
   page then reloads from the sheets; written cells equal the proposal, so they leave the review by
   themselves.
5. **Out of date.** If a cell is edited in the sheet after the run, its change turns "out of date" and is
   ignored (and cannot be exported). Run KHDT again to refresh. Running KHDT again replaces the current
   review (the page asks first).

Safety: every proposed change is signed with the app's `FLASK_SECRET_KEY`, and export only writes
changes that carry a valid signature - so set a real `FLASK_SECRET_KEY` in production. A squad whose
file is an uploaded `.xlsx` (not a native Google Sheet) can be reviewed but not exported.

The old flow (`POST /run`, writing to the KHDT sheet's `temp` tab) still exists in `app.py` but the
page no longer uses it.

## Daily Distribution page (read-only)

Side menu → **Daily Distribution** (or open `/#distribution`). It reads several
other Google spreadsheets - one per aircraft/check - and shows who goes to
which zone on a chosen day. It never writes to them.

**Each spreadsheet is expected to look like this**
- **1st sheet** - general info. Found by label, so exact cells don't matter:
  `A/C`, `CHECK`, `DATE` (e.g. `21-29 SEP 2026`, or two date cells),
  `FOREMAN`, `TRỰC ĐỘI`, `DOCK PLANNER`, `SHIFT / TECH SUPP` (name, then phone
  next to it or below it), plus any rows that hold an employee ID and a phone
  number - that is the phone book used for the PHONE column.
- **If the 1st sheet is a monthly roster** (header row with `ID` + `NAME`, one date
  column per day) the crew header is read from it for the selected day: anyone whose
  cell holds `TĐ` (Trực đội), `PPC` (Dock planner) or `FM` (Foreman) - alone or with
  a shift/aircraft, like `TĐ-SAG`, `TĐ @16:00`, `A326-FM`. Several people can share
  a role. These roster codes win over the `FOREMAN:`-style labels; the codes come
  from `DISTRIBUTION_ROLE_MARKERS` in `config.py`.
- **Every other sheet** - one day, named `<A/C>-<MMM><DD>` (e.g. `B218-SEP21`).
  A zero-padded day is fine (`A326-OCT09`, `A326-OCT011` = Oct 11). Text before the
  aircraft is kept as the day's CHECK (`WO COMP A611-OCT07` -> A/C `A611`, CHECK
  `WO COMP`). A tab named only with a number (`1`, `14`) is that day of the month
  the 1st sheet is a roster for (read from `THÁNG 10.2026` in its top rows, or from
  a tab name like `Doi 3 Thang 10`, or - when the 1st sheet has no month text, like
  Squad 1/4's `ROSTER` - the dates over its day columns). The A/C shown is the one in
  each day's own tab name, else the `A/C:` on the day tab itself; with neither, the page
  shows just the date. It holds `ORD / NAME AND SURNAME / ID / POSITION / REMARK` tables split by
  section rows (`ZONE 128`, `ZONE 128 @16H00`, `ZONE AVI`, `STRUCTURE PAINTING`...).
  `ZONE ...` sections fill the left column (`@16H00`-style ones get a sun/moon
  icon); the right column always lists Structure Sheet Metal / Composite /
  Painting and Cabin, showing "No personnel assigned" until a section with that
  name has people. A red REMARK in the sheet stays red on the page.
- **Squad 1/4 layout**: the 1st sheet is `ROSTER`; day tabs are named `1`, `2` ...
  Each day tab has its own info block (`A/C: A864`, `FOREMAN:`, `BCH ĐỘI` = Trực đội,
  `TECH SUPPORT`, `DOCK PLANNER:`, each with `PHONE:` next to it; `#N/A` = nobody), then two
  tables side by side with `ORD / NAME AND SURNAME / VAECO ID / POSITION / PHONE / REMARK`
  (any `<word> ID` header works). Section titles like `A864-128` count as zones. A note in
  REMARK/PHONE/POSITION on a row with no person is not a section. A person row with an ID
  but no name yet is still listed. For the crew, labels on the day tab win over the
  `TĐ`/`PPC`/`FM` codes in the roster.
- Sheets that don't match the name pattern (notes, templates) are ignored.

**Setup**
1. Ask each owner to share their spreadsheet with the service-account email as
   **Viewer** (the same bot email already used for the Roster; it only needs
   view access here - the page asks Google for read-only scopes).
2. Put the links in `DISTRIBUTION_SHEET_URLS` in `config.py` (one per line, as
   many as you need), or set the `DISTRIBUTION_SHEET_URLS` environment variable
   (one URL per line or comma-separated) - the variable wins if both are set.
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

Then open `http://localhost:5000`, open the side menu -> **KHDT -> Roster**, upload the KHDT
file and click **Run**. Review the highlighted changes on the roster, then **Export** the ones you kept.

## Configuration

Edit `config.py`:
- `DEFAULT_ROSTER_SHEET_URL` — only used by the old `/run` flow now (the KHDT sheet with Main/temp).
- `DISTRIBUTION_SHEET_URLS` / `DISTRIBUTION_SHEET_NAMES` — the Daily Distribution
  spreadsheets and their tab names, matched by position (1st URL = Squad 1 ...
  last = Squad 4).
- `DISTRIBUTION_ROLE_MARKERS` — roster codes for the crew roles: Trực đội = `TĐ`,
  Dock planner = `ppc`, Foreman = `fm`.
- `COURSE_ABBREVIATIONS` / `COURSE_NAME_ABBREVIATIONS` — marker shorthand.
- `MARKER_PREFIX` — defaults to `H`.
- `LOG_COLUMN_HEADERS` / `LOG_EVENT_LABELS` — labels used in the log file.

## Project files

| File | Purpose |
|---|---|
| `app.py` | Flask routes: roster page, `/api/roster`, `/api/khdt/preview`, `/api/khdt/export`, `/api/distribution*`, old `/run` |
| `khdt_review.py` | KHDT -> proposed changes on the squads' sheets (signed), and the checked export |
| `engine.py` | All KHDT-parsing and Roster-matching/marking logic |
| `sheets_client.py` | Google Sheets read/write (service-account auth) |
| `distribution.py` | Daily Distribution: reads the other spreadsheets, parses info + day tabs |
| `squad_roster.py` | The roster page: merges the 1st sheet of each squad's spreadsheet |
| `log_workbook.py` | Builds the downloadable `.xlsx` run log |
| `config.py` | Abbreviations, log labels, default Sheet URL |
| `templates/`, `static/` | Upload form + results page |
