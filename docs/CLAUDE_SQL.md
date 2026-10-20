## Session: PostgreSQL migration plan (2026-10-20)

> Append this entry to the repo's existing `CLAUDE.md` (keep earlier session notes as they are).

**Task:** Create `plan.md`, a step-by-step plan to replace the 4 squad Google Sheets (and the KHDT `Main`/`temp` tabs) with PostgreSQL.

**What changed**
- Added `plan.md` (Steps 0-9, status board, decisions table, open questions).
- No application code or schema files were changed.

**Findings from reading `SQL/scheme.sql` (draft, still unmodified)**
- `day_crew` primary key includes nullable `display_name`, which Postgres rejects.
- `day_plans` unique constraint on nullable `aircraft` does not prevent duplicates.
- Dense vs sparse `roster_entries` (store blank cells or not) is undecided.
- Squad membership is a single `employees.squad_id`, so there is no history if people move squads.
- `phone` is stored in both `employees` and `day_assignments`.

**Working rules for this migration**
- Sheets remain the source of truth until Step 8 (cutover).
- Discuss logic and trade-offs before writing code.
- Output only modified files; full content (CSS: changed blocks only).
- Out-of-scope edge cases are dismissed explicitly, not worked around.
- Add a `CLAUDE.md` entry after every task.

**Open items**
- Step 0 decisions: hosting, Postgres version, driver, migration tool, history scope, editing path, whether Daily Distribution is editable in-app.
- `docs/` folder could not be read this session (GitHub blocked automated access); `docs/HOW_IT_WORKS.md` and `docs/structure.md` are needed for Step 1 (sheet layouts and marking rules).

**Next**
- Start Step 0 (decisions) together, then Step 1 (sheet inventory).

---

## Session: hosting + test environment decision (2026-10-20)

**Task:** Decide how to test now and move the database to the company machine later.

**What changed**
- `plan.md`: added "Recommended setup (test now, move later)" to Step 0; filled decisions 0.1 and 0.2.

**Decisions**
- Production: company-provided machine hosting the site locally, with PostgreSQL.
- Test: Dockerised Postgres pinned to the company machine's major version.
- Move: schema from migration files, data via `pg_dump -Fc` / `pg_restore`, or re-run the importer.

**Open items**
- Company machine: Postgres version, OS, whether Docker is allowed there (still unknown).
- Remaining Step 0 decisions: driver, migration tool, history scope, editing path.

---

## Session: recommendation accepted (2026-10-20)

**Task:** Record that the recommended test/migration setup is accepted.

**What changed**
- `plan.md`: decisions 0.1-0.4 filled (Docker Postgres for testing, `psycopg` v3 + plain SQL, numbered SQL migrations); Step 0 marked partly decided.

**Workflow:** build and test locally in Docker; build on the company machine later (only `DATABASE_URL` changes).

**Open items**
- 0.5 history scope, 0.6 editing path, 0.7 Distribution read-only or editable.
- Need `docs/HOW_IT_WORKS.md` and `docs/structure.md` contents for Step 1.

---

## Session: decisions 0.5-0.7 (2026-10-20)

**Task:** Record history scope, editing path and Distribution editability.

**What changed**
- `plan.md`: status board now has a Remarks column with the "last N months" risks; decisions 0.5, 0.6, 0.7 filled; Step 8 rewritten as "Roles, editing UI + cutover".

**Decisions**
- 0.5: import last N months, N to be decided later (risks in Remarks).
- 0.7: Daily Distribution is editable through the website UI, with user roles.
- 0.6: follows from 0.7 (UI editing); pending confirmation.

**Impact**
- Schema needs `users`/roles tables; app needs login and per-route permission checks (new work, previously no logins).

**Open items**
- Role list and who gets which permission; login method.
- Value of N.
- `docs/HOW_IT_WORKS.md` and `docs/structure.md` for Step 1.