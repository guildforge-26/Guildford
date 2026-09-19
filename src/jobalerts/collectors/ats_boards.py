"""Reads public JSON job-board APIs that Greenhouse, Lever, Ashby and
Workable provide for embedding a company's careers page. These are public,
documented-by-convention endpoints meant for external consumption -- not
scraping, and nothing to do with LinkedIn/Indeed's terms.

targets.yaml lists which companies to check. One bad/renamed slug should
not take down the whole collector run, so per-company failures are caught
and logged; the collector only raises (to trigger the retry/circuit-breaker
machinery in collectors/base.py) if every target of a given board type
failed, which usually means the board_type's API itself is down.
"""
from __future__ import annotations

from typing import Optional

import requests
import yaml

_TIMEOUT_SECONDS = 15
_USER_AGENT = "Mozilla/5.0 (compatible; TommyJobAlertBot/1.0; personal use)"


class BoardTypeUnavailable(Exception):
    pass


def load_targets(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("targets") or []


def _get(url: str) -> dict:
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def _fetch_greenhouse(company: str, slug: str) -> list[dict]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = []
    for job in data.get("jobs", []):
        out.append({
            "title": job.get("title", ""),
            "company": company,
            "location": (job.get("location") or {}).get("name"),
            "url": job.get("absolute_url"),
            "salary_text": None,
            "posted_at": job.get("updated_at"),
            "source": "greenhouse",
            "source_id": str(job.get("id")),
        })
    return out


def _fetch_lever(company: str, slug: str) -> list[dict]:
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for job in data:
        categories = job.get("categories") or {}
        out.append({
            "title": job.get("text", ""),
            "company": company,
            "location": categories.get("location"),
            "url": job.get("hostedUrl"),
            "salary_text": None,
            "posted_at": job.get("createdAt"),
            "source": "lever",
            "source_id": str(job.get("id")),
        })
    return out


def _fetch_ashby(company: str, slug: str) -> list[dict]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for job in data.get("jobs", []):
        out.append({
            "title": job.get("title", ""),
            "company": company,
            "location": job.get("location"),
            "url": job.get("jobUrl") or job.get("applyUrl"),
            "salary_text": None,
            "posted_at": job.get("publishedAt"),
            "source": "ashby",
            "source_id": str(job.get("id")),
        })
    return out


def _fetch_workable(company: str, slug: str) -> list[dict]:
    data = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    out = []
    for job in data.get("jobs", []):
        location = job.get("location") or {}
        location_str = ", ".join(filter(None, [location.get("city"), location.get("region"), location.get("country")]))
        out.append({
            "title": job.get("title", ""),
            "company": company,
            "location": location_str or None,
            "url": job.get("url"),
            "salary_text": None,
            "posted_at": None,
            "source": "workable",
            "source_id": job.get("shortcode"),
        })
    return out


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "workable": _fetch_workable,
}


def collect_from_board_type(board_type: str, targets_path: str, logger=None) -> list[dict]:
    """Fetch all targets of one board_type. Raises BoardTypeUnavailable only if
    every target failed (signals the platform's API itself may be down)."""
    fetcher = _FETCHERS[board_type]
    targets = [t for t in load_targets(targets_path) if t.get("board_type") == board_type]
    if not targets:
        return []

    postings: list[dict] = []
    errors: list[str] = []
    for target in targets:
        company, slug = target["company"], target["slug"]
        try:
            postings.extend(fetcher(company, slug))
        except Exception as exc:  # noqa: BLE001 - one bad company slug must not sink the whole run
            errors.append(f"{company} ({slug}): {exc}")
            if logger is not None:
                logger.warning(f"ats_boards[{board_type}] failed for {company}: {exc}")

    if errors and not postings and len(errors) == len(targets):
        raise BoardTypeUnavailable(f"all {board_type} targets failed: {'; '.join(errors)}")

    return postings
