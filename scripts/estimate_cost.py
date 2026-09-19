#!/usr/bin/env python3
"""Estimates scoring cost per run and per month BEFORE you turn on the
schedule. Adjust the assumptions below (or pass them as flags) to match
reality once you've seen a few real runs' token counts in the logs.

Usage:
    python scripts/estimate_cost.py
    python scripts/estimate_cost.py --postings-per-run 8 --cache-hit-rate 0.7
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jobalerts.config import get_settings  # noqa: E402

RUNS_PER_DAY = 6  # every 4 hours
DAYS_PER_MONTH = 30

# Rough token-size assumptions for one scoring call (see docs/adr/ADR-002).
SYSTEM_PROMPT_TOKENS = 1800  # briefing.txt + instructions, identical every call -> cacheable
POSTING_TOKENS = 2200        # enriched posting text + fields
OUTPUT_TOKENS = 600          # the JSON response


def estimate(postings_per_run: float, cache_hit_rate: float) -> dict:
    settings = get_settings()
    pricing = settings.pricing

    # First call of a run: system prompt is a fresh cache write.
    # Later calls in the same run (and calls in later runs within the cache
    # TTL): system prompt is served from cache at cache_hit_rate.
    def call_cost(is_cache_write: bool, is_cache_hit: bool) -> float:
        input_cost = (POSTING_TOKENS / 1_000_000) * pricing["input_per_mtok"]
        output_cost = (OUTPUT_TOKENS / 1_000_000) * pricing["output_per_mtok"]
        if is_cache_write:
            sys_cost = (SYSTEM_PROMPT_TOKENS / 1_000_000) * pricing["input_per_mtok"] * pricing["cache_write_5m_multiplier"]
        elif is_cache_hit:
            sys_cost = (SYSTEM_PROMPT_TOKENS / 1_000_000) * pricing["input_per_mtok"] * pricing["cache_read_multiplier"]
        else:
            sys_cost = (SYSTEM_PROMPT_TOKENS / 1_000_000) * pricing["input_per_mtok"]
        return input_cost + output_cost + sys_cost

    first_call = call_cost(is_cache_write=True, is_cache_hit=False)
    later_call_hit = call_cost(is_cache_write=False, is_cache_hit=True)
    later_call_miss = call_cost(is_cache_write=False, is_cache_hit=False)
    later_call_avg = cache_hit_rate * later_call_hit + (1 - cache_hit_rate) * later_call_miss

    remaining = max(postings_per_run - 1, 0)
    per_run_cost = first_call + remaining * later_call_avg if postings_per_run > 0 else 0.0
    per_day_cost = per_run_cost * RUNS_PER_DAY
    per_month_cost = per_day_cost * DAYS_PER_MONTH

    return {
        "model": settings.claude_model,
        "per_call_first": first_call,
        "per_call_later_avg": later_call_avg,
        "per_run": per_run_cost,
        "per_day": per_day_cost,
        "per_month": per_month_cost,
        "daily_cap": settings.daily_spend_cap_usd,
        "monthly_cap": settings.monthly_spend_cap_usd,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postings-per-run", type=float, default=5.0,
                         help="Average NEW postings scored per 4-hour run after dedupe/prefilter (default: 5)")
    parser.add_argument("--cache-hit-rate", type=float, default=0.6,
                         help="Fraction of non-first calls that hit the system-prompt cache (default: 0.6)")
    args = parser.parse_args()

    result = estimate(args.postings_per_run, args.cache_hit_rate)

    print(f"Model: {result['model']}")
    print(f"Assumptions: {args.postings_per_run:.1f} postings scored per run, {RUNS_PER_DAY} runs/day, "
          f"{args.cache_hit_rate:.0%} cache-hit rate on non-first calls per run")
    print()
    print(f"  First call in a run (cache write):  ${result['per_call_first']:.4f}")
    print(f"  Later calls, avg w/ cache hits:      ${result['per_call_later_avg']:.4f}")
    print(f"  Estimated cost per run:              ${result['per_run']:.4f}")
    print(f"  Estimated cost per day:              ${result['per_day']:.2f}   (cap: ${result['daily_cap']:.2f})")
    print(f"  Estimated cost per month:             ${result['per_month']:.2f}   (cap: ${result['monthly_cap']:.2f})")
    print()
    print("These are pre-launch estimates from assumed token sizes. Once real runs")
    print("have happened, prefer actual numbers from `jobs list today` / the runs")
    print("table / logs/*.log, which log real cost_usd per call.")


if __name__ == "__main__":
    main()
