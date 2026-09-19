"""Appends every alert of the day to alerts/YYYY-MM-DD.md."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def append_alert_markdown(alerts_dir: Path, when: datetime, entry: dict) -> None:
    alerts_dir.mkdir(parents=True, exist_ok=True)
    path = alerts_dir / f"{when.strftime('%Y-%m-%d')}.md"
    is_new = not path.exists()
    with open(path, "a", encoding="utf-8") as fh:
        if is_new:
            fh.write(f"# Job alerts — {when.strftime('%Y-%m-%d')}\n\n")
        fh.write(
            f"- **{entry['total_score']}** [{entry['tier']}/{entry['track']}] "
            f"{entry['title']} at {entry['company']} ({entry.get('location') or 'n/a'}) "
            f"— {entry.get('url') or 'no link'} ({when.strftime('%H:%M')})\n"
        )
