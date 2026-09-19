"""Reads LinkedIn/Indeed job-alert emails via the Gmail API (read-only scope)
and extracts postings. This is the spec's Source A: it never touches
LinkedIn or Indeed directly, only the emails they send you.

Email HTML templates change without notice and vary by locale/plan, so the
extraction here is a best-effort heuristic (look for anchors linking to a
job-view URL, then guess company/location from the surrounding text lines).
Treat the first few real digests as a check on whether these heuristics
need tuning -- see docs/test_plan.md.
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from .. import db as dbmod
from ..gmail_client import get_gmail_service

_QUERY_SENDERS = (
    "from:jobs-noreply@linkedin.com",
    "from:jobalerts-noreply@linkedin.com",
    "from:alert@indeed.com",
    "from:indeedapply@indeed.com",
)


def _build_query(since: datetime) -> str:
    since_epoch = int(since.timestamp())
    senders = " OR ".join(_QUERY_SENDERS)
    return f"({senders}) after:{since_epoch}"


def _get_header(payload: dict, name: str) -> str:
    for h in payload.get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _get_html_body(payload: dict) -> Optional[str]:
    if payload.get("mimeType") == "text/html" and "data" in payload.get("body", {}):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        html = _get_html_body(part)
        if html:
            return html
    return None


def _guess_company_location(lines: list[str], title: str) -> tuple[str, str]:
    try:
        idx = lines.index(title)
    except ValueError:
        idx = -1
    company = lines[idx + 1] if idx != -1 and idx + 1 < len(lines) else "Unknown (verify from email)"
    location = lines[idx + 2] if idx != -1 and idx + 2 < len(lines) else ""
    return company, location


def _parse_linkedin_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    postings, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/jobs/view/" not in href or href in seen:
            continue
        seen.add(href)
        title = a.get_text(strip=True)
        if not title:
            continue
        container = a.find_parent(["td", "div", "table"]) or a.parent
        lines = [l.strip() for l in container.get_text(separator="\n").split("\n") if l.strip()]
        company, location = _guess_company_location(lines, title)
        postings.append({
            "title": title, "company": company, "location": location,
            "url": href, "salary_text": None, "posted_at": None,
            "source": "email_linkedin", "source_id": href,
        })
    return postings


def _parse_indeed_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    postings, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ("indeed.com/rc/clk" not in href and "viewjob" not in href) or href in seen:
            continue
        seen.add(href)
        title = a.get_text(strip=True)
        if not title:
            continue
        container = a.find_parent(["td", "div", "table"]) or a.parent
        lines = [l.strip() for l in container.get_text(separator="\n").split("\n") if l.strip()]
        company, location = _guess_company_location(lines, title)
        postings.append({
            "title": title, "company": company, "location": location,
            "url": href, "salary_text": None, "posted_at": None,
            "source": "email_indeed", "source_id": href,
        })
    return postings


def _extract_postings_from_message(service, msg_id: str) -> tuple[list[dict], str]:
    msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = msg["payload"]
    sender = _get_header(payload, "From").lower()
    html = _get_html_body(payload)
    if not html:
        return [], "unknown"
    if "linkedin.com" in sender:
        return _parse_linkedin_html(html), "linkedin"
    if "indeed.com" in sender:
        return _parse_indeed_html(html), "indeed"
    return [], "unknown"


def collect_from_gmail(settings, conn, since: datetime) -> list[dict]:
    service = get_gmail_service(settings)
    query = _build_query(since)

    message_ids: list[str] = []
    page_token = None
    while True:
        resp = service.users().messages().list(userId="me", q=query, pageToken=page_token, maxResults=50).execute()
        message_ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    all_postings: list[dict] = []
    for msg_id in message_ids:
        if dbmod.is_email_processed(conn, msg_id):
            continue
        postings, email_source = _extract_postings_from_message(service, msg_id)
        all_postings.extend(postings)
        dbmod.mark_email_processed(conn, msg_id, email_source)

    return all_postings
