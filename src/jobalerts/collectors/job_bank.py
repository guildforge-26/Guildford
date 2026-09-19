"""Government of Canada / Job Bank / municipal postings.

Job Bank Canada publishes labour-market OPEN DATA (bulk statistical
datasets) but, as far as could be verified while this scaffold was built,
no documented real-time public search API for individual job postings.
Rather than fabricate an endpoint, this collector is off by default: set
JOB_BANK_FEED_URL / GC_JOBS_FEED_URL in .env once you've found and confirmed
a real feed (an RSS/XML/JSON feed some municipalities and GC job sites do
publish), and this starts using it. Until then it logs that it's
unconfigured and returns no postings -- never an error (hard rule 5).

See docs/adr/ADR-001-sources-and-no-scraping.md for the reasoning.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

_TIMEOUT_SECONDS = 15


def _fetch_rss(url: str) -> list[dict]:
    resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    postings = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = (item.findtext("description") or "").strip()
        if not title or not link:
            continue
        postings.append({
            "title": title,
            "company": "Government of Canada / Municipal",
            "location": None,
            "url": link,
            "salary_text": None,
            "posted_at": item.findtext("pubDate"),
            "source": "gov_ca",
            "source_id": link,
            "raw_text": description or None,
        })
    return postings


def collect_from_job_bank(job_bank_feed_url: str, gc_jobs_feed_url: str, logger=None) -> list[dict]:
    urls = [u for u in (job_bank_feed_url, gc_jobs_feed_url) if u]
    if not urls:
        if logger is not None:
            logger.info("job_bank/gov_ca feed URLs not configured, skipping source")
        return []

    postings: list[dict] = []
    for url in urls:
        postings.extend(_fetch_rss(url))
    return postings
