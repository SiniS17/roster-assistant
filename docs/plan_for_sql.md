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
