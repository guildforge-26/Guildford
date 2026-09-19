"""Canonicalization and dedupe-key computation.

Two postings are the same job if they share a canonical URL, or if they
share the same (company, title, location) after normalization -- this is
what catches the same posting appearing via an email alert AND an ATS board.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACKING_PARAM_PREFIXES = ("utm_", "gh_", "gh_src", "trk", "ref", "src", "lever-source")
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    kept_query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    query = urlencode(sorted(kept_query))
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.lower().strip()
    value = _PUNCT_RE.sub(" ", value)
    value = _WHITESPACE_RE.sub(" ", value)
    return value.strip()


def build_dedupe_key(company: str, title: str, location: str | None) -> str:
    return "|".join([normalize_text(company), normalize_text(title), normalize_text(location or "")])


def compute_posting_id(canonical_url: str | None, dedupe_key: str) -> str:
    basis = f"u:{canonical_url}" if canonical_url else f"d:{dedupe_key}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def build_posting_record(
    *,
    source: str,
    source_id: str | None,
    title: str,
    company: str,
    location: str | None,
    url: str | None,
    salary_text: str | None,
    posted_at: str | None,
    collected_at: str,
    run_id: str,
) -> dict:
    canonical_url = canonicalize_url(url)
    dedupe_key = build_dedupe_key(company, title, location)
    posting_id = compute_posting_id(canonical_url, dedupe_key)
    return {
        "id": posting_id,
        "canonical_url": canonical_url,
        "dedupe_key": dedupe_key,
        "source": source,
        "source_id": source_id,
        "title": title,
        "company": company,
        "location": location,
        "salary_text": salary_text,
        "posted_at": posted_at,
        "collected_at": collected_at,
        "first_run_id": run_id,
    }
