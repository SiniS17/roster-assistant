# CLAUDE.md — roster-assistant handover

Repo: https://github.com/SiniS17/roster-assistant.git (internal VAECO tool, Flask + Google Sheets)
Last updated: 2026-10-12 (session 1: read-only review, no code changed)

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
| `tests/test_distribution.py` | Distribution parser tests (squad 1/4 and 2/3 layouts) |

## Key behaviours to remember
- KHDT dates are `YYYY-DD-MM` (day/month swapped); `parse_khdt_date` un-swaps real Excel dates. Slash text is read as normal DD/MM/YYYY.
- A `Lí do` note like "Lên lớp sáng/chiều <date>" pins marking to that single day.
- Weekends always get `N` (black); weekday markers are red. Black `N` is overwritten; red `N` or other content is a conflict, so the new value is appended unless "force" is ticked.
- Run flow: `Main` is the source; `temp` is rebuilt as a copy of `Main` (or reused if "keep" is ticked), then updates are written to `temp` only.
- Distribution parsing is label-based (not fixed cells); tab names must look like `B218-SEP21`.
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
- Session 1 task 1 DONE (in `distribution.py`, not yet deployed/verified against the live sheets): fixed Daily Distribution for squad 1/4. Original error: `Couldn't find a header row with ID and NAME columns` because the header is `VAECO ID`.
  - ID header now matches `VAECO ID` (and any `<word> ID`).
  - Stray text in REMARK/PHONE/POSITION columns no longer creates a bogus empty section.
  - Titles like `A864-128` count as zones (`ACZONE_RE`), so they show in the zone column.
  - Numeric day tabs (`1`..`31`) are accepted via `numeric_tab_dates()`: dates are assigned in tab order, month = month of the sheet's date (or today if none found), moving to the next month when the number drops (30 -> 1). Check this against the real sheets.
  - Tests added in `tests/test_distribution.py`. They pass on a grid copied from the screenshot, not on the live sheets.
- Not done / ideas: the info block (foreman, BCH đội, tech support, dock planner, phones) on squad 1/4 day tabs is not read yet (the page reads these from the 1st sheet only, which is `ROSTER` for squad 1/4). A/C falls back to the spreadsheet title for numeric tabs.
- Update this section after each task.
