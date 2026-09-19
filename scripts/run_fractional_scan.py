#!/usr/bin/env python3
"""Cron entry point: once a day, ask the model to review the day's collected
postings and flag companies that seem to need a part-time CFO/COO even
though they posted a full-time role for a related position.

    30 4 * * * /path/to/venv/bin/python /path/to/scripts/run_fractional_scan.py >> logs/cron.log 2>&1
"""
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import anthropic  # noqa: E402

from jobalerts import db as dbmod  # noqa: E402
from jobalerts import timeutil  # noqa: E402
from jobalerts.alerts.ntfy import send_ntfy  # noqa: E402
from jobalerts.config import get_settings  # noqa: E402
from jobalerts.guardrails import StopRequested, check_stop  # noqa: E402
from jobalerts.logging_utils import get_run_logger, log_fields  # noqa: E402
from jobalerts.scoring import ScoringError, scan_for_fractional_leads  # noqa: E402


def main() -> int:
    settings = get_settings()
    run_id = f"fractional_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger = get_run_logger("jobalerts.fractional_scan", run_id, settings.logs_dir / f"run-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log")

    try:
        check_stop(settings)
    except StopRequested as exc:
        logger.warning(str(exc), extra=log_fields(event="stop_file_present"))
        return 0

    now_local = datetime.now(ZoneInfo(settings.timezone))
    today_str = now_local.strftime("%Y-%m-%d")

    with dbmod.connect(settings) as conn:
        dbmod.start_run(conn, run_id, kind="fractional_scan")

        if dbmod.has_fractional_scan_run(conn, today_str):
            logger.info("fractional scan already ran today, skipping", extra=log_fields(event="already_ran"))
            dbmod.finish_run(conn, run_id, "success", {"skipped": True}, 0.0, [])
            return 0

        start = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        end = datetime.now(timezone.utc).isoformat()
        postings = dbmod.postings_collected_between(conn, start, end)

        if not postings:
            logger.info("no postings collected in the last 24h, nothing to scan", extra=log_fields(event="no_postings"))
            dbmod.record_fractional_scan(conn, today_str, [])
            dbmod.finish_run(conn, run_id, "success", {"postings_reviewed": 0}, 0.0, [])
            return 0

        if not settings.briefing_path.exists() or not settings.anthropic_api_key:
            logger.error("briefing.txt or ANTHROPIC_API_KEY missing, skipping fractional scan", extra=log_fields(event="missing_prereqs"))
            dbmod.finish_run(conn, run_id, "failed", {"postings_reviewed": len(postings)}, 0.0, ["missing_prereqs"])
            return 1

        briefing_text = settings.briefing_path.read_text(encoding="utf-8")
        summary = "\n\n".join(
            f"Title: {p['title']}\nCompany: {p['company']}\nSnippet: {(p['raw_text'] or '')[:500]}"
            for p in postings
        )

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        try:
            result = scan_for_fractional_leads(client, settings.claude_model, settings.pricing, briefing_text, summary)
        except ScoringError as exc:
            logger.error(f"fractional scan failed: {exc}", extra=log_fields(event="scan_failed"))
            dbmod.finish_run(conn, run_id, "failed", {"postings_reviewed": len(postings)}, 0.0, [str(exc)])
            return 1

        dbmod.record_spend(conn, run_id, None, now_local.strftime("%Y-%m-%d"), now_local.strftime("%Y-%m"), result.cost_usd)
        dbmod.record_fractional_scan(conn, today_str, result.flagged)
        dbmod.finish_run(conn, run_id, "success", {"postings_reviewed": len(postings), "flagged": len(result.flagged)}, result.cost_usd, [])

        logger.info(f"fractional scan flagged {len(result.flagged)} companies", extra=log_fields(event="scan_complete", flagged=len(result.flagged), cost_usd=result.cost_usd))

        if result.flagged and settings.ntfy_topic:
            names = ", ".join(f["company"] for f in result.flagged[:5])
            try:
                send_ntfy(settings.ntfy_topic, title="Fractional CFO/COO leads found",
                          message=f"{len(result.flagged)} companies flagged: {names}", priority="default")
            except Exception as exc:  # noqa: BLE001 - a failed push must not crash the run
                logger.error(f"ntfy send failed: {exc}", extra=log_fields(event="ntfy_failed"))

        return 0


if __name__ == "__main__":
    sys.exit(main())
