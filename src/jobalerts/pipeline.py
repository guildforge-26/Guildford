"""The every-4-hours pipeline: collect -> dedupe -> prefilter -> enrich ->
score -> store -> alert. Every guardrail from the build spec is wired in
here: STOP kill switch, run lock, wall-clock timeout, per-source retries +
circuit breaker, model-call budget, and spend caps.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import anthropic

from . import db as dbmod
from .alerts.daily_log import append_alert_markdown
from .alerts.ntfy import send_ntfy_alert
from .collectors.adzuna import collect_from_adzuna
from .collectors.ats_boards import collect_from_board_type
from .collectors.base import run_collector
from .collectors.gmail_alerts import collect_from_gmail
from .collectors.job_bank import collect_from_job_bank
from .config import Settings, get_settings
from .dedupe import build_posting_record
from .enrich import EnrichmentError, fetch_posting_text
from .guardrails import (
    CircuitBreaker,
    LockHeld,
    ModelCallBudget,
    RunTimer,
    SpendGuard,
    StopRequested,
    TimeoutExceeded,
    check_stop,
    pipeline_lock,
)
from .logging_utils import get_run_logger, log_fields
from .prefilter import load_tracks_config, run_prefilter
from .scoring import ScoringError, score_posting, score_to_db_row

_ESTIMATED_COST_PER_CALL_USD = 0.02  # conservative pre-check ceiling; real cost is logged after each call

_ATS_BOARD_TYPES = ("greenhouse", "lever", "ashby", "workable")


def _new_run_id() -> str:
    return f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"


def _collect_all(settings: Settings, conn, circuit_breaker: CircuitBreaker, logger) -> tuple[list[dict], dict]:
    since = datetime.now(timezone.utc) - timedelta(hours=settings.collect_lookback_hours)
    counts: dict[str, int] = {}
    raw: list[dict] = []

    if settings.gmail_credentials_path.exists():
        postings = run_collector(
            "gmail", lambda: collect_from_gmail(settings, conn, since),
            circuit_breaker=circuit_breaker, max_retries=settings.max_retries_per_source, logger=logger,
        )
    else:
        logger.info("gmail not configured (no credentials file), skipping", extra=log_fields(source="gmail", event="collector_unconfigured"))
        postings = []
    counts["gmail"] = len(postings)
    raw.extend(postings)

    for board_type in _ATS_BOARD_TYPES:
        source = f"ats_{board_type}"
        postings = run_collector(
            source, lambda bt=board_type: collect_from_board_type(bt, str(settings.targets_path), logger=logger),
            circuit_breaker=circuit_breaker, max_retries=settings.max_retries_per_source, logger=logger,
        )
        counts[source] = len(postings)
        raw.extend(postings)

    tracks_config = load_tracks_config(str(settings.tracks_config_path))
    postings = run_collector(
        "adzuna", lambda: collect_from_adzuna(settings.adzuna_app_id, settings.adzuna_app_key, tracks_config),
        circuit_breaker=circuit_breaker, max_retries=settings.max_retries_per_source, logger=logger,
    )
    counts["adzuna"] = len(postings)
    raw.extend(postings)

    postings = run_collector(
        "job_bank", lambda: collect_from_job_bank(settings.job_bank_feed_url, settings.gc_jobs_feed_url, logger=logger),
        circuit_breaker=circuit_breaker, max_retries=settings.max_retries_per_source, logger=logger,
    )
    counts["job_bank"] = len(postings)
    raw.extend(postings)

    return raw, counts


def _store_and_prefilter(settings: Settings, conn, run_id: str, raw_postings: list[dict], tracks_config: dict, logger, counts: dict) -> list[str]:
    """Upserts every raw posting (idempotent) and returns posting_ids that
    are new this run AND passed the cheap prefilter -- these are the only
    ones eligible for enrichment/scoring."""
    to_process: list[str] = []
    collected_at = datetime.now(timezone.utc).isoformat()

    for raw in raw_postings:
        record = build_posting_record(
            source=raw["source"], source_id=raw.get("source_id"), title=raw.get("title", ""),
            company=raw.get("company", "Unknown"), location=raw.get("location"), url=raw.get("url"),
            salary_text=raw.get("salary_text"), posted_at=raw.get("posted_at"),
            collected_at=collected_at, run_id=run_id,
        )
        posting_id, is_new = dbmod.upsert_posting(conn, record)
        if not is_new:
            counts["skipped_duplicate"] = counts.get("skipped_duplicate", 0) + 1
            continue

        if raw.get("raw_text"):
            dbmod.set_posting_enriched(conn, posting_id, raw["raw_text"])

        pf = run_prefilter(
            {**record, "raw_text": raw.get("raw_text")}, tracks_config,
            settings.min_salary_usd, settings.min_monthly_retainer_usd,
        )
        if not pf.passed:
            dbmod.set_posting_status(conn, posting_id, "prefiltered_out", pf.reason)
            counts["prefiltered_out"] = counts.get("prefiltered_out", 0) + 1
            logger.info(f"prefiltered out: {pf.reason}", extra=log_fields(event="prefiltered_out", posting_id=posting_id, reason=pf.reason))
            continue

        to_process.append(posting_id)

    return to_process


def _enrich_all(settings: Settings, conn, posting_ids: list[str], timer: RunTimer, logger, counts: dict) -> None:
    for posting_id in posting_ids:
        timer.check()
        posting = dbmod.get_posting(conn, posting_id)
        if posting["raw_text"]:
            continue  # already enriched from the source payload itself (e.g. gov_ca RSS description)
        if not posting["canonical_url"]:
            continue
        try:
            text = fetch_posting_text(posting["canonical_url"])
            dbmod.set_posting_enriched(conn, posting_id, text)
            counts["enriched"] = counts.get("enriched", 0) + 1
        except EnrichmentError as exc:
            dbmod.set_posting_status(conn, posting_id, "enrich_failed", str(exc))
            counts["enrich_failed"] = counts.get("enrich_failed", 0) + 1
            logger.warning(f"enrichment failed: {exc}", extra=log_fields(event="enrich_failed", posting_id=posting_id))


def _score_all(settings: Settings, conn, run_id: str, posting_ids: list[str], timer: RunTimer, logger, counts: dict, errors: list) -> list[str]:
    scored_ids: list[str] = []

    if not settings.briefing_path.exists():
        logger.error(f"briefing not found at {settings.briefing_path}, skipping scoring this run", extra=log_fields(event="briefing_missing"))
        errors.append("briefing_missing")
        return scored_ids
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY not set, skipping scoring this run", extra=log_fields(event="api_key_missing"))
        errors.append("anthropic_api_key_missing")
        return scored_ids

    briefing_text = settings.briefing_path.read_text(encoding="utf-8")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    call_budget = ModelCallBudget(settings.max_model_calls_per_run)
    spend_guard = SpendGuard(conn, settings)

    for posting_id in posting_ids:
        timer.check()
        if dbmod.has_score(conn, posting_id):
            continue  # already scored in a previous run -- never re-score (cost control + idempotency)

        if not call_budget.can_call():
            logger.warning("model call budget exhausted for this run", extra=log_fields(event="call_budget_exhausted", max_calls=settings.max_model_calls_per_run))
            errors.append("call_budget_exhausted")
            break

        if not spend_guard.can_spend(_ESTIMATED_COST_PER_CALL_USD):
            logger.error("spend cap reached, stopping scoring (collection continues)", extra=log_fields(
                event="spend_cap_reached", daily_spent=spend_guard.daily_spent(), monthly_spent=spend_guard.monthly_spent(),
            ))
            errors.append("spend_cap_reached")
            if settings.ntfy_topic:
                try:
                    send_ntfy_alert(settings.ntfy_topic, title="Spend cap reached", company="Job Alert System",
                                     score=0, url="", priority="high")
                except Exception as exc:  # noqa: BLE001 - alert failure must not crash the run
                    logger.error(f"failed to send spend-cap alert: {exc}")
            break

        posting = dbmod.get_posting(conn, posting_id)
        try:
            result = score_posting(client, settings.claude_model, settings.pricing, briefing_text, dict(posting))
        except ScoringError as exc:
            call_budget.record_call()
            dbmod.set_posting_status(conn, posting_id, "error", str(exc))
            logger.error(f"scoring failed: {exc}", extra=log_fields(event="scoring_failed", posting_id=posting_id))
            errors.append(f"scoring_failed:{posting_id}")
            continue

        call_budget.record_call()
        spend_guard.record(run_id, posting_id, result.cost_usd)
        row = score_to_db_row(result, settings.claude_model)
        dbmod.save_score(conn, posting_id, row, run_id)
        scored_ids.append(posting_id)
        counts["scored"] = counts.get("scored", 0) + 1
        logger.info(
            f"scored {row['total_score']}/100 ({row['tier']}, {row['track']})",
            extra=log_fields(event="scored", posting_id=posting_id, total_score=row["total_score"],
                              tier=row["tier"], track=row["track"], cost_usd=result.cost_usd),
        )

    return scored_ids


def _alert_all(settings: Settings, conn, run_id: str, scored_ids: list[str], logger, counts: dict, errors: list) -> None:
    now_local = datetime.now(ZoneInfo(settings.timezone))
    for posting_id in scored_ids:
        posting = dbmod.get_posting(conn, posting_id)
        score = dbmod.get_score(conn, posting_id)
        immediate_threshold = settings.track2_alert_score if str(score["track"]) == "2" else settings.alert_score_a

        if score["total_score"] >= immediate_threshold:
            alert_type, priority = "immediate_a", "urgent"
        elif score["total_score"] >= settings.alert_score_b_min:
            alert_type, priority = "digest_b", "default"
        else:
            continue

        entry = {
            "title": posting["title"], "company": posting["company"], "location": posting["location"],
            "url": posting["canonical_url"], "total_score": score["total_score"], "tier": score["tier"],
            "track": score["track"],
        }

        if alert_type == "immediate_a" and settings.ntfy_topic:
            if dbmod.record_alert(conn, posting_id, "ntfy", alert_type, run_id):
                try:
                    send_ntfy_alert(settings.ntfy_topic, title=posting["title"], company=posting["company"],
                                     score=score["total_score"], url=posting["canonical_url"], priority=priority)
                except Exception as exc:  # noqa: BLE001 - a failed push must not crash the run
                    logger.error(f"ntfy send failed: {exc}", extra=log_fields(event="ntfy_failed", posting_id=posting_id))
                    errors.append(f"ntfy_failed:{posting_id}")

        if dbmod.record_alert(conn, posting_id, "markdown", alert_type, run_id):
            append_alert_markdown(settings.alerts_dir, now_local, entry)
            counts["alerted"] = counts.get("alerted", 0) + 1


def run_pipeline(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    run_id = _new_run_id()
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = settings.logs_dir / f"run-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    logger = get_run_logger("jobalerts.pipeline", run_id, log_file)

    counts: dict = {}
    errors: list[str] = []

    try:
        check_stop(settings)
    except StopRequested as exc:
        logger.warning(str(exc), extra=log_fields(event="stop_file_present"))
        return {"run_id": run_id, "status": "killed_stop", "counts": counts, "errors": [str(exc)]}

    try:
        with pipeline_lock(settings):
            with dbmod.connect(settings) as conn:
                dbmod.start_run(conn, run_id, kind="pipeline")
                status = "success"
                try:
                    timer = RunTimer(settings.run_timeout_seconds)
                    circuit_breaker = CircuitBreaker(conn, settings)
                    tracks_config = load_tracks_config(str(settings.tracks_config_path))

                    raw_postings, collect_counts = _collect_all(settings, conn, circuit_breaker, logger)
                    counts.update({f"collected_{k}": v for k, v in collect_counts.items()})
                    timer.check()

                    to_process = _store_and_prefilter(settings, conn, run_id, raw_postings, tracks_config, logger, counts)
                    timer.check()

                    _enrich_all(settings, conn, to_process, timer, logger, counts)
                    check_stop(settings)
                    timer.check()

                    scored_ids = _score_all(settings, conn, run_id, to_process, timer, logger, counts, errors)
                    timer.check()

                    _alert_all(settings, conn, run_id, scored_ids, logger, counts, errors)

                except TimeoutExceeded as exc:
                    logger.error(str(exc), extra=log_fields(event="run_timeout"))
                    status, errors = "killed_timeout", errors + [str(exc)]
                except StopRequested as exc:
                    logger.warning(str(exc), extra=log_fields(event="stop_mid_run"))
                    status, errors = "killed_stop", errors + [str(exc)]
                except Exception as exc:  # noqa: BLE001 - top-level safety net, must not crash cron
                    logger.error(f"unexpected pipeline error: {exc}", extra=log_fields(event="unexpected_error"))
                    status, errors = "failed", errors + [str(exc)]
                else:
                    if errors:
                        status = "partial"

                cost_total = dbmod.get_run_spend(conn, run_id)
                dbmod.finish_run(conn, run_id, status, counts, cost_total, errors)
                logger.info("run finished", extra=log_fields(event="run_finished", status=status, counts=counts, cost_usd=cost_total))
                return {"run_id": run_id, "status": status, "counts": counts, "errors": errors, "cost_usd": cost_total}
    except LockHeld as exc:
        logger.warning(str(exc), extra=log_fields(event="lock_held"))
        return {"run_id": run_id, "status": "skipped_lock_held", "counts": counts, "errors": [str(exc)]}
