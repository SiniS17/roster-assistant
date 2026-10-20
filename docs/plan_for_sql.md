# plan.md — Migrate roster-assistant from Google Sheets to PostgreSQL

Goal: replace the 4 squad Google Sheets (+ the KHDT roster sheet's `Main`/`temp` tabs) with PostgreSQL, so data is easy to access and edit, without breaking Roster, Daily Distribution, or KHDT → Roster along the way.

**Working agreement**
- Discuss logic and trade-offs first, then code. Each step has a "Decide" part (talk) before a "Build" part (code).
- Output only modified files; full file content (CSS: changed blocks only).
- Out-of-scope edge cases get dismissed explicitly, not worked around.
- After every task: add/update an entry in `CLAUDE.md`.

**Safety rule for the whole plan:** Sheets stay the source of truth until Step 8. Nothing is deleted or switched off before the DB output has been proven identical.

---

## Status board

| # | Step | Status | Remarks |
|---|------|--------|---------|
| 0 | Decisions & scope | 🔶 0.1-0.5, 0.7 decided; 0.6 pending confirmation | **Risk of "last N months" (0.5):** (1) older months aren't in the DB, so they can't be viewed or edited in the app; (2) KHDT runs touching an old month find no roster rows; (3) people who appear only in older months won't exist as employees; (4) parity check (Step 5) only proves the imported range; (5) if N is too small we re-import (safe, the importer is idempotent) but only while the sheets still exist, so keep them until N is final. N is decided later. |
| 1 | Inventory the current sheets | ☐ | Needs `docs/HOW_IT_WORKS.md` and `docs/structure.md` |
| 2 | Finalize schema + create database | ☐ | Now also needs `users`/roles tables (0.7) |
| 3 | Data-access layer (backend switch) | ☐ | |
| 4 | Importer: Sheets → Postgres | ☐ | Range limited by N (0.5) |
| 5 | Parity check (Sheets vs DB) | ☐ | Covers only the imported months |
| 6 | Switch reads to Postgres | ☐ | |
| 7 | Switch KHDT writes to Postgres | ☐ | |
| 8 | Roles, editing UI + cutover | ☐ | Expanded: login + roles + edit screens (0.7) |
| 9 | Cleanup, backups, docs | ☐ | |


---

## Step 0 — Decisions & scope (discussion only, no code)

Decide together:

1. **Where does Postgres live?** Local only, same host as the Flask app, or a managed service. Drives backups, connection string, and who can reach it.
2. **Postgres version.** Matters for one schema detail (`UNIQUE NULLS NOT DISTINCT` needs 15+; otherwise we use a different index).
3. **Driver and style.** Proposal: `psycopg` (v3) + plain SQL, no ORM (the draft schema says "plain Postgres only", and the app is small).
4. **Migrations.** Proposal: numbered plain `.sql` files in `SQL/migrations/` applied by a tiny script, instead of Alembic.
5. **History scope.** How far back do we import? Current month only, last N months, or everything the sheets hold.
6. **Who edits data after cutover, and how?** (See Step 8.) Options: SQL client (DBeaver/pgAdmin), a small admin page in the app, or keep editing in Sheets with a periodic re-import.
7. **Does Daily Distribution stay read-only in the app?** Today it only reads. If the DB replaces the sheet, someone must still create each day's plan somewhere.

**Recommended setup (test now, move later)**
- Test DB: Postgres in Docker (`docker compose`), same major version as the company machine, data in a named volume. If Docker isn't an option, install the same version natively.
- Schema is always rebuilt from `SQL/migrations/*.sql`, never copied by hand.
- Data moves with `pg_dump -Fc --no-owner --no-privileges` then `pg_restore` on the company machine. One file, fast, version-safe (target version must be the same or newer).
- Alternative for data: re-run the idempotent importer (Step 4) against the real sheets on the company machine. Use this if the test DB only holds imported data; use dump/restore if you edited data in the test DB.
- Only `DATABASE_URL` changes between test and company machine.

**Done when:** each point above has a written answer in this file (fill the "Decisions" section at the bottom).

---

## Step 1 — Inventory the current sheets

Decide/Build: write a field-mapping table, sheet layout → table/column, for every thing the code reads.

Sources to read: `squad_roster.py`, `distribution.py`, `khdt_review.py`, `config.py`, and `docs/HOW_IT_WORKS.md` (exact layouts and marking rules).

Capture, per sheet:
- Header rows, ID/name/phone columns, how dates map to columns, where the "NV TĂNG CƯỜNG" (reinforcement) block starts.
- How cell **colour** is read (red `N` vs black `N` matters, so the importer must read formatting, not just values).
- Distribution tabs: how a tab is named per day, zone blocks, crew roles (`TĐ`, `ppc`, `fm`), rows with a name but no ID.
- Quirks: merged cells, blank vs missing, trailing spaces, duplicated IDs, people appearing in two squads.

**Deliverable:** a "Sheet → DB mapping" table appended to this file.
**Done when:** every column the code touches has a destination, and every oddity has a stated rule.

---

## Step 2 — Finalize schema + create database

Start from the draft `SQL/scheme.sql`. Issues spotted on first read, to settle before creating anything:

| Draft | Problem | Proposed fix |
|-------|---------|--------------|
| `day_crew` PRIMARY KEY `(plan_id, role, display_name)` | `display_name` is nullable, and PK columns can't be NULL | Use `id bigserial` PK + unique index on `(plan_id, role, coalesce(employee_id, display_name))` |
| `day_plans` UNIQUE `(squad_id, plan_date, aircraft)` | `aircraft` is nullable, and NULLs never collide in a normal unique constraint, so duplicates slip in | `NULLS NOT DISTINCT` (PG 15+) or a unique index on `coalesce(aircraft,'')` |
| `roster_entries.code` default `''` | Dense vs sparse: one row for every blank cell, or only for filled ones? | Proposal: sparse (only store non-empty cells; blank = no row) |
| `employees.squad_id` single value | If people move squads over time, history of old months would show them in the wrong squad | Decide if squad membership is static for our purposes (if yes, dismiss it as out of scope) |
| `phone` in both `employees` and `day_assignments` | Two sources of truth | Keep `employees.phone` as the master; `day_assignments.phone` only if sheets hold a different per-day number |
| `roster_audit` has no FKs | Intentional (audit must survive deletes), but should be stated | Keep, add a comment |
| No updated_at trigger | `roster_entries.updated_at` won't self-update | Set it in the write query, or add a trigger |

Build:
1. `SQL/migrations/001_init.sql` — the agreed schema.
2. `SQL/seed_squads.sql` — the 4 squads with the display names from `DISTRIBUTION_SHEET_NAMES`.
3. Apply migrations script + `DATABASE_URL` in `.env` / `config.py` (no hardcoded URLs elsewhere, same rule as the sheet URLs).

**Done when:** an empty database can be created from scratch with one command, and rerunning it is safe.

---

## Step 3 — Data-access layer (backend switch)

Decide: where the line is between "get roster data" and "how it's fetched".

Build:
- A small repository module with functions the pages need (roster for a month, distribution for a date, employee lookup, KHDT run read/write).
- Move the current Google Sheets code behind that interface unchanged (`sheets` backend).
- Add a `postgres` backend with the same function signatures (stubs at first).
- Config flag `DATA_BACKEND=sheets|postgres` (default `sheets`).
- Routes and templates call only the repository.

**Done when:** the app behaves exactly as before with `DATA_BACKEND=sheets`, and all existing tests still pass.

Test strategy to decide here: keep the current fake-Google tests for the sheets backend; for Postgres, run tests against a throwaway database (schema created fresh per test run).

---

## Step 4 — Importer: Sheets → Postgres

Build a command-line importer (`python -m tools.import_sheets`), in this order:

1. `squads`, then `employees` (from the 4 squad sheets, incl. reinforcement block).
2. `roster_entries` (value + colour per cell; each import row also written to `roster_audit` with `source='import'`).
3. `day_plans`, `day_crew`, `day_zones`, `day_assignments` (from the distribution tabs, within the history scope from Step 0).

Requirements:
- **Idempotent:** running it twice gives the same result (upsert by natural keys).
- **Dry-run mode:** prints what it would insert/update/skip.
- **Report:** counts per table, plus a list of rows it couldn't place (unknown ID, duplicate ID, unparseable date, name without ID).
- Read-only against Google (viewer access only, as today).

**Done when:** an import of the real sheets finishes with an explained, reviewed exceptions list.

---

## Step 5 — Parity check (Sheets vs DB)

Build a script that renders the same view from both backends and diffs them:
- Roster for chosen months (every employee, every day, code + colour).
- Daily Distribution for a sample of dates across all 4 squads (zones, assignments, crew).
- KHDT: run the same `.xlsx` against both and compare proposed changes.

Decide the sample: e.g. the current month, one older month, a day with a reinforcement employee, a day with a no-ID name.

**Done when:** diff is empty, or every difference is understood and signed off.

---

## Step 6 — Switch reads to Postgres

1. Set `DATA_BACKEND=postgres` locally, click through Roster, search, squad filter, Daily Distribution, reload button.
2. Replace `DISTRIBUTION_CACHE_SECONDS` logic: DB reads don't need the 60 s Sheets cache; decide whether the reload button stays (probably becomes a plain refresh).
3. Run for a trial period with Sheets still being edited and the importer re-run to refresh the DB.

**Done when:** the trial period passes with no mismatches found by users.

---

## Step 7 — Switch KHDT writes to Postgres

This replaces the `temp` tab entirely, in line with the preview-then-apply direction already chosen.

Flow:
1. Upload the KHDT `.xlsx` → create a `khdt_runs` row.
2. Compute changes against `roster_entries` → `khdt_changes` rows (`kind`: new / update / dayoff / conflict, `status='pending'`).
3. Review screen: per-change keep / reject (single reviewer, no team review).
4. Apply: in **one transaction**, write kept changes to `roster_entries`, mark them `applied`, and log each to `roster_audit` (`source='khdt_export'`).
5. Undo: reverse an applied run from `roster_audit` / `khdt_changes` (old_code, old_is_red).

Decide: does review state survive a page reload (it should, now that it lives in the DB instead of browser localStorage), and how long old runs are kept.

**Done when:** a full KHDT run (upload, review, apply, undo) works against Postgres and leaves a correct audit trail.

---

## Step 8 — Roles, editing UI + cutover

Today the app has no logins (it signs in to Google as a service account). Editing through the UI means the app must know who is making each change.

Decide (discussion first):
1. **Login method:** username + password stored hashed in Postgres (simplest for a local company machine), or company SSO if one exists.
2. **Roles and permissions.** Proposal to start from: `viewer` (read roster/distribution), `editor` (edit roster cells and day plans), `khdt` (run and apply KHDT), `admin` (manage users and roles). You tell me what the real functions are and who gets which.
3. **Which screens are editable:** roster cell edit, day plan / zone / assignment / crew edit, employee add/edit.

Build:
- `users`, `roles` (and user-role link) tables; login/logout, session handling, permission check on every write route.
- Every UI edit writes through one function that also writes `roster_audit` (who, when, old, new, `source='manual'`).
- Edit screens for the items chosen above, one at a time.

Cutover checklist:
1. Final import from Sheets.
2. Freeze the 4 sheets (view-only for everyone but you, "MOVED TO DB" note).
3. Switch production `DATA_BACKEND=postgres`.
4. Keep Sheets untouched for a fallback window.

**Done when:** the app runs only on Postgres, and each role can do exactly its allowed edits and nothing else.

---

## Step 9 — Cleanup, backups, docs

- Scheduled `pg_dump` backup, plus one tested restore.
- Remove (or isolate) Google dependencies no longer used; keep the importer if re-import is useful.
- Update `README.md` (Quick start, Configuration, Google access sections), `docs/structure.md`, `docs/HOW_IT_WORKS.md`, `docs/guide.md`.
- Final `CLAUDE.md` entry: what changed, open items, rollback instructions.

---

## Decisions (fill in as we go)

| # | Question | Answer |
|---|----------|--------|
| 0.1 | Postgres hosting | Test: Dockerised Postgres on your machine. Production: company-provided machine, built later (recommended setup accepted) |
| 0.2 | Postgres version | Match the company machine's major version; test DB pinned to it |
| 0.3 | Driver / ORM | `psycopg` v3 + plain SQL, no ORM (accepted) |
| 0.4 | Migration tool | Numbered plain `.sql` files + tiny apply script (accepted) |
| 0.5 | History scope | Last N months; N decided later. Risks logged in the status board Remarks |
| 0.6 | Editing path | Follows from 0.7: edits happen in the website UI (see Step 8). SQL client stays as a developer-only tool. Pending your confirmation |
| 0.7 | Distribution: read-only or editable in app | Editable via the website UI, with user roles limiting who can do what |

## Open questions / risks

- Colour is part of the data (red `N` vs black `N`); the importer must read cell formatting, and Sheets API formatting reads are heavier than value reads.
- Distribution tab layouts may vary between squads or over time; the mapping table in Step 1 must surface that early.
- Employees with a name but no ID (`employee_id` NULL in `day_assignments`) need a rule: leave NULL, or create a placeholder employee.
- Moving people between squads over time (see schema table above).