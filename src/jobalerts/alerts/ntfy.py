"""Push notifications via ntfy.sh -- free, no account needed, topic acts as
the shared secret. https://docs.ntfy.sh/publish/
"""
from __future__ import annotations

import requests

_TIMEOUT_SECONDS = 10


def send_ntfy(topic: str, *, title: str, message: str, priority: str = "default", click: str | None = None) -> None:
    if not topic:
        raise ValueError("NTFY_TOPIC is not configured")
    headers = {"Title": title.encode("utf-8"), "Priority": priority, "Tags": "briefcase"}
    if click:
        headers["Click"] = click.encode("utf-8")
    resp = requests.post(f"https://ntfy.sh/{topic}", data=message.encode("utf-8"), headers=headers, timeout=_TIMEOUT_SECONDS)
    resp.raise_for_status()


def send_ntfy_alert(topic: str, *, title: str, company: str, score: int, url: str | None, priority: str = "default") -> None:
    send_ntfy(
        topic,
        title=f"Job alert: {score}/100",
        message=f"{title} at {company} — score {score}/100",
        priority=priority,
        click=url,
    )
