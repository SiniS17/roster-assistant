# CLAUDE.md — roster-assistant

Flask website for VAECO: KHDT (training plan, .xlsx) -> Roster (Google Sheet), plus a
Daily Distribution page. Full behaviour of the KHDT flow is in `HOW_IT_WORKS.md`.

## Layout
- `app.py` — Flask routes (`/`, `/api/roster`, `/api/distribution`, `/api/distribution/day`, `POST /run`)
- `engine.py` — KHDT loading, roster header detection (`find_roster_header_grid`), `parse_sheet_date`, marking logic
- `distribution.py` — Daily Distribution: reads the squad spreadsheets (view-only), parses day tabs and crew
- `config.py` — squad sheet URLs/names, role markers (TĐ / ppc / fm), course abbreviations, log labels
- `roster_view.py`, `sheets_client.py`, `log_workbook.py` — roster payload/diff, Google API clients, Excel log
- `templates/`, `static/style.css` — UI

## Conventions
- Labels and headers are found by searching (accent-folded via `fold()`), never by fixed cell addresses.
- Sheets are read with `UNFORMATTED_VALUE` + `SERIAL_NUMBER`, so date cells arrive as serial numbers.
- Squad sheets: 1st tab is general info / monthly roster; other tabs are day tabs
  (`B218-SEP21`, or just `1`..`31`).
- Numbered tabs (`1`..`31`) take their month from the 1st sheet's roster date header row
  (`roster_header_month`), falling back to "THÁNG N" text. Tab names can be stale (e.g. "SEP" while columns are October).

## Task log
- Fixed Squad 1 Daily Distribution showing no days: numbered tabs had no month because
  `roster_month()` only searched text. It now reads the header dates first (`distribution.py`).
  Known leftover: `find_roster_header_grid` treats a plain `1` cell as a 1899 date (affects `engine.py` expected-year only).
- Daily Distribution page (`templates/index.html`, `paintDay`): zones and shops with people are listed first,
  empty ones (UNASSIGNED / "No personnel assigned") sink to the bottom. Stable sort, so the default order
  (sheet order for zones, `SHOPS` order for shops) is kept within each group.
