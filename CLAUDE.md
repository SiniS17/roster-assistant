# CLAUDE.md — roster-assistant handover

Repo: https://github.com/SiniS17/roster-assistant.git (internal VAECO tool, Flask + Google Sheets)
Last updated: 2026-10-29 (session 8: roster <-> daily link, dry-run only, Phase 3 of the Login and Linked Editing Plan; branch feature/edit)

## Working agreement
- Owner wants a CLAUDE.md (or equivalent handover) updated after every task.
- Related URLs (Roster sheet, Daily Distribution sheets) live in `config.py`. Don't hardcode them elsewhere.

## What it does
1. **KHDT → Roster** (side menu): upload the training-plan `.xlsx` (KHDT); it is matched by Employee ID against the **1st sheet of each squad's spreadsheet** (the sheets the roster page shows). Nothing is written. The proposed cell changes (course markers like `H ATHK`, weekend `N`) are highlighted on the roster; the user keeps/rejects each one; decisions persist **per browser** (localStorage) so other users/devices are unaffected; **Export** writes the kept cells into the 4 real sheets (`khdt_review.py`).
2. **Roster page** (`/`): the main roster, built from the **1st sheet of each squad's spreadsheet** (`squad_roster.py`), one table with a squad (Đội) filter. It no longer reads the KHDT sheet's Main tab. The old Main/temp view (`/api/roster?url=&gid=`) and `POST /run` still exist in the backend but the page no longer uses them.
3. **Daily Distribution** (`/#distribution`): read-only view of other teams' spreadsheets (who is in which zone per day).

Full plain-language behaviour (marker rules, N/red-N handling, date-swap bug): `HOW_IT_WORKS.md`.

## File map
| File | Role |
|---|---|
| `auth.py` | Login (`/api/login`, `/api/logout`, `/api/me`), `@login_required`, `can_edit` (role seam); accounts from `Database/users.xlsx` |
| `assignments.py` | Roster <-> Daily Distribution link, **dry run only** (Phase 3): per-squad layout adapters, `locate_day` (cell positions on a day tab), `plan_link` / `plan_batch` / `dry_run` -> the exact cells both sides WOULD write; `POST /api/link/dry-run` (login required); `tools/link_dry_run.py` prints a plan from the command line |
| `roster_edit.py` | Hand edits of roster cells: re-reads the squad sheets fresh, checks every staged edit (same employee on the row, date column present, cell text unchanged, not locked, allowed value), then writes black cells; `POST /api/roster/save` (login required) |
| `app.py` | Flask routes: `/`, `/api/roster`, `POST /api/roster/save`, `POST /api/khdt/preview`, `POST /api/khdt/export`, `/api/distribution`, `/api/distribution/day`, old `POST /run` |
| `khdt_review.py` | KHDT -> proposed changes on the squads' 1st sheets (signed, nothing written) and the checked export into the real sheets |
| `engine.py` | KHDT parsing + roster marking (`load_khdt`, `mark_roster_grid`, markers, date parsing) |
| `sheets_client.py` | Service-account auth, read grid + font colours, batch write cells |
| `roster_view.py` | Roster JSON payload for one sheet, tab listing, `rebuild_temp`, Main-vs-temp diff (the latter three serve the KHDT temp preview) |
| `squad_roster.py` | Roster page data: merges the squads' 1st sheets (IDs only, stops at `NV TĂNG CƯỜNG`, dedupes by ID, reports unreadable squads) |
| `distribution.py` | Reads distribution sheets (Sheets API, Drive fallback for uploaded .xlsx), parses info + day tabs, 60 s cache |
| `log_workbook.py` | Builds the downloadable `.xlsx` run log |
| `config.py` | Sheet URLs, course abbreviations, log labels, `MARKER_PREFIX` |
| `templates/index.html` | Single-page UI (roster + KHDT review bar/popover/list/export dialogs, distribution, KHDT dialog; all JS inline, ~900 lines) |
| `templates/result.html`, `static/style.css` | Legacy plain form-post result page |
| `tests/test_khdt_review.py` | KHDT preview/export: per-squad partition, signing, stale-cell skipping, routes; `tests/browser_smoke.py` is an optional Playwright run of the whole review flow (not collected by pytest) |
| `tests/test_distribution.py`, `tests/test_squad_roster.py`, `tests/test_header_detection.py` | Parser tests (squad 1/4 and 2/3 layouts), the combined-roster tests and roster-header / HTTP-limit tests; fake Google source, no network |

