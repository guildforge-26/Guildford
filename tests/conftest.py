import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from jobalerts.config import Settings  # noqa: E402
from jobalerts import db as dbmod  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(
        base_dir=REPO_ROOT,
        briefing_path=tmp_path / "briefing.txt",
        targets_path=REPO_ROOT / "targets.yaml",
        db_path=tmp_path / "jobs.db",
        tracks_config_path=REPO_ROOT / "config" / "tracks.yaml",
        logs_dir=tmp_path / "logs",
        alerts_dir=tmp_path / "alerts",
        lock_path=tmp_path / "pipeline.lock",
        stop_path=tmp_path / "STOP",
        ntfy_topic="",
        anthropic_api_key="",
        max_model_calls_per_run=5,
        max_retries_per_source=2,
        run_timeout_seconds=1200,
        circuit_breaker_failure_threshold=3,
        circuit_breaker_cooldown_hours=24,
        daily_spend_cap_usd=2.0,
        monthly_spend_cap_usd=30.0,
    )


@pytest.fixture
def conn(settings):
    connection = dbmod.get_connection(settings)
    dbmod.init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def tracks_config():
    from jobalerts.prefilter import load_tracks_config
    load_tracks_config.cache_clear()
    return load_tracks_config(str(REPO_ROOT / "config" / "tracks.yaml"))
