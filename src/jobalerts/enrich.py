"""Fetch full posting text from a link when possible.

Best-effort by design: enrichment failure is logged and the posting is
still scored on title/company/location/salary alone rather than crashing
the run (hard rule #5).
"""
from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

_USER_AGENT = "Mozilla/5.0 (compatible; TommyJobAlertBot/1.0; personal use, not a scraper of LinkedIn/Indeed)"
_MAX_CHARS = 12_000
_TIMEOUT_SECONDS = 15


class EnrichmentError(Exception):
    pass


def fetch_posting_text(url: str) -> str:
    try:
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise EnrichmentError(f"fetch failed for {url}: {exc}") from exc

    soup = BeautifulSoup(resp.text, "lxml")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()

    if not text:
        raise EnrichmentError(f"no extractable text at {url}")

    return text[:_MAX_CHARS]
