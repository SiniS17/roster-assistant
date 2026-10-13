# CLAUDE.md — roster-assistant handover

Repo: https://github.com/SiniS17/roster-assistant.git (internal VAECO tool, Flask + Google Sheets)
Last updated: 2026-10-13 (session 2: Squad 1/4 daily-distribution support, tests added)

## Working agreement
- Owner wants a CLAUDE.md (or equivalent handover) updated after every task.
- Related URLs (Roster sheet, Daily Distribution sheets) live in `config.py`. Don't hardcode them elsewhere.

## What it does
1. **KHDT → Roster**: upload the training-plan `.xlsx` (KHDT); matched by Employee ID against the Roster Google Sheet; course markers (e.g. `H ATHK`) are written to a `temp` tab, never straight to `Main`.
2. **Roster page** (`/`): shows Main/temp tabs, highlights cells that differ in temp.
3. **Daily Distribution** (`/#distribution`): read-only view of other teams' spreadsheets (who is in which zone per day).

Full plain-language behaviour (marker rules, N/red-N handling, date-swap bug): `HOW_IT_WORKS.md`.

## File map
| File | Role |
|---|---|
| `app.py` | Flask routes: `/`, `/api/roster`, `/api/distribution`, `/api/distribution/day`, `POST /run` |
| `engine.py` | KHDT parsing + roster marking (`load_khdt`, `mark_roster_grid`, markers, date parsing) |
| `sheets_client.py` | Service-account auth, read grid + font colours, batch write cells |
| `roster_view.py` | Roster JSON payload, tab listing, `rebuild_temp`, Main-vs-temp diff |
| `distribution.py` | Reads distribution sheets (Sheets API, Drive fallback for uploaded .xlsx), parses info + day tabs, 60 s cache |
| `log_workbook.py` | Builds the downloadable `.xlsx` run log |
| `config.py` | Sheet URLs, course abbreviations, log labels, `MARKER_PREFIX` |
| `templates/index.html` | Single-page UI (roster, distribution, KHDT dialog; all JS inline, ~640 lines) |
| `templates/result.html`, `static/style.css` | Legacy plain form-post result page |
| `tests/test_distribution.py` | Distribution parser tests (squad 1/4 and 2/3 layouts; fake Google source, no network) |

## Key behaviours to remember
- KHDT dates are `YYYY-DD-MM` (day/month swapped); `parse_khdt_date` un-swaps real Excel dates. Slash text is read as normal DD/MM/YYYY.
- A `Lí do` note like "Lên lớp sáng/chiều <date>" pins marking to that single day.
- Weekends always get `N` (black); weekday markers are red. Black `N` is overwritten; red `N` or other content is a conflict, so the new value is appended unless "force" is ticked.
- Run flow: `Main` is the source; `temp` is rebuilt as a copy of `Main` (or reused if "keep" is ticked), then updates are written to `temp` only.
- Distribution parsing is label-based (not fixed cells). Day-tab names: `B218-SEP21`, zero-padded days allowed (`A326-OCT011` = Oct 11), `WO COMP A611-OCT07` (text before the aircraft = CHECK), or just a number (`1`..`31`) = that day of the roster's month.
- Squad names/roles come from `config.py`: `DISTRIBUTION_SHEET_NAMES` (by position: 1st URL = Squad 1 ... last = Squad 4) and `DISTRIBUTION_ROLE_MARKERS` (Trực đội=`TĐ`, Dock planner=`ppc`, Foreman=`fm`).
- Crew header precedence per role: labels on the day tab > `TĐ`/`PPC`/`FM` codes in the roster's column for that day > labels on the 1st sheet.
- Reload really reloads: `/api/distribution/day?refresh=1` skips the 60 s cache; the page keeps a day for 60 s only.
- Course label comes from `COURSE_ABBREVIATIONS` (class-code prefix) or `COURSE_NAME_ABBREVIATIONS` (full name); otherwise auto-abbreviated, `?` if nothing found.

