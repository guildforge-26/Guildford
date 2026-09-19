"""SQLite access layer. All idempotency guarantees live here:

- postings.dedupe_key is UNIQUE -> a posting is only ever inserted once.
- scores.posting_id is the PRIMARY KEY -> a posting is only ever scored once.
- alerts has UNIQUE(posting_id, channel, alert_type) -> never double-alerted.
- processed_emails.message_id is the PRIMARY KEY -> an alert email is only read once.
- digest_log / fractional_scan_log PK on (date[, slot]) -> those jobs run once per slot/day.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .config import Settings

_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "sql" / "schema.sql"


def get_connection(settings: Settings) -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text())
    conn.commit()


@contextmanager
def connect(settings: Settings) -> Iterator[sqlite3.Connection]:
    conn = get_connection(settings)
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


# --- postings -----------------------------------------------------------

def upsert_posting(conn: sqlite3.Connection, posting: dict) -> tuple[str, bool]:
    """Insert a posting if its dedupe_key is new. Returns (posting_id, is_new)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO postings
            (id, canonical_url, dedupe_key, source, source_id, title, company,
             location, salary_text, posted_at, collected_at, status, first_run_id)
        VALUES (:id, :canonical_url, :dedupe_key, :source, :source_id, :title, :company,
                :location, :salary_text, :posted_at, :collected_at, 'new', :first_run_id)
        """,
        posting,
    )
    conn.commit()
    is_new = cur.rowcount == 1
    row = conn.execute(
        "SELECT id FROM postings WHERE dedupe_key = ?", (posting["dedupe_key"],)
    ).fetchone()
    return row["id"], is_new


def get_posting(conn: sqlite3.Connection, posting_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM postings WHERE id = ?", (posting_id,)).fetchone()


def set_posting_status(conn: sqlite3.Connection, posting_id: str, status: str, reason: str | None = None) -> None:
    conn.execute(
        "UPDATE postings SET status = ?, prefilter_reason = ?, updated_at = datetime('now') WHERE id = ?",
        (status, reason, posting_id),
    )
    conn.commit()


def set_posting_enriched(conn: sqlite3.Connection, posting_id: str, raw_text: str) -> None:
    conn.execute(
        """UPDATE postings SET raw_text = ?, enriched_at = datetime('now'),
           status = 'enriched', updated_at = datetime('now') WHERE id = ?""",
        (raw_text, posting_id),
    )
    conn.commit()


def postings_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM postings WHERE status = ?", (status,)).fetchall()


def postings_collected_between(conn: sqlite3.Connection, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM postings WHERE collected_at >= ? AND collected_at < ?",
        (start_iso, end_iso),
    ).fetchall()


def postings_needing_scoring(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Postings that are enriched (or failed enrichment) but were never
    successfully scored -- includes ones whose scoring call errored on a
    previous run. Dedupe means a posting is only ever collected once, so
    without this a scoring failure would otherwise go unretried forever."""
    return conn.execute(
        """
        SELECT p.* FROM postings p
        LEFT JOIN scores s ON s.posting_id = p.id
        WHERE p.status IN ('enriched', 'enrich_failed', 'error') AND s.posting_id IS NULL
        """
    ).fetchall()


# --- scores ---------------------------------------------------------------

def has_score(conn: sqlite3.Connection, posting_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM scores WHERE posting_id = ?", (posting_id,)).fetchone()
    return row is not None


def save_score(conn: sqlite3.Connection, posting_id: str, score: dict, run_id: str) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO scores
            (posting_id, verified, track, tier, total_score, breakdown_json, hard_filter_passed,
             hard_filter_reason, matching_facts_json, top_gaps_json, resume_version,
             warm_angle, next_action, ai_bonus_score, ai_bonus_notes, model_used,
             input_tokens, output_tokens, cost_usd, raw_json, run_id)
        VALUES (:posting_id, :verified, :track, :tier, :total_score, :breakdown_json, :hard_filter_passed,
                :hard_filter_reason, :matching_facts_json, :top_gaps_json, :resume_version,
                :warm_angle, :next_action, :ai_bonus_score, :ai_bonus_notes, :model_used,
                :input_tokens, :output_tokens, :cost_usd, :raw_json, :run_id)
        """,
        {"posting_id": posting_id, "run_id": run_id, **score},
    )
    conn.execute(
        "UPDATE postings SET status = 'scored', updated_at = datetime('now') WHERE id = ?",
        (posting_id,),
    )
    conn.commit()


def get_score(conn: sqlite3.Connection, posting_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM scores WHERE posting_id = ?", (posting_id,)).fetchone()


def scores_with_postings_since(conn: sqlite3.Connection, since_iso: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT p.*, s.*
        FROM scores s JOIN postings p ON p.id = s.posting_id
        WHERE s.scored_at >= ?
        ORDER BY s.total_score DESC
        """,
        (since_iso,),
    ).fetchall()


# --- alerts -----------------------------------------------------------------

