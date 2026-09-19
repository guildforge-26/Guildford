"""Central settings, loaded from .env with safe defaults.

Nothing here reads briefing.txt content -- that stays out of this module so
config can be imported (and tested) without the real briefing present.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env_str(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val not in (None, "") else default


# Gemini pricing per 1M tokens, USD. gemini-2.5-flash is used on the FREE
# tier (Google AI Studio API key, no Cloud Billing account attached), which
# is $0 per call -- see docs/adr/ADR-006-scoring-model-gemini-free-tier.md.
# If you ever attach Cloud Billing and move off the free tier, replace
# these with Gemini's current paid per-token rates (ai.google.dev/pricing)
# before trusting cost_usd numbers again.
PRICING = {
    "gemini-2.5-flash": {
        "input_per_mtok": 0.0,
        "output_per_mtok": 0.0,
    },
}


@dataclass(frozen=True)
class Settings:
    # Paths
    base_dir: Path = BASE_DIR
    briefing_path: Path = field(default_factory=lambda: Path(_env_str("BRIEFING_PATH", "./briefing.txt")))
    targets_path: Path = field(default_factory=lambda: Path(_env_str("TARGETS_PATH", "./targets.yaml")))
    db_path: Path = field(default_factory=lambda: Path(_env_str("DB_PATH", "./data/jobs.db")))
    tracks_config_path: Path = field(default_factory=lambda: BASE_DIR / "config" / "tracks.yaml")
    logs_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    alerts_dir: Path = field(default_factory=lambda: BASE_DIR / "alerts")
    lock_path: Path = field(default_factory=lambda: BASE_DIR / "data" / "pipeline.lock")
    stop_path: Path = field(default_factory=lambda: BASE_DIR / "STOP")

    # Gemini API (free tier -- Google AI Studio key, no Cloud Billing needed)
    gemini_api_key: str = field(default_factory=lambda: _env_str("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: _env_str("GEMINI_MODEL", "gemini-2.5-flash"))

    # Gmail
    gmail_credentials_path: Path = field(default_factory=lambda: Path(_env_str("GMAIL_CREDENTIALS_PATH", "./gmail_credentials.json")))
    gmail_token_path: Path = field(default_factory=lambda: Path(_env_str("GMAIL_TOKEN_PATH", "./gmail_token.json")))
    digest_to_email: str = field(default_factory=lambda: _env_str("DIGEST_TO_EMAIL", ""))

    # Adzuna
    adzuna_app_id: str = field(default_factory=lambda: _env_str("ADZUNA_APP_ID", ""))
    adzuna_app_key: str = field(default_factory=lambda: _env_str("ADZUNA_APP_KEY", ""))

    # Job Bank / GC feeds (optional -- collector skips itself if unset)
    job_bank_feed_url: str = field(default_factory=lambda: _env_str("JOB_BANK_FEED_URL", ""))
    gc_jobs_feed_url: str = field(default_factory=lambda: _env_str("GC_JOBS_FEED_URL", ""))

    # ntfy
    ntfy_topic: str = field(default_factory=lambda: _env_str("NTFY_TOPIC", ""))

    # Guardrails / cost controls
    max_model_calls_per_run: int = field(default_factory=lambda: _env_int("MAX_MODEL_CALLS_PER_RUN", 20))
    max_retries_per_source: int = field(default_factory=lambda: _env_int("MAX_RETRIES_PER_SOURCE", 3))
    run_timeout_seconds: int = field(default_factory=lambda: _env_int("RUN_TIMEOUT_SECONDS", 1200))
    circuit_breaker_failure_threshold: int = field(default_factory=lambda: _env_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 3))
    circuit_breaker_cooldown_hours: int = field(default_factory=lambda: _env_int("CIRCUIT_BREAKER_COOLDOWN_HOURS", 24))
    daily_spend_cap_usd: float = field(default_factory=lambda: _env_float("DAILY_SPEND_CAP_USD", 2.00))
    monthly_spend_cap_usd: float = field(default_factory=lambda: _env_float("MONTHLY_SPEND_CAP_USD", 30.00))

    # Scoring thresholds
    alert_score_a: int = field(default_factory=lambda: _env_int("ALERT_SCORE_A", 80))
    alert_score_b_min: int = field(default_factory=lambda: _env_int("ALERT_SCORE_B_MIN", 65))
    track2_alert_score: int = field(default_factory=lambda: _env_int("TRACK2_ALERT_SCORE", 70))
    min_salary_usd: int = 100_000          # full-time floor, briefing.txt Part B
    min_monthly_retainer_usd: int = 5_000  # fractional/interim (Track 2) floor, briefing.txt Part B
    followup_business_days: int = 5
    collect_lookback_hours: int = field(default_factory=lambda: _env_int("COLLECT_LOOKBACK_HOURS", 26))

    # Scheduling
    timezone: str = field(default_factory=lambda: _env_str("TIMEZONE", "America/Edmonton"))
    digest_hour_am: int = field(default_factory=lambda: _env_int("DIGEST_HOUR_AM", 7))
    digest_hour_pm: int = field(default_factory=lambda: _env_int("DIGEST_HOUR_PM", 16))

    @property
    def pricing(self) -> dict:
        return PRICING.get(self.gemini_model, PRICING["gemini-2.5-flash"])


def get_settings() -> Settings:
    return Settings()
