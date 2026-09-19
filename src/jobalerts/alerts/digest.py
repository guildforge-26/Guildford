"""Builds the twice-daily digest and saves it as a Gmail DRAFT (never sent).

Per hard rule 2 ("never send my personal details... never submit or
message on my behalf") and the spec's explicit instruction, this only ever
creates a draft addressed to Tommy so he reviews before anything goes out.
"""
from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText


# Point caps from briefing.txt Part H, for readable "x/max" display only --
# the model computes and returns the actual score, this is just formatting.
_PART_MAX_POINTS = {
    "requirements_match": 35, "track_level_fit": 15, "industry_fit": 10, "location": 10,
    "compensation": 10, "access": 10, "timing_competition": 10, "ai_bonus": 5,
}


def _format_score_entry(row) -> str:
    breakdown = json.loads(row["breakdown_json"] or "{}")
    facts = json.loads(row["matching_facts_json"] or "[]")
    gaps = json.loads(row["top_gaps_json"] or "[]")
    breakdown_lines = "\n".join(
        f"    - {name}: {value}/{_PART_MAX_POINTS.get(name, '?')}"
        for name, value in breakdown.items()
    )
    gap_lines = "\n".join(
        f"    - {g.get('gap', g)}" + (f" (fix: {g['how_to_address']})" if isinstance(g, dict) and g.get("how_to_address") else "")
        for g in gaps
    )
    return (
        f"### {row['title']} at {row['company']} ({row['location'] or 'location n/a'})\n"
        f"Score: {row['total_score']}/100  |  Tier: {row['tier']}  |  Track: {row['track']}"
        f"{' (unverified -- thin posting text)' if not row['verified'] else ''}\n"
        f"Link: {row['canonical_url'] or ''}\n\n"
        f"Breakdown:\n{breakdown_lines}\n\n"
        f"Matching facts: {'; '.join(facts)}\n"
        f"Gaps:\n{gap_lines}\n"
        f"Resume version: {row['resume_version']}\n"
        f"Warm angle: {row['warm_angle']}\n"
        f"Next action: {row['next_action']}\n"
    )


def build_digest_body(*, b_tier_rows: list, a_tier_rows_yesterday: list, followups_due: list, slot: str) -> str:
    parts = [f"# Job digest -- {slot.upper()}\n"]

    if followups_due:
        parts.append("## Follow-ups due (5+ business days since applying)\n")
        for app in followups_due:
            parts.append(f"- {app['role']} at {app['company']} -- applied {app['date_applied']}, status: {app['status']}")
        parts.append("")

    parts.append("## Yesterday's A-tier postings (score >= 80)\n")
    if a_tier_rows_yesterday:
        for row in a_tier_rows_yesterday:
            parts.append(_format_score_entry(row))
    else:
        parts.append("(none)\n")

    parts.append("## B-tier postings (score 65-79)\n")
    if b_tier_rows:
        for row in b_tier_rows:
            parts.append(_format_score_entry(row))
    else:
        parts.append("(none)\n")

    return "\n".join(parts)


def create_digest_draft(service, *, to_email: str, subject: str, body: str) -> str:
    message = MIMEText(body)
    message["to"] = to_email
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]