## Setup / run
- Credentials via env: `GOOGLE_SERVICE_ACCOUNT_JSON` (one-line JSON) or `GOOGLE_APPLICATION_CREDENTIALS` (path). Also `FLASK_SECRET_KEY`. `.env` is gitignored.
- Sheets must be shared with the service account (Editor for the Roster, Viewer for distribution sheets). Drive API only needed if a distribution file is an uploaded .xlsx.
- `pip install -r requirements.txt && python app.py` → http://localhost:5000
- Hosting hint in docs: Vercel (`GOOGLE_SERVICE_ACCOUNT_JSON` env var).

## Observations from review (not yet acted on)
- `HOW_IT_WORKS.md` mentions copying `.env.example`, but no such file is in the repo.
- `requirements.txt` lists the same packages twice (duplicates, harmless).
- `package.json` looks unrelated to this Python app (pnpm workspace boilerplate).
- Sheet URLs are committed in `config.py` (fine if the repo is private).
- No tests in the repo.

## Sheet formats (Daily Distribution)
- **Squad 2/3**: day tabs named `B218-SEP21`; one table per section, headers `ORD / NAME AND SURNAME / ID / POSITION / REMARK`, sections titled `ZONE 128`, `ZONE AVI`, `STRUCTURE PAINTING`...
- **Squad 1/4** (seen in a real A864 screenshot): 1st sheet is `ROSTER`; day tabs are just `1`, `2` ... `20`. Each day tab has an info block (A/C, FOREMAN, CRS C, BCH ĐỘI, TECH SUPPORT, DOCK PLANNER, with PHONE next to each), then in row 6 two tables side by side (left A-F, a divider in G, right H-M), each with `ORD / NAME AND SURNAME / VAECO ID / POSITION / PHONE / REMARK`. Zone titles sit in the row below the header and look like `A864-128`, `A864-34`, `A864-567`, `A864-AVI`. Stray notes can sit in REMARK on rows with no person. A row may have an ID but no name yet.

## Tests
`python tests/test_distribution.py` (or `pytest tests`): covers the squad 1/4 layout, the squad 2/3 layout, and numeric tabs.

## Status / next steps
- History: an earlier squad 1/4 attempt (commit `cd3d29b`) was reverted (`d626c31`) and its `tests/` folder never reached the repo. The old status text claiming it was done was wrong; it is replaced by the notes below.
- Session 2 DONE (in `distribution.py` + `templates/index.html`; tested only on grids copied from screenshots, **not yet verified against the live sheets**):
  - Squad 1/4 day tabs: any `<word> ID` header (`VAECO ID`) is an ID column; titles like `A864-128` count as zones (`ZONE_TITLE_RE`); a stray note in REMARK/PHONE/POSITION no longer creates a bogus section; labels may end in a colon (`FOREMAN:`); `BCH ĐỘI` = Trực đội; `#N/A` = nobody.
  - Number-only tabs (`1`..`31`) = that day of the roster's month, read from the roster's date header (`roster_header_month`) or 'THÁNG 10.2026' text; if neither exists it assumes the current month and shows a warning. A/C is shown only when the tab name or the day tab has one; otherwise just the date.
  - Squad 3: tabs like `A326-OCT010`/`OCT011` (3-digit zero-padded days) were skipped, so the list stopped at Oct 9; fixed. A/C is now per day (was one A/C for the whole file, wrongly A611 for A326 days).
  - Info block on each day tab (A/C, FOREMAN, BCH ĐỘI, TECH SUPPORT, DOCK PLANNER + phones) is now read; `TĐ`/`PPC`/`FM` codes in the roster fill the crew when the day tab has no label.
  - Reload refetches the day tab (was served from a 60 s server cache + a page-lifetime browser cache).
  - `tests/test_distribution.py`: `python tests/test_distribution.py`.
- Open questions / ideas: if Squad 1's roster header dates are text (hyperlink formulas) instead of real dates, the month falls back to the current month (warning shown) and roster-code crew isn't read - day-tab labels still work. Nothing writes TĐ/ppc/fm into the main roster; they are only read from it.
- Update this section after each task (owner's standing instruction).
