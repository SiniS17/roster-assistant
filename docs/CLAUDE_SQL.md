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

---

## Session: roles and functions for Step 8 (2026-10-20)

**Task:** Record decision 0.6 as confirmed and the role list for Step 8.

**What changed**
- `plan.md`: Step 0 status now 0.1-0.4 and 0.6-0.8 decided (0.5, the value of N, still open); 0.6 marked confirmed; new decision 0.8; Step 8 rewritten with a permissions table, starting roles, guard rails and open points; Step 2 status now lists the five auth tables; open-questions list updated.
- No application code or schema files were changed.

**Decisions**
- 0.6: edits happen in the website UI; the SQL client is a developer-only tool.
- 0.8: functions are view only, edit roster, edit distribution, run KHDT, manage users. An admin role can change roles and their functions.
- Design: permissions are fixed in code (each write route checks one); the role → permission mapping is data in Postgres, so an admin can change it from the UI without a deploy.

**Impact**
- Schema needs `users`, `roles`, `permissions`, `role_permissions`, `user_roles`.
- Admin screens (users, role assignment, role permissions) join the Step 8 build; their changes are audited too.

**Open items**
- Login method (hashed passwords in Postgres vs company SSO).
- Several roles per user (proposed: yes, permissions are the union).
- Who may grant Admin / `users.manage` (proposed: Admin only); last-Admin guard rail.
- Whether viewing needs a login (proposed: yes).
- Initial users and role assignment at cutover.
- Value of N (0.5).
- `docs/HOW_IT_WORKS.md` and `docs/structure.md` contents for Step 1.


---

## Session: login rules, view scope, history range (2026-10-20)

**Task:** Record answers on login, roles, view scope and the history range.

**What changed**
- `plan.md`: Step 0 marked done (0.1-0.9); 0.5 filled; new decision 0.9; Step 8 rewritten for squad-scoped access (`roster.view_own` / `roster.view_all`, starting roles, squad link, open points); Step 3 repository takes the viewer's allowed squads; Step 4 range made concrete; Step 1 sources updated; open questions updated.
- No application code or schema files were changed.

**Decisions**
- 0.5: import 2 months into the past and 1 month ahead (if the sheets have it).
- 0.9: hashed passwords in Postgres; several roles per user (union of permissions); only Admin grants Admin / `users.manage`; everyone logs in; users see only their own squad's roster and distribution unless a role gives view-all; initial role assignment decided later.
- `structure.md` is available; `HOW_IT_WORKS.md` is not updated yet, so Step 1 verifies layouts and marking rules against the code and live sheets.

**Impact**
- `users` needs a `squad_id`; scoping must be enforced in the data layer, not only in the UI.
- The roster's "squad membership is static" question (`employees.squad_id`) now affects access, not just history.

**Open items**
- Step 8 proposals awaiting a yes/no: edit rights limited to the squads a user can view; KHDT run needs view-all; no self-signup, admin creates accounts and resets passwords.
- Initial users and role assignment (decided later).
- Who adds next month's roster after cutover.
- Confirm squad membership is static (or dismiss explicitly).
- Next: Step 1 (sheet inventory) from `structure.md` and the code.


---

## Session: missing local-install step (2026-10-20)

**Task:** Add the missing step for installing and running Postgres on the developer laptop.

**What changed**
- `plan.md`: new **Step 2a** (install and run Postgres locally) with a status-board row; no existing step renumbered.
- No application code or schema files were changed.

**Why**
- Decision 0.1 chose Dockerised Postgres for testing, but no step said when it gets installed, and Step 2 assumed a running database.

**Step 2a contents**
- Decide: laptop OS, whether Docker is allowed, provisional Postgres version (proposal: 16, with a schema that also works on older versions).
- Build: Docker Desktop (or native Postgres), `docker-compose.yml` with a named volume, `.env.example` with `DATABASE_URL`, `psycopg[binary]` in `requirements.txt`, `tools/check_db.py` smoke test, optional SQL client.
- Habit: `down` keeps data, `down -v` deletes it.

**Open items**
- Laptop OS and whether Docker is allowed.
- Postgres version on the company machine (still unknown; test version is provisional).
- Step 8 proposals awaiting yes/no (edit scope, KHDT scope, password handling); initial users and roles; who adds next month's roster; static squad membership.
- Step 1 (sheet inventory) can run in parallel with Step 2a.