## Key behaviours to remember
- **KHDT review flow** (`khdt_review.py` + `templates/index.html`):
  - `preview()` re-reads the 4 squad sheets (force, no cache), runs `engine.mark_roster_grid(..., lenient=True)` per squad on the squad's own rows only (above `NV TĂNG CƯỜNG`), KHDT rows are partitioned by owner (an ID in two squads belongs to the first, same as the roster page), IDs found in no squad count as `no_id_match`. Returns one change per cell: `squad, id, name, date, row, col, old, new, newColor, kind` (`new` empty cell, `update` marker extended, `dayoff` black N replaced, `conflict` existing content/red N replaced or appended) + `sig`.
  - `sig` = HMAC-SHA256 (first 32 hex) of `squad,id,date,row,col,old,new,newColor` with `app.secret_key` (`FLASK_SECRET_KEY`). `export()` only writes changes with a valid sig, so a forged request can't write arbitrary text. Set a real `FLASK_SECRET_KEY` in production (the dev default is public).
  - `export()` re-reads each squad fresh and skips (and reports) a change when the row no longer holds that employee ID, the date column moved, or the cell text differs from `old`. Writes go through `sheets_client.write_roster_updates` (write scope) to the squad's 1st tab; squads backed by an uploaded `.xlsx` (XlsxSource) can't be exported. Caches are dropped afterwards.
  - Client state: `localStorage['roster.khdt.review.v1']` = `{file, at, changes:{'ID|YYYY-MM-DD': {...change, status:'pending'|'kept'|'rejected'}}}`. `reconcile()` after every roster load: live == `old` -> `ok` (overlaid), live == `new` -> dropped (already applied, e.g. after export), anything else -> `stale` (ignored, not exportable); employee/date not on the page -> `missing` (kept in storage, e.g. a squad failed to load). Statuses never touch the server.
  - A new KHDT run **replaces** the whole review (the page confirms first): changes are computed against the live sheets, not against earlier kept-but-unexported changes.
