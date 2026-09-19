# ADR-005: Storage (SQLite)

## Status
Accepted

## Context
The system needs durable storage for postings, scores, alerts sent,
applications, run history/metrics, per-source circuit-breaker state, and
spend tracking -- all for a single user, running on a single machine via
cron.

## Decision
A single SQLite database (`data/jobs.db`, path configurable via
`DB_PATH`), schema in `sql/schema.sql`, applied idempotently on every
connection (`db.py::init_db` runs `CREATE TABLE IF NOT EXISTS` /
`CREATE INDEX IF NOT EXISTS` statements, so there's no separate migration
step to remember). `PRAGMA journal_mode = WAL` for safer concurrent
reads (the CLI can read while a pipeline run is writing) and
`PRAGMA foreign_keys = ON` for referential integrity between postings,
scores, alerts, and applications.

Every idempotency guarantee the spec requires is enforced at the schema
level, not just in application code, so it holds even if a caller forgets
a check:
- `postings.dedupe_key` is UNIQUE -> a posting is only ever inserted once,
  regardless of which source(s) report it.
- `scores.posting_id` is the PRIMARY KEY -> a posting is only ever scored
  once.
- `alerts` has UNIQUE(posting_id, channel, alert_type) -> an alert is only
  ever sent once per posting per channel per tier.
- `processed_emails.message_id` is the PRIMARY KEY -> an alert email is
  only ever parsed once.
- `digest_log` / `fractional_scan_log` are keyed by date[, slot] -> those
  jobs run at most once per slot per day.

## Consequences
- SQLite is the right size for one user's data on one machine; this
  would need to change (Postgres, a managed DB) if the system ever grew
  to serve multiple users concurrently, which is out of scope.
- WAL mode does mean the database is represented by three files on disk
  (`jobs.db`, `jobs.db-wal`, `jobs.db-shm`) during normal operation, which
  `.gitignore` already accounts for.
- Because idempotency lives in schema constraints, the pipeline code can
  stay straightforward (insert-or-ignore, catch the specific
  `IntegrityError` for alerts) instead of hand-rolling "have I seen this
  before" checks everywhere.
