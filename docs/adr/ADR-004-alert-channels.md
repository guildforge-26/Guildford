# ADR-004: Alert channels

## Status
Accepted

## Context
The spec asks for near-real-time alerts on strong matches (score >= 80,
or >= 70 for Track 2 fractional/interim CFO/COO), a twice-daily digest of
everything else worth a look, and a durable daily record -- while never
sending anything on Tommy's behalf (hard rule 2).

## Decision

**Immediate: ntfy.sh push.** Free, no account required, a private topic
name acts as the shared secret (`NTFY_TOPIC`). Chosen over email-for-
immediate-alerts because push notifications actually interrupt Tommy in
the way "apply within hours" urgency requires; email digests are batched
by design. `alerts/ntfy.py`.

**Twice daily: Gmail draft, not a sent email.** `run_digest.py` runs
hourly and only acts at the configured AM/PM Mountain-time hour
(`DIGEST_HOUR_AM` / `DIGEST_HOUR_PM`), checked in *local* time inside the
script rather than relied on from cron's own timezone handling, so it's
correct across DST without needing `CRON_TZ` support. It creates a Gmail
**draft** addressed to Tommy's own inbox (`gmail.compose` scope) listing
B-tier postings and yesterday's A-tier postings with the full score
breakdown, plus follow-ups due. Tommy reviews and can turn it into a sent
email himself, or not -- the system never calls Gmail's send endpoint.
`alerts/digest.py`.

**Durable record: `alerts/YYYY-MM-DD.md`.** Every alert (immediate or
digest-tier) is appended to a local markdown file the moment it's decided,
independent of whether the push or draft-creation step itself succeeds --
so there's always a plain-text record of what was flagged and when, even
if ntfy or Gmail are temporarily down. `alerts/daily_log.py`.

**Idempotency:** the `alerts` table's UNIQUE(posting_id, channel,
alert_type) constraint means a re-run can't double-push or double-append;
`db.py::record_alert` returns `False` (and the caller skips the actual
send) if that alert was already recorded.

## Consequences
- Digest timing correctness depends on the hourly cron job actually
  firing every hour; if cron itself is down, no digest fires, but the
  next successful hourly run's local-time check still catches the correct
  slot (it doesn't try to "catch up" missed slots from earlier in the
  day -- once an hour's window passes, that slot is simply skipped for
  today, which is an acceptable trade-off for a personal tool over the
  complexity of backfill logic).
- ntfy.sh is a third-party free service; a private topic name is not a
  strong secret (nothing stops someone who guesses/finds the topic from
  subscribing to it), which is an acceptable risk for job-posting
  metadata but is documented here rather than left implicit.
