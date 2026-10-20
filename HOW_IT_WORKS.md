# Roster Assistant — How it works

A small internal website for VAECO. It does three things, all driven by Google Sheets:

1. **Roster** — shows the monthly roster of the four squads in one table (read-only).
2. **KHDT → Roster** — you upload the monthly **KHDT** (training-plan) Excel file; the app works out which roster cells should be marked as training days, shows them as **proposed changes** on the roster, lets you keep or reject each one, and only then writes the kept ones into the squads' Google Sheets.
3. **Daily Distribution** — shows, for a chosen day, which person is assigned to which zone, read from the squads' day tabs (read-only).

There is no database and nothing is stored on the server. The Google Sheets are the single source of truth; the only things kept outside them are a short-lived in-memory cache on the server and, in each person's own browser, the KHDT review in progress and a few display preferences.

```
 KHDT .xlsx ──upload──►  /api/khdt/preview ──► proposed changes (signed, nothing written)
                              │                        │
                              │ reads                  ▼
                              ▼                 browser: highlight on roster,
              1st sheet of each squad's         Keep / Reject (saved in localStorage)
              Google spreadsheet  ◄───────────────────┐
                              ▲                        │ kept changes
                              │ re-checks + writes     ▼
                              └────────────────  /api/khdt/export
```

---

## 1. What you need before running it

**A. Google access (service account).** The app signs in to Google as a *service account*, not as a person. Every spreadsheet it touches must be shared with that account's email address (it looks like `something@project-id.iam.gserviceaccount.com`):

| Spreadsheet | Needed for | Share as |
|---|---|---|
| Each of the 4 squads' spreadsheets | Roster page, Daily Distribution, KHDT preview | **Viewer** is enough to read |
| Each of the 4 squads' spreadsheets | **Exporting** KHDT changes | **Editor** |

**B. The squads' spreadsheets.** Their links are listed in `config.py` (`DISTRIBUTION_SHEET_URLS`, one per squad, named by `DISTRIBUTION_SHEET_NAMES`). The **1st sheet** of each spreadsheet is that squad's monthly roster; the other sheets are day tabs (see §5 and §6 for the exact layout).

**C. The KHDT file** — an `.xlsx` export of the monthly training plan (first worksheet is read). See §4.1.

---

## 2. Setup (Google credentials)

1. In Google Cloud Console create (or reuse) a project, enable the **Google Sheets API**, and create a **Service Account**.
2. Create a JSON key for it and download it.
3. Share each squad spreadsheet with the service account's email (Viewer to read, Editor if you want to export KHDT changes).
4. Give the app the credentials, either:
   - **Local:** save the key file and set `GOOGLE_APPLICATION_CREDENTIALS=./path/to/key.json` in `.env`.
   - **Hosted (e.g. Vercel):** paste the whole key as a **single-line, minified** JSON into the environment variable `GOOGLE_SERVICE_ACCOUNT_JSON`. Do not wrap it in extra quotes, and redeploy after setting it. If the value isn't valid JSON the app says so (with the length and first characters) instead of failing obscurely.
5. Copy `.env.example` to `.env` and set `FLASK_SECRET_KEY` to a long random string. **This is not optional in production**: it is the key that signs every proposed KHDT change (see §4.4). If it changes between a KHDT run and the export, the export is refused and you have to run KHDT again.
6. Enable the **Google Drive API** in the same project *only if* some squad file is an uploaded `.xlsx` that was opened in Google Sheets rather than a native Google Sheet. The Sheets API can't read those, so the app downloads them through Drive (read-only). Native Google Sheets need nothing extra.

Scopes the app asks for: full Sheets access (only used by the KHDT export and the legacy flow), and **read-only** Sheets/Drive access for everything else — so the Roster page and Daily Distribution can never modify a spreadsheet.

## 3. Running it locally

```
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`. The side menu has **Roster**, **Daily Distribution** and **KHDT → Roster**. `PORT` can be set in the environment (default 5000).

