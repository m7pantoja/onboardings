CREATE TABLE IF NOT EXISTS onboardings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id         INTEGER UNIQUE NOT NULL,
    deal_name       TEXT NOT NULL,
    company_name    TEXT NOT NULL,
    service_name    TEXT NOT NULL,
    department      TEXT,
    hubspot_owner_id INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    current_step    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS onboarding_technicians (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    onboarding_id   INTEGER NOT NULL REFERENCES onboardings(id),
    hubspot_tec_id  TEXT NOT NULL,
    property_name   TEXT NOT NULL,
    UNIQUE(onboarding_id, hubspot_tec_id)
);

CREATE TABLE IF NOT EXISTS onboarding_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    onboarding_id   INTEGER NOT NULL REFERENCES onboardings(id),
    step_name       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    result_data     TEXT,  -- JSON serializado
    error_message   TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    UNIQUE(onboarding_id, step_name)
);
