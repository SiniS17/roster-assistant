# Code structure

Flask app, no database. All data lives in Google Sheets; the server holds only a short in-memory cache. Frontend is one HTML page with inline JavaScript.

## Layout

```
app.py            Flask routes
config.py         Sheet URLs, abbreviations, labels (the one place to edit settings)
engine.py         KHDT parsing, roster header detection, marking logic
sheets_client.py  Google auth, read grid + font colours, batch write
roster_view.py    Roster JSON for one tab; tab listing; temp rebuild; Main-vs-temp diff
squad_roster.py   Roster page data: merge of the 4 squads' 1st sheets
distribution.py   Daily Distribution: sources, parsing, caching
assignments.py    Roster <-> day-tab link, dry run only: layout adapters, cell positions, plans
log_workbook.py   Builds the downloadable .xlsx run log
templates/
  index.html      Single-page UI (roster, distribution, KHDT dialog; JS inline)
  result.html     Legacy plain form-post result page
static/style.css  Legacy page styles
tests/            pytest suites with fake Google sources
CLAUDE.md         Session handover
HOW_IT_WORKS.md   Behaviour rules and sheet formats
```

`package.json` is unrelated boilerplate (pnpm workspace) and is not used by the Python app.

## Routes (`app.py`)

| Route | Purpose |
|---|---|
| `GET /` | The page |
| `GET /api/roster` | Combined squad roster. With `?url=&gid=` it reads one KHDT-sheet tab instead (Main/temp preview) |
| `GET /api/distribution` | Squads, their info blocks, and day-tab lists |
| `GET /api/distribution/day?sheet=<n>&tab=<title>` | One day's zones and people |
| `POST /api/link/dry-run` | Login required. Plans a roster edit or daily move on both sides; writes nothing |
| `POST /run` | KHDT upload; writes to `temp`; JSON for the page's fetch call, HTML for a plain form post |

`?refresh=1` on the GET APIs skips the 60 s cache.

## Data flows

**Roster page**

```
/api/roster -> squad_roster.build_squads_roster
  per squad (threaded): distribution source -> 1st sheet grid
    -> roster_view.build_roster_payload (engine.find_roster_header_grid, lenient)
    -> cut at "NV TĂNG CƯỜNG", keep rows with a valid ID
  merge: union of dates, dedupe by ID, report unreadable squads
```

**Daily Distribution**

```
/api/distribution      -> distribution.build_meta     (info block + day tab list per squad)
/api/distribution/day  -> distribution.build_day      (parse_day + roster_crew)
Sources: SheetsSource (Sheets API) or XlsxSource (Drive download for uploaded .xlsx)
```

Parsing is label-based, not fixed-cell. Crew precedence per role: labels on the day tab, then `TĐ`/`PPC`/`FM` codes in the roster, then labels on the 1st sheet.

**KHDT run (`POST /run`)**

```
engine.load_khdt -> read Main (or temp if "keep") -> engine.mark_roster_grid
  -> roster_view.rebuild_temp (unless "keep") -> sheets_client.write_roster_updates (temp only)
  -> log_workbook.write_log_workbook -> JSON with stats, log, base64 .xlsx
```

## Key modules

**`engine.py`**
- `load_khdt`, `find_khdt_header`: read the plan; header found by label in the first 30 rows.
- `parse_khdt_date`: un-swaps `YYYY-DD-MM` Excel dates.
- `find_roster_header_grid(values, lenient, default_month)`: finds the ID/NAME header by alias (`ID_HEADER_ALIASES`, `NAME_HEADER_ALIASES`), accent- and case-insensitive. Day columns are real dates or bare numbers placed in `default_month` (default: current month). Lenient mode guesses the name column left of ID.
- `build_marker`, `combine_markers`, `mark_roster_grid`: marker text, same-day overlaps, black/red `N` rules, conflict handling.

**`sheets_client.py`**
- `_build` / `_http`: Google clients with a relaxed httplib2 decode limit (`DECODE_LIMIT_RATIO = 0`, hard cap 512 MB), needed for large sheets of formatted empty cells.
- `read_roster_grid`: values plus font colours. `write_roster_updates`: batch cell writes.
- Credentials: `GOOGLE_SERVICE_ACCOUNT_JSON` or `GOOGLE_APPLICATION_CREDENTIALS`. Reads use read-only scopes.

**`distribution.py`**
- `parse_tab_name`: day-tab names (`B218-SEP21`, `A326-OCT011`, `WO COMP A611-OCT07`, bare numbers).
- `parse_info`: info block (A/C, foreman, trực đội, dock planner, tech support, phones).
- `parse_day`: finds header rows (any `<word> ID`), splits sections by zone titles (`ZONE_TITLE_RE`), handles side-by-side tables.
- `roster_crew`: crew from roster codes. `_cached`: 60 s in-memory cache.

**`roster_view.py`**: `build_roster_payload`, `list_tabs`, `find_tab`, `rebuild_temp`, `diff_main_temp`. The last three serve the KHDT temp preview only.

## Conventions

- Settings and URLs go in `config.py` only.
- Vietnamese text is matched accent- and case-insensitively (`strip_accents`, `fold`).
- Read paths are view-only. Only `POST /run` writes, and only to `temp`.
- One bad squad must not break the rest: errors are collected and reported per squad.

## Tests

`pytest tests`

- `test_distribution.py`: day-tab layouts for squads 1/4 and 2/3, numeric tabs.
- `test_squad_roster.py`: merging, duplicates, reinforcement cutoff, unreadable squad, `/api/roster`.
- `test_header_detection.py`: header aliases, day-number columns, httplib2 limit (needs httplib2 >= 0.32).

## Known gaps

- Parsers are tested on grids copied from screenshots and header rows, not yet verified against the live sheets.
- The KHDT `temp` tab still lives on the old sheet; where it should live now that the roster page reads the squad sheets is undecided.
- `requirements.txt` has duplicate entries and does not pin `httplib2`. `HOW_IT_WORKS.md` mentions a `.env.example` that is not in the repo.
