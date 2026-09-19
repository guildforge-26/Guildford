#!/usr/bin/env python3
"""Estimates scoring call volume per run and per day BEFORE you turn on the
schedule, and checks it against Gemini's free-tier rate limit.

Scoring itself is $0/call on the free tier (see
docs/adr/ADR-006-scoring-model-gemini-free-tier.md), so there's no dollar
cost to estimate anymore. The real pre-launch question is different: will
this schedule's call volume fit inside the free tier's requests-per-day
quota? Google's published free-tier RPD numbers for gemini-2.5-flash have
varied across sources and over time, so this defaults to a conservative
assumption you should adjust to whatever ai.google.dev/gemini-api/docs/rate-limits
shows for your model on the day you read it.

Usage:
    python scripts/estimate_cost.py
    python scripts/estimate_cost.py --postings-per-run 8 --free-tier-rpd 1000
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobalerts.config import get_settings  # noqa: E402

RUNS_PER_DAY = 6  # every 4 hours


def estimate(postings_per_run: float, free_tier_rpd: int) -> dict:
    settings = get_settings()
    calls_per_run = min(postings_per_run, settings.max_model_calls_per_run)
    calls_per_day = calls_per_run * RUNS_PER_DAY

    return {
        "model": settings.gemini_model,
        "calls_per_run": calls_per_run,
        "max_calls_per_run_setting": settings.max_model_calls_per_run,
        "calls_per_day": calls_per_day,
        "free_tier_rpd": free_tier_rpd,
        "headroom_pct": (1 - calls_per_day / free_tier_rpd) * 100 if free_tier_rpd else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postings-per-run", type=float, default=5.0,
                         help="Average NEW postings scored per 4-hour run after dedupe/prefilter (default: 5)")
    parser.add_argument("--free-tier-rpd", type=int, default=250,
                         help="Your model's free-tier requests-per-day limit -- check "
                              "ai.google.dev/gemini-api/docs/rate-limits and adjust this (default: 250, "
                              "a conservative figure for gemini-2.5-flash as of when this was written)")
    args = parser.parse_args()

    result = estimate(args.postings_per_run, args.free_tier_rpd)

    print(f"Model: {result['model']} (free tier, $0/call)")
    print(f"Assumptions: {args.postings_per_run:.1f} postings scored per run, {RUNS_PER_DAY} runs/day, "
          f"MAX_MODEL_CALLS_PER_RUN={result['max_calls_per_run_setting']}")
    print()
    print(f"  Estimated calls per run:   {result['calls_per_run']:.1f}")
    print(f"  Estimated calls per day:   {result['calls_per_day']:.0f}")
    print(f"  Assumed free-tier RPD:     {result['free_tier_rpd']}")
    if result["headroom_pct"] is not None:
        if result["headroom_pct"] >= 0:
            print(f"  Headroom:                  {result['headroom_pct']:.0f}% under the daily limit")
        else:
            print(f"  OVER BUDGET by {-result['headroom_pct']:.0f}% -- lower MAX_MODEL_CALLS_PER_RUN "
                  f"in .env, or the postings-per-run assumption is too high")
    print()
    print("Also relevant: the free tier has a PER-MINUTE limit too, so a run that fires")
    print("many calls back-to-back can 429 well before the daily count is reached. A")
    print("failed call is retried automatically on the next run (see")
    print("db.py::postings_needing_scoring), so occasional 429s are not data loss --")
    print("but frequent ones mean MAX_MODEL_CALLS_PER_RUN should come down.")
    print()
    print("Once real runs exist, check actual call counts against real 429s in")
    print("logs/*.log rather than trusting this pre-launch estimate.")


if __name__ == "__main__":
    main()
