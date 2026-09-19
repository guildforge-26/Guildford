"""Runaway and loop protection.

Every mechanism the build spec calls for lives in one place so it can be
tested in isolation: STOP kill switch, run lock, wall-clock timeout,
per-source retry cap, circuit breaker, and daily/monthly spend caps.
Nothing here sends anything outbound -- that's alerts/*.py, gated by these.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, TypeVar
from zoneinfo import ZoneInfo

import psutil

from . import db as dbmod
from .config import Settings

T = TypeVar("T")


class StopRequested(Exception):
    """Raised when a STOP file is present. Halts the run immediately."""


class LockHeld(Exception):
    """Raised when another run already holds the pipeline lock."""


class TimeoutExceeded(Exception):
    """Raised when a run exceeds its wall-clock budget."""


class SpendCapExceeded(Exception):
    """Raised when a scoring call would exceed the daily or monthly spend cap."""


def check_stop(settings: Settings) -> None:
    if settings.stop_path.exists():
        raise StopRequested(f"STOP file present at {settings.stop_path}; halting run.")


@contextmanager
def pipeline_lock(settings: Settings):
    """Filesystem lock so two runs never overlap. Non-blocking: raises LockHeld immediately.

    Cross-platform by design (this runs on Windows via Task Scheduler as
    often as it runs on Linux/macOS via cron): uses atomic file creation
    (O_CREAT | O_EXCL), not fcntl.flock, which doesn't exist on Windows.
    A lock left behind by a crashed run is detected as stale by checking
    whether its recorded PID is still alive (psutil, cross-platform) and
    cleared automatically -- fcntl's advisory lock used to do this for
    free by releasing when its owning process died; this replaces that
    guarantee explicitly.
    """
    settings.lock_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.lock_path.exists():
        try:
            existing_pid = int(settings.lock_path.read_text().strip())
        except (ValueError, OSError):
            existing_pid = None
        if existing_pid is not None and psutil.pid_exists(existing_pid):
            raise LockHeld(f"Another run (pid {existing_pid}) holds the lock at {settings.lock_path}")
        settings.lock_path.unlink(missing_ok=True)  # stale lock from a crashed run

    try:
        fd = os.open(settings.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise LockHeld(f"Another run holds the lock at {settings.lock_path}")

    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        settings.lock_path.unlink(missing_ok=True)


class RunTimer:
    """Wall-clock budget for a single run. Call .check() between units of work."""

    def __init__(self, max_seconds: int):
        self.max_seconds = max_seconds
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def check(self) -> None:
        if self.elapsed() > self.max_seconds:
            raise TimeoutExceeded(f"Run exceeded its {self.max_seconds}s wall-clock budget")


def with_retries(func: Callable[[], T], *, max_retries: int, logger=None, source: str = "") -> T:
    """Run func with up to max_retries attempts. Re-raises the last exception on total failure."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - intentionally broad, this is the retry boundary
            last_exc = exc
            if logger is not None:
                logger.warning(
                    f"{source} attempt {attempt}/{max_retries} failed: {exc}",
                    extra={"fields": {"source": source, "attempt": attempt, "error": str(exc)}},
                )
    assert last_exc is not None
    raise last_exc


class ModelCallBudget:
    """Caps the number of scoring calls in a single run."""

    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.used = 0

    def can_call(self) -> bool:
        return self.used < self.max_calls

    def record_call(self) -> None:
        self.used += 1


class CircuitBreaker:
    """Pauses a source after repeated failures; source stays paused for a cooldown window."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings):
        self.conn = conn
        self.settings = settings

    def is_paused(self, source: str) -> bool:
        health = dbmod.get_source_health(self.conn, source)
        if not health or not health["paused_until"]:
            return False
        return datetime.fromisoformat(health["paused_until"]) > datetime.now(timezone.utc)

    def record_success(self, source: str) -> None:
        dbmod.record_source_success(self.conn, source)

    def record_failure(self, source: str, error: str) -> bool:
        """Returns True if this failure just tripped the breaker (source now paused)."""
        health = dbmod.get_source_health(self.conn, source)
        current = health["consecutive_failures"] if health else 0
        new_count = current + 1
        paused_until_iso = None
        tripped = False
        if new_count >= self.settings.circuit_breaker_failure_threshold:
            paused_until_iso = (
                datetime.now(timezone.utc) + timedelta(hours=self.settings.circuit_breaker_cooldown_hours)
            ).isoformat()
            tripped = True
        dbmod.record_source_failure(self.conn, source, str(error), paused_until_iso)
        return tripped


class SpendGuard:
    """Enforces daily and monthly scoring-spend caps against the spend_ledger table."""

    def __init__(self, conn: sqlite3.Connection, settings: Settings):
        self.conn = conn
        self.settings = settings

    def _now_local(self) -> datetime:
        return datetime.now(ZoneInfo(self.settings.timezone))

    def today(self) -> str:
        return self._now_local().strftime("%Y-%m-%d")

    def month(self) -> str:
        return self._now_local().strftime("%Y-%m")

    def daily_spent(self) -> float:
        return dbmod.get_spend(self.conn, "day", self.today())

    def monthly_spent(self) -> float:
        return dbmod.get_spend(self.conn, "month", self.month())

    def can_spend(self, estimated_cost_usd: float) -> bool:
        return (
            self.daily_spent() + estimated_cost_usd <= self.settings.daily_spend_cap_usd
            and self.monthly_spent() + estimated_cost_usd <= self.settings.monthly_spend_cap_usd
        )

    def record(self, run_id: str, posting_id: str, cost_usd: float) -> None:
        dbmod.record_spend(self.conn, run_id, posting_id, self.today(), self.month(), cost_usd)
