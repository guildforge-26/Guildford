"""Timestamp helpers that keep Python-side date math consistent with
SQLite's own `datetime('now')` text format (UTC, space-separated, no
offset) so string comparisons in WHERE clauses behave correctly.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def sqlite_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def local_midnight_utc(local_date: date, tz_name: str) -> datetime:
    return datetime.combine(local_date, datetime.min.time(), tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
