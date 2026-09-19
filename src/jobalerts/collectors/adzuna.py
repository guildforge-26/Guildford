"""Adzuna job search API (Canada endpoint). Public, documented, keyed API --
not scraping. Docs: https://developer.adzuna.com/

Runs one query per track using a representative OR-joined phrase built from
config/tracks.yaml, once for Calgary and once nationwide-remote, and merges
results. Adzuna's free tier paginates at 50 results/page; this collector
only reads page 1 per query to keep call volume predictable -- revisit if
a track is consistently missing postings.
"""
from __future__ import annotations

import requests

_TIMEOUT_SECONDS = 15
_BASE_URL = "https://api.adzuna.com/v1/api/jobs/ca/search/1"


def _build_query_terms(tracks_config: dict) -> list[str]:
    terms = []
    for track in tracks_config.get("tracks", []):
        keywords = track.get("title_keywords", [])
        if keywords:
            # Adzuna's `what_or` param takes space-separated terms, OR'd together.
            terms.append(" ".join(k.replace(" ", "_") for k in keywords[:6]))
    return terms


def _fetch_page(app_id: str, app_key: str, what_or: str, where: str | None) -> list[dict]:
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what_or": what_or,
        "results_per_page": 50,
        "content-type": "application/json",
    }
    if where:
        params["where"] = where
    resp = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json().get("results", [])


def _salary_text(job: dict) -> str | None:
    lo, hi = job.get("salary_min"), job.get("salary_max")
    if not lo and not hi:
        return None
    if lo and hi and lo != hi:
        return f"${lo:,.0f} - ${hi:,.0f}"
    return f"${(lo or hi):,.0f}"


def collect_from_adzuna(app_id: str, app_key: str, tracks_config: dict) -> list[dict]:
    if not app_id or not app_key:
        return []

    postings: list[dict] = []
    seen_ids: set[str] = set()
    for what_or in _build_query_terms(tracks_config):
        for where in ("Calgary", None):
            for job in _fetch_page(app_id, app_key, what_or, where):
                job_id = str(job.get("id"))
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                postings.append({
                    "title": job.get("title", ""),
                    "company": (job.get("company") or {}).get("display_name", "Unknown"),
                    "location": (job.get("location") or {}).get("display_name"),
                    "url": job.get("redirect_url"),
                    "salary_text": _salary_text(job),
                    "posted_at": job.get("created"),
                    "source": "adzuna",
                    "source_id": job_id,
                })
    return postings
