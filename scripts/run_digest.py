#!/usr/bin/env python3
"""Cron entry point: run hourly, only actually drafts a digest at the
configured AM/PM Mountain-time hours (DST-safe -- the schedule decision is
made in local time inside this script, not by cron's own clock/timezone).

    0 * * * * /path/to/venv/bin/python /path/to/scripts/run_digest.py >> logs/cron.log 2>&1
"""
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobalerts import db as dbmod  # noqa: E402
from jobalerts import timeutil  # noqa: E402
from jobalerts.alerts.digest import build_digest_body, create_digest_draft  # noqa: E402
from jobalerts.config import get_settings  # noqa: E402
from jobalerts.gmail_client import get_gmail_service  # noqa: E402
from jobalerts.guardrails import StopRequested, check_stop  # noqa: E402
from jobalerts.logging_utils import get_run_logger, log_fields  # noqa: E402


def main() -> int:
    settings = get_settings()
    run_id = f"digest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger = get_run_logger("jobalerts.digest", run_id, settings.logs_dir / f"run-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log")

    try:
        check_stop(settings)
    except StopRequested as exc:
        logger.warning(str(exc), extra=log_fields(event="stop_file_present"))
        return 0

    now_local = datetime.now(ZoneInfo(settings.timezone))
    if now_local.hour == settings.digest_hour_am:
        slot = "am"
    elif now_local.hour == settings.digest_hour_pm:
        slot = "pm"
    else:
        logger.info(f"not a digest hour ({now_local.hour}h local Mountain time), nothing to do", extra=log_fields(event="not_digest_hour"))
        return 0

    today_str = now_local.strftime("%Y-%m-%d")

    with dbmod.connect(settings) as conn:
        if dbmod.has_digest_sent(conn, today_str, slot):
            logger.info(f"{slot} digest already sent today, skipping", extra=log_fields(event="digest_already_sent", slot=slot))
            return 0

        since_b = timeutil.sqlite_utc(datetime.now(timezone.utc) - timedelta(hours=24))
        recent = dbmod.scores_with_postings_since(conn, since_b)
        b_tier_rows = [r for r in recent if r["tier"] == "B"]

        yesterday_local = now_local.date() - timedelta(days=1)
        y_start_utc = timeutil.sqlite_utc(timeutil.local_midnight_utc(yesterday_local, settings.timezone))
        today_start_utc = timeutil.sqlite_utc(timeutil.local_midnight_utc(now_local.date(), settings.timezone))
        a_tier_all = dbmod.scores_with_postings_since(conn, y_start_utc)
        a_tier_rows = [r for r in a_tier_all if r["tier"] == "A" and r["scored_at"] < today_start_utc]

        followups_due = dbmod.applications_due_followup(conn, date.today().isoformat())

        body = build_digest_body(b_tier_rows=b_tier_rows, a_tier_rows_yesterday=a_tier_rows, followups_due=followups_due, slot=slot)

        if not settings.digest_to_email:
            logger.warning("DIGEST_TO_EMAIL not set; logging digest body instead of drafting it", extra=log_fields(event="digest_to_email_missing"))
            logger.info(body, extra=log_fields(event="digest_body"))
            dbmod.record_digest_sent(conn, today_str, slot, None)
            return 0

        try:
            service = get_gmail_service(settings)
            draft_id = create_digest_draft(service, to_email=settings.digest_to_email,
                                            subject=f"Job digest {today_str} {slot.upper()}", body=body)
        except Exception as exc:  # noqa: BLE001 - must not crash cron
            logger.error(f"failed to create digest draft: {exc}", extra=log_fields(event="digest_draft_failed"))
            return 1

        dbmod.record_digest_sent(conn, today_str, slot, draft_id)
        logger.info(f"{slot} digest draft created: {draft_id}", extra=log_fields(event="digest_created", draft_id=draft_id))
        return 0


if __name__ == "__main__":
    sys.exit(main())
