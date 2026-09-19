"""Reads a company's public Workday CXS job-posting API -- the same JSON
endpoint a Workday-hosted careers site's own frontend calls to render its
job list (POST .../wday/cxs/{tenant}/{site}/jobs, no auth, no API key).
Same category of source as the Greenhouse/Lever/Ashby/Workable collectors
in ats_boards.py: a company's own public data about its own postings, not
scraping, and unrelated to LinkedIn/Indeed's terms.

This exists because briefing.txt Part G's starter target list turned out
to be mostly on Workday rather than the four boards ats_boards.py
supports -- see targets.yaml's header and docs/adr/ADR-001 for what was
checked and found.

CAVEAT, read before trusting a target blindly: this collector is built
from Workday's CXS API shape as documented across many public sources (a
long-standing, widely used pattern), but it could NOT be verified against
a live Workday tenant from the sandbox this was built in -- outbound
requests to *.myworkdayjobs.com were blocked by that environment's network
egress policy (both `curl` and WebFetch returned EGRESS_BLOCKED). Treat a
new target's first real run as the actual verification step: if the shape
is off, the error goes to logs and the circuit breaker isolates that one
target without affecting anything else (hard rule 5) -- fix the parsing
here once you see a real response.
"""
from __future__ import annotations

import requests

from .ats_boards import load_targets

_TIMEOUT_SECONDS = 15
_USER_AGENT = "Mozilla/5.0 (compatible; TommyJobAlertBot/1.0; personal use)"
_PAGE_SIZE = 20
_MAX_PAGES_PER_TARGET = 10  # caps one company at 200 postings/run


class WorkdayError(Exception):
    pass


def _cxs_url(tenant: str, wd_host: str, site: str) -> str:
    return f"https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"


def _careers_url(tenant: str, wd_host: str, site: str, external_path: str) -> str:
    path = external_path if external_path.startswith("/") else f"/{external_path}"
    return f"https://{tenant}.{wd_host}.myworkdayjobs.com/{site}{path}"


def _fetch_page(tenant: str, wd_host: str, site: str, offset: int) -> dict:
    resp = requests.post(
        _cxs_url(tenant, wd_host, site),
        json={"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""},
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
        timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_workday_jobs(company: str, tenant: str, wd_host: str, site: str) -> list[dict]:
    postings: list[dict] = []
    offset = 0
    for _ in range(_MAX_PAGES_PER_TARGET):
        data = _fetch_page(tenant, wd_host, site, offset)
        job_postings = data.get("jobPostings", [])
        if not job_postings:
            break
        for job in job_postings:
            external_path = job.get("externalPath", "")
            postings.append({
                "title": job.get("title", ""),
                "company": company,
                "location": job.get("locationsText"),
                "url": _careers_url(tenant, wd_host, site, external_path) if external_path else None,
                "salary_text": None,
                # Workday's own field is a relative human string ("Posted 3
                # Days Ago"), not a timestamp -- stored as-is, same as any
                # other free-text posted_at value in this pipeline.
                "posted_at": job.get("postedOn"),
                "source": "workday",
                "source_id": external_path or job.get("jobPostingId") or job.get("title"),
            })
        offset += _PAGE_SIZE
        if offset >= data.get("total", 0):
            break
    return postings


def collect_from_workday(targets_path: str, logger=None) -> list[dict]:
    """Fetch all board_type: workday targets. Raises WorkdayError only if
    every target failed (signals the API shape itself may have changed)."""
    targets = [t for t in load_targets(targets_path) if t.get("board_type") == "workday"]
    if not targets:
        return []

    postings: list[dict] = []
    errors: list[str] = []
    for target in targets:
        company = target["company"]
        try:
            postings.extend(fetch_workday_jobs(company, target["tenant"], target["wd_host"], target["site"]))
        except Exception as exc:  # noqa: BLE001 -- one bad target must not sink the whole run
            errors.append(f"{company}: {exc}")
            if logger is not None:
                logger.warning(f"workday failed for {company}: {exc}")

    if errors and not postings and len(errors) == len(targets):
        raise WorkdayError(f"all workday targets failed: {'; '.join(errors)}")

    return postings
