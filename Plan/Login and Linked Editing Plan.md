# Login and Linked Editing Plan

Roster Assistant: discussion draft, 28 October 2026. No code written and no files changed yet.

## 1. Login (simple part)

- `Database/users.xlsx` with columns `username | password`, plus a small `tools/make_users.py` that creates it with one admin account.
- New `auth.py` with `verify(username, password)`, a `login_required` decorator, and routes `POST /api/login`, `POST /api/logout`, `GET /api/me`. The session uses the existing `FLASK_SECRET_KEY`. The xlsx is re-read when its modified time changes, so accounts can be edited without restarting.
- Every write route (the new edit routes, `/api/khdt/export`, legacy `/run`) gets `@login_required`. All GET routes stay open, so logged-out users still see everything.
- The UI gets a Login button in the top bar and an **Edit mode** toggle that only exists when logged in. Logged-out users never see edit controls.
- Everything goes through `auth.py` and one `can_edit(user, squad)` function that returns `True` for now. That is the seam where roles slot in later (Step 8 of `plan_for_sql.md`).
- Housekeeping: add `Database/` to `.gitignore`, because the file holds plain passwords. If hosted on Vercel, the filesystem is read-only, so the xlsx would have to be committed. Fine locally, but worth knowing.

## 2. Roster editing

- In edit mode, click a cell or drag a date range for one person and choose a value: an **aircraft code** (free text with suggestions from codes already in use), **normal N** (black), or **clear**.
- Edits are staged, then saved in one batch. This reuses the proven `khdt_review.export` checks: same employee on that row, same date column, cell still holds what the page saw. A cell that changed meanwhile is skipped and reported.
- **Locked cells:** red N and `H …` course markers cannot be overwritten by hand (KHDT owns those), and the editor cannot write red N.
- `TĐ/PPC/FM` is left out of phase 1. Day-tab labels already override roster codes for crew on squads 1/4, so editing them would create confusing precedence.

## 3. The link between roster and daily distribution

The two sheets do not describe the same thing equally well:

| Squad | Roster cell | Day tab |
| --- | --- | --- |
| 1 / 4 | `A864-34` (aircraft + zone) | section `A864-34` |
| 2 / 3 | `A611` (aircraft only) | tab `A611-OCT06`, section `ZONE 128` |

The sync is exact for squads 1/4. For squads 2/3 it is lossy: the zone lives only in the daily view. Proposed rules:

- **Daily → roster:** moving someone into a zone sets their roster cell to the aircraft, plus the zone on squads 1/4. Removing them from a zone clears the aircraft part (or leaves it, to be decided).
- **Roster → daily:** setting `A864-34` places the person in that section on squads 1/4. For squads 2/3, or when no zone is given, they go into an `UNASSIGNED` section on that day's tab until someone moves them to a zone.
- **Normal N** removes the person from that day's distribution.
- **Missing day tab:** the big open point. Options are to create it by duplicating a template tab, or to only update days whose tab already exists and tell the user otherwise.
- One code per cell, so two aircraft in one day is not supported. `@16H00` shifts are also out of scope for now; both are dismissed explicitly.

## 4. The risky part

Roster writes are one cell each. Day-tab writes are not. Tabs have an info block and two side-by-side tables, so inserting or deleting a row shifts the neighbouring table. Sheets also has no transaction across the roster and the day tab. If the second write fails, they drift apart.

Mitigations:

- Write only cell values inside a section's own bounds, never insert or delete rows.
- Write the roster first, then the day tab, and report partial failure clearly.
- Add a mismatch check on the daily page ("roster says A864-34, tab does not list them"), since people will also edit the sheets directly.
- Start with a dry-run that prints the exact cells it would write, tested on the screenshot-based mock grids, before enabling real writes.

This part is exactly what the PostgreSQL plan makes easy. The code should sit behind a small `assignments.py` interface with a Sheets adapter now, so a DB adapter can replace it later.

## 5. Phases

1. Login, logout, `/api/me`, and guards on existing write routes, with tests.
2. Roster edit: staged edits, batch save, locks, stale checks, with tests.
3. Link logic, dry-run only, per-squad layout adapters.
4. Daily edit, written to the day tab and the roster.
5. Roster edit, now also writing to the day tab (create or modify).
6. Mismatch indicator, docs, and the `CLAUDE.md` entry.

Anything not mentioned above stays as the current design.

## Open decision

Which direction for the day-tab write-back: write into the existing Google day tabs as described (fragile but keeps Sheets as the source), or build phases 1-2 now and hold the daily write-back until the Postgres step?
