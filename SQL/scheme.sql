-- roster-assistant: DRAFT PostgreSQL schema (replaces Google Sheets). Plain Postgres only.
-- Derived from the repo code (squad_roster.py, distribution.py, khdt_review.py). Review before use.

CREATE TABLE squads (
    id        smallint PRIMARY KEY,            -- 1..4
    name      text NOT NULL                    -- "Squad 1" ...
);

CREATE TABLE employees (
    employee_id  text PRIMARY KEY,             -- VAECO ID (the roster's unique key)
    full_name    text NOT NULL,
    squad_id     smallint REFERENCES squads(id),
    is_reinforcement boolean NOT NULL DEFAULT false,  -- below "NV TĂNG CƯỜNG" block
    phone        text,
    active       boolean NOT NULL DEFAULT true
);

-- One row per employee per day (a roster "cell"). Colour matters: red N vs black N differ.
CREATE TABLE roster_entries (
    employee_id  text NOT NULL REFERENCES employees(employee_id),
    work_date    date NOT NULL,
    code         text NOT NULL DEFAULT '',     -- e.g. 'N', 'H ATHK', 'TĐ', 'ppc', 'fm', shift codes
    is_red       boolean NOT NULL DEFAULT false,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    updated_by   text,
    PRIMARY KEY (employee_id, work_date)
);
CREATE INDEX ON roster_entries (work_date);

-- Daily Distribution: one plan per squad per day (tab).
CREATE TABLE day_plans (
    id          bigserial PRIMARY KEY,
    squad_id    smallint NOT NULL REFERENCES squads(id),
    plan_date   date NOT NULL,
    aircraft    text,                          -- A/C e.g. A864, B218
    check_type  text,                          -- e.g. 'WO COMP', 'CHECK'
    UNIQUE (squad_id, plan_date, aircraft)
);

CREATE TABLE day_crew (                        -- foreman, trực đội (BCH đội), dock planner, tech support, CRS
    plan_id      bigint NOT NULL REFERENCES day_plans(id) ON DELETE CASCADE,
    role         text NOT NULL CHECK (role IN ('foreman','truc_doi','dock_planner','tech_support','crs')),
    employee_id  text REFERENCES employees(employee_id),
    display_name text,
    phone        text,
    PRIMARY KEY (plan_id, role, display_name)
);

CREATE TABLE day_zones (
    id        bigserial PRIMARY KEY,
    plan_id   bigint NOT NULL REFERENCES day_plans(id) ON DELETE CASCADE,
    title     text NOT NULL,                   -- 'ZONE 128', 'A864-AVI', 'STRUCTURE PAINTING'
    sort_no   int NOT NULL DEFAULT 0
);

CREATE TABLE day_assignments (
    id           bigserial PRIMARY KEY,
    zone_id      bigint NOT NULL REFERENCES day_zones(id) ON DELETE CASCADE,
    ord          int,
    employee_id  text REFERENCES employees(employee_id),  -- may be NULL (name only / no ID yet)
    display_name text,
    position     text,
    phone        text,
    remark       text
);

-- KHDT (training plan) review: replaces per-browser localStorage + Sheets export.
CREATE TABLE khdt_runs (
    id          bigserial PRIMARY KEY,
    filename    text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    created_by  text
);

CREATE TABLE khdt_changes (
    id           bigserial PRIMARY KEY,
    run_id       bigint NOT NULL REFERENCES khdt_runs(id) ON DELETE CASCADE,
    employee_id  text NOT NULL REFERENCES employees(employee_id),
    work_date    date NOT NULL,
    old_code     text, old_is_red boolean,
    new_code     text NOT NULL, new_is_red boolean NOT NULL DEFAULT true,
    kind         text NOT NULL CHECK (kind IN ('new','update','dayoff','conflict')),
    status       text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','kept','rejected','applied')),
    decided_by   text, decided_at timestamptz,
    UNIQUE (run_id, employee_id, work_date)
);

-- Audit trail for every roster edit (who/when/old/new) - Sheets' version history is lost otherwise.
CREATE TABLE roster_audit (
    id           bigserial PRIMARY KEY,
    at           timestamptz NOT NULL DEFAULT now(),
    actor        text,
    employee_id  text,
    work_date    date,
    old_code     text, old_is_red boolean,
    new_code     text, new_is_red boolean,
    source       text                          -- 'import','khdt_export','manual'
);