def record_alert(conn: sqlite3.Connection, posting_id: str, channel: str, alert_type: str, run_id: str) -> bool:
    """Returns True if this alert was newly recorded, False if it was already sent (idempotent)."""
    try:
        conn.execute(
            "INSERT INTO alerts (posting_id, channel, alert_type, run_id) VALUES (?, ?, ?, ?)",
            (posting_id, channel, alert_type, run_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def has_alert(conn: sqlite3.Connection, posting_id: str, channel: str, alert_type: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE posting_id = ? AND channel = ? AND alert_type = ?",
        (posting_id, channel, alert_type),
    ).fetchone()
    return row is not None


# --- processed emails ---------------------------------------------------

def is_email_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM processed_emails WHERE message_id = ?", (message_id,)).fetchone()
    return row is not None


def mark_email_processed(conn: sqlite3.Connection, message_id: str, source: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO processed_emails (message_id, source) VALUES (?, ?)",
        (message_id, source),
    )
    conn.commit()


# --- runs -----------------------------------------------------------------

def start_run(conn: sqlite3.Connection, run_id: str, kind: str = "pipeline") -> None:
    conn.execute(
        "INSERT INTO runs (run_id, kind, started_at, status) VALUES (?, ?, datetime('now'), 'running')",
        (run_id, kind),
    )
    conn.commit()


def finish_run(conn: sqlite3.Connection, run_id: str, status: str, counts: dict, cost_usd: float, errors: list) -> None:
    conn.execute(
        """UPDATE runs SET finished_at = datetime('now'), status = ?, counts_json = ?,
           cost_usd = ?, errors_json = ? WHERE run_id = ?""",
        (status, json.dumps(counts), cost_usd, json.dumps(errors), run_id),
    )
    conn.commit()


def recent_runs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()


# --- source health / circuit breaker ---------------------------------------

def get_source_health(conn: sqlite3.Connection, source: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM source_health WHERE source = ?", (source,)).fetchone()


def record_source_success(conn: sqlite3.Connection, source: str) -> None:
    conn.execute(
        """
        INSERT INTO source_health (source, consecutive_failures, paused_until, last_success_at, last_attempt_at)
        VALUES (?, 0, NULL, datetime('now'), datetime('now'))
        ON CONFLICT(source) DO UPDATE SET
            consecutive_failures = 0, paused_until = NULL,
            last_success_at = datetime('now'), last_attempt_at = datetime('now')
        """,
        (source,),
    )
    conn.commit()


def record_source_failure(conn: sqlite3.Connection, source: str, error: str, paused_until_iso: str | None) -> None:
    conn.execute(
        """
        INSERT INTO source_health (source, consecutive_failures, paused_until, last_error, last_attempt_at)
        VALUES (?, 1, ?, ?, datetime('now'))
        ON CONFLICT(source) DO UPDATE SET
            consecutive_failures = consecutive_failures + 1,
            paused_until = ?,
            last_error = ?,
            last_attempt_at = datetime('now')
        """,
        (source, paused_until_iso, error, paused_until_iso, error),
    )
    conn.commit()


# --- spend ledger -----------------------------------------------------------

def record_spend(conn: sqlite3.Connection, run_id: str, posting_id: str, day: str, month: str, cost_usd: float) -> None:
    conn.execute(
        "INSERT INTO spend_ledger (run_id, posting_id, day, month, cost_usd) VALUES (?, ?, ?, ?, ?)",
        (run_id, posting_id, day, month, cost_usd),
    )
    conn.commit()


def get_run_spend(conn: sqlite3.Connection, run_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM spend_ledger WHERE run_id = ?", (run_id,)
    ).fetchone()
    return float(row["total"])


def get_spend(conn: sqlite3.Connection, column: str, value: str) -> float:
    assert column in ("day", "month")
    row = conn.execute(
        f"SELECT COALESCE(SUM(cost_usd), 0) AS total FROM spend_ledger WHERE {column} = ?", (value,)
    ).fetchone()
    return float(row["total"])


# --- digest / fractional scan idempotency -----------------------------------

def has_digest_sent(conn: sqlite3.Connection, log_date: str, slot: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM digest_log WHERE log_date = ? AND slot = ?", (log_date, slot)
    ).fetchone()
    return row is not None


def record_digest_sent(conn: sqlite3.Connection, log_date: str, slot: str, draft_id: str | None) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO digest_log (log_date, slot, draft_id) VALUES (?, ?, ?)",
        (log_date, slot, draft_id),
    )
    conn.commit()


def has_fractional_scan_run(conn: sqlite3.Connection, log_date: str) -> bool:
    row = conn.execute("SELECT 1 FROM fractional_scan_log WHERE log_date = ?", (log_date,)).fetchone()
    return row is not None


def record_fractional_scan(conn: sqlite3.Connection, log_date: str, flagged: list) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO fractional_scan_log (log_date, flagged_json) VALUES (?, ?)",
        (log_date, json.dumps(flagged)),
    )
    conn.commit()


# --- applications -----------------------------------------------------------

def add_application(conn: sqlite3.Connection, posting_id: str | None, company: str, role: str,
                     contact: str | None, date_applied: str, next_step_due: str | None) -> int:
    cur = conn.execute(
        """INSERT INTO applications (posting_id, date_applied, company, role, contact, next_step_due)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (posting_id, date_applied, company, role, contact, next_step_due),
    )
    conn.commit()
    return cur.lastrowid


def update_application_status(conn: sqlite3.Connection, application_id: int, status: str, next_step: str | None = None) -> bool:
    cur = conn.execute(
        """UPDATE applications SET status = ?, next_step = COALESCE(?, next_step),
           updated_at = datetime('now') WHERE id = ?""",
        (status, next_step, application_id),
    )
    conn.commit()
    return cur.rowcount > 0


def list_applications(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute("SELECT * FROM applications WHERE status = ? ORDER BY date_applied", (status,)).fetchall()
    return conn.execute("SELECT * FROM applications ORDER BY date_applied").fetchall()


def applications_due_followup(conn: sqlite3.Connection, as_of_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM applications
           WHERE next_step_due IS NOT NULL AND next_step_due <= ?
             AND status NOT IN ('rejected', 'withdrawn', 'offer')""",
        (as_of_date,),
    ).fetchall()
