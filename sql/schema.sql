-- Job Alert System database schema (SQLite).
-- Applied idempotently by src/jobalerts/db.py::init_db() on every run.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- One row per unique posting, deduplicated across sources.
CREATE TABLE IF NOT EXISTS postings (
    id TEXT PRIMARY KEY,                 -- sha256(canonical_url) or sha256(dedupe_key) fallback
    canonical_url TEXT,
    dedupe_key TEXT NOT NULL,            -- normalized "company|title|location"
    source TEXT NOT NULL,                -- email_linkedin, email_indeed, greenhouse, lever, ashby, workable, adzuna, job_bank, gov_ca
    source_id TEXT,                      -- id/url as seen at the source, for traceability
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    salary_text TEXT,
    posted_at TEXT,
    collected_at TEXT NOT NULL,
    raw_text TEXT,                       -- full posting body once enriched
    enriched_at TEXT,
    status TEXT NOT NULL DEFAULT 'new',  -- new, prefiltered_out, enrich_failed, enriched, scored, error
    prefilter_reason TEXT,
    first_run_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_postings_dedupe ON postings(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_postings_status ON postings(status);
CREATE INDEX IF NOT EXISTS idx_postings_canonical_url ON postings(canonical_url);

-- One row per scored posting. PK on posting_id enforces "scored once".
CREATE TABLE IF NOT EXISTS scores (
    posting_id TEXT PRIMARY KEY REFERENCES postings(id),
    track TEXT,
    tier TEXT,
    total_score INTEGER,
    breakdown_json TEXT,                 -- the 7-part score breakdown, as returned by the model
    hard_filter_passed INTEGER,          -- 0/1
    hard_filter_reason TEXT,
    matching_facts_json TEXT,            -- 3 matching facts
    top_gaps_json TEXT,                  -- top 3 gaps
    resume_version TEXT,
    warm_angle TEXT,
    next_action TEXT,
    ai_bonus_score INTEGER,
    ai_bonus_notes TEXT,
    model_used TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    scored_at TEXT NOT NULL DEFAULT (datetime('now')),
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_scores_total ON scores(total_score);
CREATE INDEX IF NOT EXISTS idx_scores_track ON scores(track);

-- One row per alert actually sent. UNIQUE constraint enforces "never double-alert".
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT NOT NULL REFERENCES postings(id),
    channel TEXT NOT NULL,               -- ntfy, digest_am, digest_pm, markdown
    alert_type TEXT NOT NULL,            -- immediate_a, digest_b, track2_alert
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    run_id TEXT,
    UNIQUE(posting_id, channel, alert_type)
);

-- Applications tracking table, driven by the `jobs` CLI.
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT REFERENCES postings(id),
    date_applied TEXT,
    company TEXT NOT NULL,
    role TEXT NOT NULL,
    contact TEXT,
    status TEXT NOT NULL DEFAULT 'applied',  -- applied, interview, offer, rejected, withdrawn, no_response
    next_step TEXT,
    next_step_due TEXT,                  -- computed: date_applied + 5 business days, unless overridden
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per pipeline run, for logging/metrics.
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'pipeline',  -- pipeline, digest, fractional_scan
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running', -- running, success, partial, failed, killed_stop, killed_timeout
    counts_json TEXT,
    cost_usd REAL DEFAULT 0,
    errors_json TEXT
);

-- Circuit breaker state, one row per source.
CREATE TABLE IF NOT EXISTS source_health (
    source TEXT PRIMARY KEY,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    paused_until TEXT,
    last_error TEXT,
    last_success_at TEXT,
    last_attempt_at TEXT
);

-- Every scoring-call cost, for daily/monthly spend caps.
CREATE TABLE IF NOT EXISTS spend_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    posting_id TEXT,
    day TEXT NOT NULL,      -- YYYY-MM-DD (local Mountain date)
    month TEXT NOT NULL,    -- YYYY-MM (local Mountain date)
    cost_usd REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_spend_day ON spend_ledger(day);
CREATE INDEX IF NOT EXISTS idx_spend_month ON spend_ledger(month);

-- Gmail message ids already ingested, so a re-run never double-processes an alert email.
CREATE TABLE IF NOT EXISTS processed_emails (
    message_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,   -- linkedin, indeed
    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One row per (date, slot) digest actually drafted -- idempotency for the hourly digest checker.
CREATE TABLE IF NOT EXISTS digest_log (
    log_date TEXT NOT NULL,
    slot TEXT NOT NULL,     -- am, pm
    sent_at TEXT NOT NULL DEFAULT (datetime('now')),
    draft_id TEXT,
    PRIMARY KEY (log_date, slot)
);

-- One row per day the fractional-CFO/COO scan has run -- idempotency for the daily scan.
CREATE TABLE IF NOT EXISTS fractional_scan_log (
    log_date TEXT PRIMARY KEY,
    run_at TEXT NOT NULL DEFAULT (datetime('now')),
    flagged_json TEXT
);
