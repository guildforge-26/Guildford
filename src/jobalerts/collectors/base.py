"""Shared runner that wraps every collector with retries + the circuit breaker.

A collector's fetch_fn takes no args and returns a list of raw posting dicts
with keys: title, company, location, url, salary_text, posted_at, source,
source_id. run_collector never raises -- a fully failed source logs an
error and returns an empty list, per hard rule 5 ("if a source fails, log
it, keep going").
"""
from __future__ import annotations

from typing import Callable

from ..guardrails import CircuitBreaker, with_retries
from ..logging_utils import log_fields


def run_collector(
    source: str,
    fetch_fn: Callable[[], list[dict]],
    *,
    circuit_breaker: CircuitBreaker,
    max_retries: int,
    logger,
) -> list[dict]:
    if circuit_breaker.is_paused(source):
        logger.info(f"{source} is paused by the circuit breaker, skipping", extra=log_fields(source=source, event="collector_skipped_paused"))
        return []

    try:
        postings = with_retries(fetch_fn, max_retries=max_retries, logger=logger, source=source)
    except Exception as exc:  # noqa: BLE001 - top-level collector boundary, must not crash the run
        tripped = circuit_breaker.record_failure(source, str(exc))
        logger.error(
            f"{source} failed after retries: {exc}",
            extra=log_fields(source=source, event="collector_failed", error=str(exc), circuit_tripped=tripped),
        )
        return []

    circuit_breaker.record_success(source)
    logger.info(
        f"{source} collected {len(postings)} postings",
        extra=log_fields(source=source, event="collector_success", count=len(postings)),
    )
    return postings
