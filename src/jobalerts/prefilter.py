"""Cheap, pre-Claude-call filtering: geography, track-title match, salary floor,
and a placeholder disqualifying-requirement check. Every function here is
pure and dependency-free so it's trivially unit-testable without a briefing
file, an API key, or a database.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .dedupe import normalize_text

# Curated Canada/US geography markers. Deliberately allow-list based: a
# posting only fails geography if it names a location and that location
# matches none of these. An empty/missing location is passed through
# (the cheap filter should not silently drop postings ATS boards list
# without a location field) and the real hard-filter check happens again
# during scoring, using the full posting text.
_CA_PROVINCES = {
    "ab", "alberta", "bc", "british columbia", "mb", "manitoba", "nb", "new brunswick",
    "nl", "newfoundland", "ns", "nova scotia", "nt", "northwest territories", "nu", "nunavut",
    "on", "ontario", "pe", "prince edward island", "qc", "quebec", "québec", "sk", "saskatchewan",
    "yt", "yukon", "canada",
}
_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "united states", "usa", "u s a", "u s",
}
_ALLOWED_GEO_MARKERS = _CA_PROVINCES | _US_STATES | {"remote"}


@dataclass
class PrefilterResult:
    passed: bool
    reason: Optional[str] = None


@lru_cache(maxsize=1)
def load_tracks_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def is_allowed_geography(location: Optional[str]) -> bool:
    if not location or not location.strip():
        return True
    # Word-boundary match, not substring: a plain `marker in norm` check lets
    # 2-letter province/state codes false-positive inside unrelated words
    # (e.g. "on" -- Ontario -- matching inside "London").
    tokens = set(normalize_text(location).split())
    for marker in _ALLOWED_GEO_MARKERS:
        if " " in marker:
            if marker in normalize_text(location):
                return True
        elif marker in tokens:
            return True
    return False


def matched_track(title: str, tracks_config: dict) -> Optional[str]:
    norm_title = normalize_text(title)
    for exclude in tracks_config.get("title_exclude_keywords", []):
        if normalize_text(exclude) in norm_title:
            return None
    for track in tracks_config.get("tracks", []):
        for keyword in track.get("title_keywords", []):
            if normalize_text(keyword) in norm_title:
                return track["id"]
    return None


_HOURLY_RE = re.compile(r"\$?\s?(\d+(?:\.\d+)?)\s?(?:/\s?hr|/\s?hour|per\s+hour)", re.I)
_MONTHLY_RE = re.compile(r"\$?\s?(\d+(?:\.\d+)?)\s?(?:/\s?mo\b|/\s?month|per\s+month|a\s+month|monthly)", re.I)
_K_SUFFIX_RE = re.compile(r"(\d+(?:\.\d+)?)\s?[kK]\b")
_FULL_NUMBER_RE = re.compile(r"\b(\d{4,7})\b")


def parse_salary_figures(salary_text: Optional[str]) -> Optional[tuple[float, float]]:
    """Best-effort: returns (max_annual_equivalent_usd, max_monthly_equivalent_usd),
    or None if no figure could be parsed (an unparseable/missing salary is
    not a reason to drop a posting at this stage). Briefing.txt Part B sets
    two different floors -- $100k/year full-time, $5k/month fractional or
    interim -- so both units are derived from whatever's actually stated."""
    if not salary_text:
        return None
    text = salary_text.replace(",", "")

    monthly = _MONTHLY_RE.search(text)
    if monthly:
        amount = float(monthly.group(1))
        return (amount * 12, amount)

    hourly = _HOURLY_RE.search(text)
    if hourly:
        annual = float(hourly.group(1)) * 2080  # approx. full-time annualized hours
        return (annual, annual / 12)

    figures = [float(m) * 1000 for m in _K_SUFFIX_RE.findall(text)]
    figures += [float(m) for m in _FULL_NUMBER_RE.findall(text)]
    if not figures:
        return None
    annual = max(figures)
    return (annual, annual / 12)


def salary_meets_minimum(
    salary_text: Optional[str], min_annual_usd: int, min_monthly_usd: int, is_fractional: bool = False
) -> bool:
    """is_fractional=True applies the monthly retainer floor (Track 2) instead
    of the full-time annual floor."""
    parsed = parse_salary_figures(salary_text)
    if parsed is None:
        return True  # unknown salary is not filtered out here
    annual_equivalent, monthly_equivalent = parsed
    if is_fractional:
        return monthly_equivalent >= min_monthly_usd
    return annual_equivalent >= min_annual_usd


def disqualifying_requirement(text: Optional[str], disqualifying_phrases: list[str]) -> Optional[str]:
    if not text:
        return None
    norm = normalize_text(text)
    for phrase in disqualifying_phrases:
        if normalize_text(phrase) in norm:
            return phrase
    return None


def run_prefilter(
    posting: dict, tracks_config: dict, min_salary_usd: int, min_monthly_retainer_usd: int = 5_000
) -> PrefilterResult:
    """posting requires at least: title, location, salary_text (raw_text optional)."""
    if not is_allowed_geography(posting.get("location")):
        return PrefilterResult(False, f"geography_not_ca_us: {posting.get('location')!r}")

    track = matched_track(posting.get("title", ""), tracks_config)
    if track is None:
        return PrefilterResult(False, f"title_no_track_match: {posting.get('title')!r}")

    is_fractional = track == "2"  # Track 2: fractional/interim CFO/COO -- monthly retainer floor, not annual
    if not salary_meets_minimum(posting.get("salary_text"), min_salary_usd, min_monthly_retainer_usd, is_fractional):
        reason = "retainer_below_minimum" if is_fractional else "salary_below_minimum"
        return PrefilterResult(False, f"{reason}: {posting.get('salary_text')!r}")

    disqualifiers = tracks_config.get("hard_filters", {}).get("disqualifying_phrases", [])
    haystack = " ".join(filter(None, [posting.get("title"), posting.get("raw_text")]))
    hit = disqualifying_requirement(haystack, disqualifiers)
    if hit:
        return PrefilterResult(False, f"disqualifying_requirement: {hit!r}")

    return PrefilterResult(True, None)