### Configuration (`config.py`)

- `DISTRIBUTION_SHEET_URLS` / `DISTRIBUTION_SHEET_NAMES` — the four squad spreadsheets and their display names, matched **by position** (1st URL = Squad 1 … last = Squad 4). `DISTRIBUTION_SHEET_URLS` can also be set as an environment variable (one URL per line or comma-separated), which wins over the file.
- `DISTRIBUTION_ROLE_MARKERS` — roster codes for crew roles: Trực đội = `TĐ`, Dock planner = `ppc`, Foreman = `fm`.
- `DISTRIBUTION_CACHE_SECONDS` — server cache lifetime (60 s).
- `COURSE_ABBREVIATIONS` / `COURSE_NAME_ABBREVIATIONS` — short labels for courses.
- `MARKER_PREFIX` — the prefix of every course marker (default `H`).
- `LOG_COLUMN_HEADERS` / `LOG_EVENT_LABELS` — the wording used in the downloadable log.
- `DEFAULT_ROSTER_SHEET_URL` — only used by the legacy Main/temp flow (§8).

---

## 4. Roster page and KHDT → Roster

### 4.1 The Roster page (read-only)

`GET /api/roster` builds one table from the **1st sheet of each squad's spreadsheet**:

- **Finding the table.** In the first 30 rows the app looks for a header row with an **ID** column and a **NAME** column plus one date per day. Headers are matched ignoring accents, case and punctuation, and several wordings are accepted (`ID`, `MÃ VAECO`, `VAECO ID`, `HỌ VÀ TÊN`, `NAME AND SURNAME`, …). Day columns are real dates; if the header only holds bare day numbers (`01`…`31`), those days are read as belonging to the **current month**. If the NAME header can't be read (Squad 1's sits under a logo), the nearest mostly-text column to the left of ID is used.
- **Who is listed.** Only rows with a real employee ID (letters + digits, like `VAE12345`). A squad's own list **stops at the `NV TĂNG CƯỜNG` (reinforcement) row**; everyone below belongs to other squads or is a summary.
- **Merging squads.** One row per employee, with the squad's name in an **Đội** column (the page's Đội filter picks a squad). Day columns are the union of every squad's dates. Anyone listed in two squads is shown once, in the first squad, and a note says so.
- **Extra columns.** Any other labelled column left of the first date (position, group, …) is shown as small text under the employee's name (STT/TT/No/# columns are skipped).
- **Failures are isolated.** A squad that can't be read is skipped and named in a yellow bar; the others still show.
- **Page features.** Search by name or ID, Đội filter, zoom, light/dark theme, a headcount/training-days/guaranteed-days-off strip, a colour legend, and a reload button (otherwise the server's 60 s cache applies). Cell types are shown differently: `H …` course markers, black `N`, red `N` (guaranteed day off), and other codes (each gets its own colour). "Open Google Sheet" opens the filtered squad's spreadsheet.

### 4.2 The KHDT file

The first worksheet is read. Somewhere in its first 30 rows there must be a header row containing at least these Vietnamese headers (exact wording, spacing, and column order don't matter — they're found by searching, ignoring accents):

- `Mã NV` — employee ID
- `Họ tên` — name
- `Bắt đầu` / `Kết thúc` — start / end date
- `Phòng/đội`, `Tên KĐT`, `Mã lớp học`, `Lí do` are read too if present.

Rows without an employee ID are ignored. If the end date is missing or earlier than the start date, the start date is used. KHDT is **never written to**.

**A known KHDT date quirk is corrected automatically.** KHDT date cells are stored day/month-swapped (`YYYY-DD-MM`). Real Excel date cells are un-swapped; slash text like `10/09/2026` is already normal `DD/MM/YYYY` and read as is; hyphen text follows the file's `YYYY-DD-MM` convention. Anything that still looks implausible for the roster's month (more than a month away) is logged as a `[CHECK]` line rather than silently guessed.

### 4.3 What the matching rules do

This is the same engine for every KHDT run (`engine.mark_roster_grid`).

1. **Match by employee ID.** Each KHDT row is looked up in the squad's roster. If the name also differs (accents/case/spacing ignored) it's logged as a `[WARN]` name mismatch — the ID is trusted and the row is still processed.
2. **Which days to mark.** Every day from `Bắt đầu` to `Kết thúc` inclusive that falls inside the roster's date columns. **Exception:** if the `Lí do` note pins one day — phrased *"Lên lớp sáng/chiều &lt;d/m/yyyy&gt;"* ("attend class in the morning/afternoon of …") — only that day is marked, even if the range is wider (e.g. a week of self-study with one actual class day). A row whose dates don't touch the roster at all is logged as "no date overlap".
3. **The marker text.** `H` + the course label, e.g. `H ATHK`.
   - With a class code (`Mã lớp học`), the last two `/`-separated segments are dropped and the rest is looked up in `COURSE_ABBREVIATIONS`.
   - Without one, the course name is looked up in `COURSE_NAME_ABBREVIATIONS` (accents, case and repeated spaces ignored); if it isn't there, a short label is generated from the name (up to 8 meaningful words, acronym-like words kept, others reduced to initials, max 24 characters); if there's nothing at all, `?`.
   - ` SÁNG` / ` CHIỀU` is appended when the note says which half of the day.
4. **Same-day overlaps are combined.** If two KHDT rows put the same person on the same day (typically a morning class and an afternoon class) they become one marker instead of one overwriting the other, parts joined with `-` and ordered sáng → chiều → others, e.g. `H VHNT SÁNG-VHDN CHIỀU`.
5. **Weekends are always `N`.** Saturdays and Sundays get a black `N` (day off) regardless of the course; course markers are never written on a weekend. Weekday course markers are written in **red**.
6. **What's already in the cell:**

| Cell currently holds | What happens |
|---|---|
| Empty | The marker is written. |
| The same course, or part of a combined marker | Not duplicated; logged "already marked". Different parts are merged into the existing marker. |
| A **black** `N` | Treated as an ordinary day off and replaced by the course (or by `N` again on a weekend). Not a conflict. |
| A **red** `N` (guaranteed day off), or any unrelated text | **Conflict.** By default nothing is overwritten and the intended value is **appended** (`existing-new`) so no information is lost. With **"Overwrite cells that already have content"** ticked, it is replaced instead. |
| (Weekend) a course marker | Replaced by `N`, no conflict. |

Every decision is written to the run log (§4.7).

### 4.4 Step 1 — Run (preview, writes nothing)

Side menu → **KHDT → Roster**, choose the file, optionally tick *Overwrite cells that already have content*, and press **Run**. The browser posts the file to `POST /api/khdt/preview`, which (`khdt_review.preview`):

1. Reads the 1st sheet of each squad **fresh** (not from cache), in parallel.
2. Works out each squad's **own people** — IDs above the reinforcement row. A person in two squads belongs to the first one.
3. Gives each squad only the KHDT rows whose ID is one of its own people, and runs the matching rules above against that squad's own rows.
4. Turns each resulting cell update into a **change**: who, which squad, which date, row/column, what the cell says now (`old`), what it would say (`new`), its colour, and a **kind**:
   - `new` — the cell was empty,
   - `update` — an existing course marker is extended,
   - `dayoff` — a black `N` is replaced,
   - `conflict` — something else (including a red `N`) is in the cell and is replaced or appended to.
   Cells that already hold exactly the proposed value and colour are dropped.
5. **Signs every change** with an HMAC (SHA-256, using `FLASK_SECRET_KEY`) over `squad, id, date, row, col, old, new, newColor`.
6. Returns the changes, per-squad counts, the statistics, the log lines, and the `.xlsx` log (base64).

`no_id_match` in the statistics counts KHDT rows whose ID isn't an own person of *any* squad. "Marked" counts what the engine marked before the "already says exactly this" filter, so it can be slightly higher than the number of proposed changes.

A squad that couldn't be read is reported with a warning and skipped; the others still produce changes.

### 4.5 Step 2 — Review (in your browser only)

The roster page lays the proposed values over the live roster:

- **dashed, flickering green** outline = undecided
- **solid green** = kept
- **dotted grey** = rejected (an empty cell with a rejected proposal shows the value struck through; click to reconsider)
- **amber outline** = it would replace or extend something already in the cell

Click a highlighted box for **Keep / Reject / Undecided** (a multi-day box acts on all its days), or use the **Review list** (filter: undecided / kept / rejected / overwrites existing / out of date; search by name or ID) and the bulk buttons **Keep undecided / Reject undecided**. *Only changed rows* hides everyone else. **Discard** forgets the whole review (nothing was written).

**Your decisions are yours alone.** The proposed changes and your decisions are stored in this browser's `localStorage` (key `roster.khdt.review.v1`), so a reload keeps them, and a second tab of the same browser stays in sync. Other people and other browsers/devices see the plain roster. Nothing about the review is stored on the server. Clearing the site's data or pressing Discard forgets it; if the browser blocks storage, the page warns that decisions will be lost on reload. Running KHDT again replaces the current review (the page asks first).

Each time the roster loads, every stored change is compared with the live sheet:

- cell still holds what the preview saw → **active**;
- cell already shows the proposed value (for example after an export) → the change **leaves the review by itself**;
- cell was edited after the run → **out of date**: ignored and cannot be exported;
- the person isn't on the page (e.g. that squad failed to load) → **not shown**.

### 4.6 Step 3 — Export (writes only what you kept)

**Export N kept → sheets** posts the kept changes to `POST /api/khdt/export` (`khdt_review.export`):

1. **Signature check.** Changes whose signature doesn't verify are refused and counted ("refused — run KHDT again"). So a hand-made request can't put arbitrary text into the roster.
2. **Per squad, re-read the live sheet** and check each change: the row is still inside the squad's own people, the **same employee is on that row**, the **date column hasn't moved**, and the **cell text is still what the preview saw**. Any change failing a check is **skipped and reported** with the reason — never overwritten.
3. **Write** the surviving cells (text and font colour) in batches of 500 into the squad's first sheet. Only those cells are touched; everything else on the sheet is left as it is.
4. Clear the server cache, so the page's reload straight afterwards shows what was written.

Results are shown per squad (written / skipped / error). A squad whose file is an uploaded `.xlsx` (not a native Google Sheet) can be reviewed but **not exported**; a missing Editor share is reported as a permission error for that squad only.

### 4.7 The run log

Every run produces a downloadable `.xlsx` (the dialog's *Download log* button) with three tabs: **Log** (one row per person/date with events, reasons and details, labelled by `LOG_EVENT_LABELS`), **Run summary** (the counts), and **Console log** (the raw messages: `[WARN]`, `[SKIP]`, `[CHECK]`, `[NOTE DATE]`, `[NO OVERLAP]`, `[OVERLAP]`, `[OVERWRITE DAY OFF]`, `[CONFLICT]`, `[GUARANTEE DAY OFF CONFLICT]`, `[ALREADY MARKED]`). The log is generated in memory and sent to the browser; no file is kept on the server, which suits serverless hosting.

---

## 5. Daily Distribution (read-only)

Side menu → **Daily Distribution** (or open `/#distribution`). It reads the same four squad spreadsheets and shows who goes to which zone on a chosen day. It never writes. Squads appear as tabs (a `!` marks one that couldn't be read, with the reason); a strip of day buttons lists that spreadsheet's days; the last squad you looked at is remembered in your browser.

**Everything is found by searching labels, not fixed cell addresses**, so moved columns or extra blank rows don't break it.

### 5.1 Which tabs are days

- **1st sheet** — general info and/or the monthly roster (see below).
- **Day tabs** — named `<A/C>-<MMM><DD>`, e.g. `B218-SEP21`. A zero-padded day is fine (`A326-OCT09`; `A326-OCT011` = 11 Oct). Text before the aircraft is kept as the day's CHECK (`WO COMP A611-OCT07` → A/C `A611`, CHECK `WO COMP`). The year is the one nearest the roster's month (or today).
- **Number-only tabs** (`1`, `14`) are that day of the month the 1st sheet is a roster for. That month is read from the roster's date header row, else from text such as `THÁNG 10.2026` in its top rows or a tab name like `Doi 3 Thang 10`.
- Tabs that don't match are ignored (notes, templates).

### 5.2 What's read from the 1st sheet

By label: `A/C`, `CHECK`, `DATE` (e.g. `21-29 SEP 2026`, or two date cells), `FOREMAN`, `TRỰC ĐỘI` (or `BCH ĐỘI`), `DOCK PLANNER`, `SHIFT / TECH SUPP` — each with a name and phone (next to it or below it; `#N/A` means nobody). Also a **phone book**: any row holding an employee ID and a phone number.

If the 1st sheet is a **monthly roster**, the crew for the selected day is read from that day's column: anyone whose cell holds `TĐ` (Trực đội), `PPC` (Dock planner) or `FM` (Foreman), alone or with a shift/aircraft (`TĐ-SAG`, `TĐ @16:00`, `A326-FM`). Several people can share a role.

### 5.3 What's read from a day tab

Tables with `ORD / NAME AND SURNAME / ID / POSITION / REMARK` columns (any `<word> ID` header works, `PHONE` optional), possibly two side by side. Rows are split into sections by title rows:

- **Zones** — titles like `ZONE 128`, `ZONE 128 @16H00`, or aircraft-zone titles like `A864-128`. `@16H00`-style ones show a sun/moon icon.
- **Other sections** — `STRUCTURE SHEET METAL`, `STRUCTURE COMPOSITE`, `STRUCTURE PAINTING`, `CABIN`… The right-hand column always lists these shops.
- A person row has a valid ID, or a name plus a numeric ORD with no ID yet. A stray note in REMARK/PHONE/POSITION on a row with no person is not a section title. A **red REMARK** stays red on the page.

The day tab may carry its own info block (Squad 1/4: `A/C: A864`, `FOREMAN:`, `BCH ĐỘI`, `TECH SUPPORT`, `DOCK PLANNER:`, each with `PHONE:`).

**Precedence for the crew:** labels on the day tab → `TĐ/PPC/FM` codes in the roster → labels on the 1st sheet. **Aircraft shown:** the one in the tab name → the `A/C:` on the day tab → the 1st sheet's; with none, the page shows just the date. **Phones:** the table's PHONE column, then the phone book.

The page notes any of the fixed zones/shops (128, 567, 34, AVI, and the structure/cabin shops) that have nobody assigned, including when titles combine zones (`128/567`, `34567`, `ALL ZONES`).

### 5.4 Layouts in the wild

- **Squad 1/4:** the 1st sheet is `ROSTER`; day tabs are named `1`, `2`, …; each day tab has its own info block and two side-by-side tables; section titles like `A864-128` count as zones.
- **Other squads:** the 1st sheet is general info (or a roster); day tabs are `B218-SEP21`-style.

---

## 6. How Google data is read

- **One reader for everything.** The Roster page, Daily Distribution and the KHDT preview all use the same code (`distribution.py`) to open each squad's spreadsheet and read its 1st sheet, so they always agree on what the roster looks like.
- **Cache.** Reads are cached in the server's memory for `DISTRIBUTION_CACHE_SECONDS` (60 s). Reload buttons add `?refresh=1` to skip it; the KHDT preview and export always read fresh; an export clears the cache. On serverless hosting each instance has its own cache. The page also reuses a fetched day for 60 s.
- **Parallel and isolated.** Squads are read on up to 8 threads (each with its own client, because the Google client isn't thread-safe). One unreadable squad is reported but doesn't hide the others.
- **Values and colours.** Values are read unformatted, with dates as serial numbers; each cell's font colour is read separately (that's how red vs black `N` and red remarks are told apart).
- **Large responses.** Very large sheets with many formatted-but-empty cells compress extremely well, so the library's compression-ratio check is relaxed (the absolute size limit stays on).

---

## 7. Hosting notes

The app is a Flask app that keeps nothing on disk, so it runs on serverless hosts such as Vercel. Credentials come from environment variables (`GOOGLE_SERVICE_ACCOUNT_JSON`, `FLASK_SECRET_KEY`); the log download is a base64 payload, not a stored file.

---

## 8. The old Main/temp flow (still in the code, not used by the page)

Before the squad-based review, a KHDT run wrote into a single "KHDT sheet" that had a **Main** tab (the live roster) and a **temp** tab. That code is still there:

- `POST /run` — loads the KHDT file, takes **Main** (or the existing **temp** if "keep" is ticked) as the base, rebuilds **temp** as a copy of Main (unless keeping), writes the changes into **temp** only (Main is never touched), and answers JSON for a `fetch` call or the old `result.html` page for a plain form post.
- `GET /api/roster?url=<sheet url>&gid=<tab id>` — reads one Google Sheet tab and, if it has Main and temp tabs, reports which cells differ between them.
- `roster_view.py` holds the helpers for this (listing tabs, rebuilding temp, diffing).

The current page calls neither endpoint. `DEFAULT_ROSTER_SHEET_URL` and `templates/result.html` + `static/style.css` exist only for this flow.

---

## 9. Project files

| File | Purpose |
|---|---|
| `app.py` | Flask routes: `/` (the page), `/api/roster`, `/api/distribution`, `/api/distribution/day`, `/api/khdt/preview`, `/api/khdt/export`, legacy `/run` |
| `engine.py` | KHDT parsing, header detection, and all the matching/marking rules (§4.2–4.3) |
| `khdt_review.py` | KHDT → proposed changes on the squads' sheets (signed), and the checked export |
| `squad_roster.py` | Builds the combined roster for the Roster page from the squads' 1st sheets |
| `distribution.py` | Opens and caches the squads' spreadsheets; parses info blocks and day tabs for Daily Distribution; shared reader for the roster and KHDT |
| `roster_view.py` | Turns a sheet grid into the roster JSON payload; tab helpers for the legacy Main/temp flow |
| `sheets_client.py` | Google auth (service account), Sheets/Drive clients, reading a grid with colours, writing cells |
| `log_workbook.py` | Builds the downloadable `.xlsx` run log |
| `config.py` | Squad spreadsheet URLs/names, role codes, abbreviations, log labels |
| `templates/index.html` | The whole single-page UI (roster, review, distribution; its own CSS and JS) |
| `templates/result.html`, `static/style.css` | Legacy result page for `/run` only |

---

## 10. Things worth knowing

- **Review = proposal, not a draft on the server.** If you clear your browser data mid-review, the proposals are gone (the sheets are unaffected). Re-run KHDT.
- **Concurrent edits are safe, not merged.** If someone edits a cell between your run and your export, that cell is skipped and reported. The check compares the cell's *text*, not its colour.
- **Reinforcement rows aren't matched.** KHDT rows are only matched against each squad's own people (above `NV TĂNG CƯỜNG`), and a person who appears in two squads is handled by the first.
- **A red `N` on a weekend** counts as a conflict; unless *Overwrite* is ticked, `N` is appended to it (it will read `N-N`).
- **Uploaded Excel files** as squad files: readable (needs the Drive API), but not exportable.
- **Changing `FLASK_SECRET_KEY`** invalidates any review in progress: its changes will be refused at export.
- **Everything is by label.** If a squad renames a header (ID/NAME, ORD, REMARK…) or the reinforcement row, add the new wording to the alias lists in `engine.py` / `distribution.py` — the page will say what it couldn't find.