- KHDT dates are `YYYY-DD-MM` (day/month swapped); `parse_khdt_date` un-swaps real Excel dates. Slash text is read as normal DD/MM/YYYY.
- A `Lí do` note like "Lên lớp sáng/chiều <date>" pins marking to that single day.
- Weekends always get `N` (black); weekday markers are red. Black `N` is overwritten; red `N` or other content is a conflict, so the new value is appended unless "force" is ticked.
- Old `/run` flow (the page no longer uses it): `Main` is the source; `temp` is rebuilt as a copy of `Main` (or reused if "keep" is ticked), then updates are written to `temp` only.
- Distribution parsing is label-based (not fixed cells). Day-tab names: `B218-SEP21`, zero-padded days allowed (`A326-OCT011` = Oct 11), `WO COMP A611-OCT07` (text before the aircraft = CHECK), or just a number (`1`..`31`) = that day of the roster's month.
- Squad names/roles come from `config.py`: `DISTRIBUTION_SHEET_NAMES` (by position: 1st URL = Squad 1 ... last = Squad 4) and `DISTRIBUTION_ROLE_MARKERS` (Trực đội=`TĐ`, Dock planner=`ppc`, Foreman=`fm`).
- Crew header precedence per role: labels on the day tab > `TĐ`/`PPC`/`FM` codes in the roster's column for that day > labels on the 1st sheet.
- Roster page reads only the squads' 1st sheets (view-only scope). `find_roster_header_grid(values, lenient=True)` falls back to "name = column left of ID" when the NAME header is unreadable (Squad 1's is under the logo). `DEFAULT_ROSTER_SHEET_URL` is now used by the KHDT upload only.
- Roster header detection (`engine.find_roster_header_grid`): ID/NAME columns are matched by alias, accent- and case-insensitive (`ID_HEADER_ALIASES` / `NAME_HEADER_ALIASES`: `ID`, `MÃ VAECO`, `VAECO ID`, `HỌ VÀ TÊN`, `NAME AND SURNAME` ...). Day columns are real dates, or bare day numbers `01`..`31` placed in `default_month` (default: the current month, so check the month if a squad's header has no real dates). If lenient and the NAME header is unreadable, the nearest text column left of ID is used (skips blank spacer columns).
- Google clients are built in `sheets_client._build` with a relaxed httplib2 decode limit. httplib2 >= 0.32 rejects gzip responses that expand > 100x (`DecodeRatioError: Amplification ratio 232.8 ...`); a big sheet full of formatted empty cells (Squad 2: 63 KB -> 14.7 MB) is legitimately that compressible. Ratio check is off (`DECODE_LIMIT_RATIO = 0`), hard cap 512 MB stays.
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

## Sheet formats (Daily Distribution)
- **Squad 2/3**: day tabs named `B218-SEP21`; one table per section, headers `ORD / NAME AND SURNAME / ID / POSITION / REMARK`, sections titled `ZONE 128`, `ZONE AVI`, `STRUCTURE PAINTING`...
- **Squad 1/4** (seen in a real A864 screenshot): 1st sheet is `ROSTER`; day tabs are just `1`, `2` ... `20`. Each day tab has an info block (A/C, FOREMAN, CRS C, BCH ĐỘI, TECH SUPPORT, DOCK PLANNER, with PHONE next to each), then in row 6 two tables side by side (left A-F, a divider in G, right H-M), each with `ORD / NAME AND SURNAME / VAECO ID / POSITION / PHONE / REMARK`. Zone titles sit in the row below the header and look like `A864-128`, `A864-34`, `A864-567`, `A864-AVI`. Stray notes can sit in REMARK on rows with no person. A row may have an ID but no name yet.

## Tests
`python tests/test_distribution.py`, `python tests/test_squad_roster.py`, `python tests/test_khdt_review.py` (or `pytest tests`; 23 tests pass). `python tests/browser_smoke.py` needs `pip install playwright && playwright install chromium`. Covers: squad 1/4 and 2/3 day-tab layouts, numeric tabs, and the combined roster (union of dates, duplicates, reinforcement block, unreadable squad, `/api/roster`).

## Status / next steps
- History: an earlier squad 1/4 attempt (commit `cd3d29b`) was reverted (`d626c31`) and its `tests/` folder never reached the repo. The old status text claiming it was done was wrong; it is replaced by the notes below.
- Session 2 DONE (in `distribution.py` + `templates/index.html`; tested only on grids copied from screenshots, **not yet verified against the live sheets**):
  - Squad 1/4 day tabs: any `<word> ID` header (`VAECO ID`) is an ID column; titles like `A864-128` count as zones (`ZONE_TITLE_RE`); a stray note in REMARK/PHONE/POSITION no longer creates a bogus section; labels may end in a colon (`FOREMAN:`); `BCH ĐỘI` = Trực đội; `#N/A` = nobody.
  - Number-only tabs (`1`..`31`) = that day of the roster's month, read from the roster's date header (`roster_header_month`) or 'THÁNG 10.2026' text; if neither exists it assumes the current month and shows a warning. A/C is shown only when the tab name or the day tab has one; otherwise just the date.
  - Squad 3: tabs like `A326-OCT010`/`OCT011` (3-digit zero-padded days) were skipped, so the list stopped at Oct 9; fixed. A/C is now per day (was one A/C for the whole file, wrongly A611 for A326 days).
  - Info block on each day tab (A/C, FOREMAN, BCH ĐỘI, TECH SUPPORT, DOCK PLANNER + phones) is now read; `TĐ`/`PPC`/`FM` codes in the roster fill the crew when the day tab has no label.
  - Reload refetches the day tab (was served from a 60 s server cache + a page-lifetime browser cache).
  - `tests/test_distribution.py`: `python tests/test_distribution.py`.
- Session 3 DONE (tested on mock squads and in a headless browser, **not yet verified against the live sheets**): roster page built from the 4 squads' 1st sheets instead of the KHDT sheet (`squad_roster.py`, `/api/roster` default path). KHDT→Roster is unchanged and still writes to the old sheet's `temp` tab; its preview is the old `/api/roster?url=&gid=` path with a "Back to the squads' roster" button.
  - Known limits: if squads cover different months the table shows the union of dates (blanks where a squad has none); an employee in two squads shows once, in the first; the KHDT temp workaround is still to do (decide where `temp` lives now that Main is gone from the page, e.g. a tab in each squad's sheet needs Editor access).
- Session 4 DONE (tests pass on mock grids copied from the live sheets' header rows; **not yet run against the live sheets with credentials**): fixed the 3 unreadable squads from the roster page.
  - Squad 1 and 4: `Could not find the Roster header row` - their header is `STT | HỌ VÀ TÊN | MÃ VAECO` + day numbers, not `ID`/`NAME`. Fixed by header aliases + day-number columns (see Key behaviours).
  - Squad 2: `DecodeRatioError` came from httplib2's new gzip ratio guard, not from the sheet. Fixed in `sheets_client.py`.
  - Branch note: CLAUDE.md in this clone already had the session 1-3 notes; no conflicting updates found.
  - Patch applied on top of `f0fa418` (feature/daily-distribution) with `git am`, clean. All 21 tests pass with httplib2 0.32; `test_http_client_allows_highly_compressed_sheets` needs httplib2 >= 0.32 (`httplib2.decode`) and fails on older versions - requirements.txt doesn't pin it.
  - To check live: Squad 1/4 months (if the header has no real dates the current month is assumed), and that Squad 2 loads. TECH + QC rows in Squad 1 have no VAECO ID, so they are skipped by the ID filter (as before).
- Open questions / ideas (older): if Squad 1's roster header dates are text (hyperlink formulas) instead of real dates, the month falls back to the current month (warning shown) and roster-code crew isn't read - day-tab labels still work. Nothing writes TĐ/ppc/fm into the main roster; they are only read from it.
- Session 5 DONE (backend + unit tests + a headless-Chromium run on mock squads; **not yet run against the live sheets with credentials**): KHDT review + export, branch `feature/daily-distribution`.
  - Run KHDT -> highlighted cells on the roster -> keep/reject (click a box, or the Review list, or Keep/Reject undecided) -> reload keeps the decisions in this browser only -> Export writes the kept cells to the 4 squad sheets. See "KHDT review flow" under Key behaviours.
  - `engine.mark_roster_grid` got a `lenient` flag (same header reading as the roster page, so dates line up); `squad_roster.own_rows_cutoff` was extracted from `_squad_roster`.
  - The page no longer has the KHDT-sheet URL / "keep" options, the temp tab preview or its "Back to the squads' roster" button (the KHDT temp workaround from session 3 is resolved by this flow). `/run` + `/api/roster?url=&gid=` remain in the backend, unused.
  - To check live: the squad sheets must be shared with the service account as **Editor** for export (Viewer still reads); Squad 1/4 headers with bare day numbers assume the current month (as the page does); test Export on a copy first.
  - Not done / ideas: re-running KHDT replaces the review instead of stacking on kept changes; per-cell decisions are not merged across a multi-file month (export first, then run the next file); no "undo export" (the sheet's own version history is the way back); the review list caps at 1500 rows.
- Update this section after each task (owner's standing instruction).

## Session 6: login, Phase 1 of "Login and Linked Editing Plan" (2026-10-29, branch `feature/edit`)
- New `auth.py`: accounts come from `Database/users.xlsx`, re-read when its mtime/size changes. People log in with their **employee ID** + password; the file already in the repo has columns `Name | ID | Password` (165 people; `Name` is shown after login). A plain `username | password` file also works (`tools/make_users.py` creates that one). IDs are case-insensitive, passwords case-sensitive, numeric Excel passwords work.
- `@auth.login_required` (401 JSON "Please log in first.") on `POST /api/khdt/export` and `POST /run`. `POST /api/khdt/preview` and every GET stay open. `can_edit(user, squad)` returns True for any logged-in user: the seam for roles. An account removed from the file is logged out on its next request. 5 wrong passwords per (address, ID) in 5 min -> 429 (in memory, per instance).
- `app.py`: blueprint + session cookie config (HttpOnly, SameSite=Lax, 12 h; `FLASK_COOKIE_SECURE=1` on https). `static/auth.js` adds the Log in / Log out button and dialog; `templates/index.html` loads it (one `<script>` line).
- Tests: `tests/test_auth.py` (12), `test_khdt_review.py` export-route test now logs in first, `browser_smoke.py` logs in through the context (smoke not re-run: Playwright not installed here). `pytest tests`: 35 pass.
- Decision (owner): `Database/users.xlsx` stays tracked in git with its plain-text passwords; security is not a concern for this test phase and the login will be replaced later (hashed passwords + roles in Postgres, Step 8 of `docs/plan_for_sql.md`). Not done on purpose: hashing, roles, CSRF tokens (SameSite=Lax + JSON bodies), password change, Edit-mode toggle (Phase 2). Set a real `FLASK_SECRET_KEY` in production.
- Next: Phase 2 (roster edit: staged edits, batch save, locks, stale checks, behind `can_edit`).

## Session 7: roster editing, Phase 2 of "Login and Linked Editing Plan" (2026-10-29, branch `feature/edit`)
- **Page** (`templates/index.html`): an **Edit mode** button appears next to reload only for a logged-in user (`AUTH.canEdit`, from `static/auth.js`). In edit mode every cell is its own box (no merged spans). Click a cell, or drag across the days of ONE person, release -> small editor: type an aircraft code (suggestions from codes already in use), **Normal N** (black), **Clear**. Edits are *staged* in the page (`S.staged`, blue outline, lost on reload; a `beforeunload` warning protects them), and the edit bar shows `Save N to sheets` / `Discard staged` / `Exit edit mode`. Locked cells (cursor not-allowed, no editor): an `H ...` course marker, a red `N`, or a cell with a KHDT change waiting for keep/reject. After each load `reconcileStaged()` drops staged edits the sheet already shows and marks edits whose cell changed meanwhile as out of date (not saved).
- **Server** (`roster_edit.py`, `POST /api/roster/save`, `@login_required`): body `{edits:[{squad (index), id, name, date, old, kind: code|n|clear, value}]}`. Per squad: fresh read, then each edit is skipped and reported (never forced) when the employee is no longer on the squad's own rows, the date column isn't on the sheet, the cell text != `old`, the cell is locked (course marker / red N), the value isn't allowed (empty, > 40 chars, bare `N` typed as a code, `H ...`), or nothing would change. Written cells are always black; the editor cannot produce a red N or an `H ...` marker. `auth.can_edit(user, squad_index)` is checked per squad (seam for roles). At most 3000 edits per save; the last edit of one cell wins; caches are dropped after a save. The client sends only the squad index, id, date and old text: the server finds row/column itself.
- Tests: `tests/test_roster_edit.py` (10 tests; with the rest `pytest tests` = 45 pass). The page was exercised in jsdom with the mock squads (login gating, locked cells, drag over 2 days, staging, no-op edits, save payload, result dialog, logout): **not in a real browser** (Chromium can't be downloaded in this environment), and not against the live sheets.
- Dismissed on purpose: touch/mobile selection (mouse only), keyboard selection, editing `TĐ`/`PPC`/`FM` role codes (phase 1 leaves them out because day-tab labels override roster codes), persisting staged edits across reloads, merging into the KHDT review, undo (the sheet's version history is the way back), audit table (comes with Postgres, `roster_audit`).
- To check live: Editor share for the service account on each squad sheet; try Save on a copy first; the Squad name shown in the table (first info column) must equal the configured squad name, because the page maps it to the squad index.
- Next: Phase 3 (link between roster and daily distribution, dry-run only, per-squad layout adapters).

## Session 8: roster <-> daily link, dry run only, Phase 3 of "Login and Linked Editing Plan" (2026-10-29, branch `feature/edit`)

- **Nothing in this phase writes to Google.** `assignments.py` has no writer; every test patches the writers to raise. It reads the squad's roster and day tabs fresh and returns plans: `{status: ok|roster_only|noop|blocked, blocked, roster:[writes], day:[writes], notes}`, a write being `{sheet, tab, row, col, a1, old, new}`. `POST /api/link/dry-run` (`{intents:[...]}`, login required, `auth.can_edit` per squad) and `python tools/link_dry_run.py --squad 1 --id VAE... --date 2026-10-06 --code A864-34` (needs credentials) show it. No page change.
- **Two intents.** `origin:"roster"` = the same edit as `roster_edit.save` (`kind code|n|clear`, optional `old`); the day tab follows. `origin:"daily"` = `{tab, to: <section title>|"UNASSIGNED"|null}`; the roster follows.
- **Layout adapters** (`config.DISTRIBUTION_SQUAD_LAYOUTS`, by position: `zone, aircraft, aircraft, zone`): `zone` (Squads 1/4) roster `A864-34` <-> section titled `A864-34` on the numbered tab; `aircraft` (Squads 2/3) roster `A611` only, tab chosen by aircraft (`A611-OCT06`), the zone exists only on the tab, so a roster edit goes to an `UNASSIGNED` section (`config.LINK_UNASSIGNED_TITLE`) unless the person is already in some zone of that tab (then left there).
- **Rules.** Normal N or Clear removes the person from every day tab of that date. Role codes (`TĐ`/`PPC`/`FM`, also `A864-FM`), course markers and `@16H00` shift codes are not linked. Locked roster cells (`H ...`, red N) block the whole plan (also from the daily side: nobody on a course or a guaranteed day off can be placed). Roster-origin: the roster is primary; a day tab that cannot follow (no tab for that date/aircraft, no free row) gives `roster_only` with the reason, tabs are never created. Daily-origin is all or nothing, and only `UNASSIGNED` may be created; a typo'd section is refused. Daily move to a zone sets the roster code (`zone`: the title; `aircraft`: the tab's aircraft, only if the cell does not already name it); a black N is replaced with a note; a roster cell holding other text (`P`) blocks, a role code is left alone.
- **Day-tab writes** never insert or delete rows: first free row inside the section's own bounds (rows between its title and the next title, or below the data for the last section of a table); a missing section is appended at the bottom of the emptier table (title in the NAME column, person on the next row); ORD only when its cell is blank (max+1); phone from the phone book when the table has a PHONE column. **Removal blanks the whole row including ORD**: a row holding only an ORD number is read by `distribution.parse_day` as a section title (found by a test, not by design). `locate_day` mirrors `parse_day`'s header/person/title rules and keeps row numbers (a test checks both agree).
- **Decisions I took where the plan said "to be decided"** (change in `config.py` if you disagree): taking someone out of the distribution leaves the roster cell as it is (`LINK_REMOVE_CLEARS_ROSTER = False`); a missing day tab is reported, not created (the plan's second option); Clear is treated like Normal N (removes from the daily). Not done on purpose: ORD renumbering/compacting after a removal, merged cells in section titles, two aircraft in one day, shifts, no UI for the dry run.
- Tests: `tests/test_assignments.py` (28; with the rest `pytest tests` = 73 pass) on mock squads laid out like the screenshot grids: **not run against the live sheets**.
- To check live (needs credentials): run `tools/link_dry_run.py` on a few real days of each squad and read the printed cells against the sheet before Phase 4 writes anything: (1) the real day tabs have blank rows inside/below each section (the mocks assume so; sheets whose sections are packed against the next title give "no free row"); (2) the ORD column holds numbers only on person rows; (3) Squad 1/4 `A/C:` and aircraft in section titles match the roster codes; (4) section titles are in the NAME column (not merged from column A) so appending a title there works.
- Next: Phase 4 (daily edit written to the day tab and the roster, using these plans; roster first, then the day tab, partial failure reported).
