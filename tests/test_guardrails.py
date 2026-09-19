import time

import pytest

from jobalerts.guardrails import (
    CircuitBreaker,
    LockHeld,
    ModelCallBudget,
    RunTimer,
    SpendGuard,
    StopRequested,
    TimeoutExceeded,
    check_stop,
    pipeline_lock,
    with_retries,
)


def test_check_stop_raises_when_stop_file_present(settings):
    settings.stop_path.write_text("stop")
    with pytest.raises(StopRequested):
        check_stop(settings)


def test_check_stop_ok_when_absent(settings):
    check_stop(settings)  # should not raise


def test_pipeline_lock_blocks_concurrent_runs(settings):
    with pipeline_lock(settings):
        with pytest.raises(LockHeld):
            with pipeline_lock(settings):
                pass  # pragma: no cover


def test_pipeline_lock_released_after_context(settings):
    with pipeline_lock(settings):
        pass
    with pipeline_lock(settings):
        pass  # second acquisition must succeed now that the first released it


def test_run_timer_raises_after_budget_exceeded():
    timer = RunTimer(max_seconds=0)
    time.sleep(0.01)
    with pytest.raises(TimeoutExceeded):
        timer.check()


def test_run_timer_ok_within_budget():
    timer = RunTimer(max_seconds=60)
    timer.check()  # should not raise


def test_with_retries_succeeds_after_transient_failures():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("transient")
        return "ok"

    assert with_retries(flaky, max_retries=3, source="test") == "ok"
    assert calls["count"] == 3


def test_with_retries_reraises_after_exhausting_attempts():
    def always_fails():
        raise RuntimeError("permanent")

    with pytest.raises(RuntimeError):
        with_retries(always_fails, max_retries=2, source="test")


def test_model_call_budget_caps_calls():
    budget = ModelCallBudget(max_calls=2)
    assert budget.can_call() is True
    budget.record_call()
    assert budget.can_call() is True
    budget.record_call()
    assert budget.can_call() is False


def test_circuit_breaker_trips_after_threshold_failures(conn, settings):
    breaker = CircuitBreaker(conn, settings)
    assert breaker.is_paused("adzuna") is False
    tripped = False
    for _ in range(settings.circuit_breaker_failure_threshold):
        tripped = breaker.record_failure("adzuna", "boom")
    assert tripped is True
    assert breaker.is_paused("adzuna") is True


def test_circuit_breaker_success_resets_failure_count(conn, settings):
    breaker = CircuitBreaker(conn, settings)
    breaker.record_failure("adzuna", "boom")
    breaker.record_success("adzuna")
    assert breaker.is_paused("adzuna") is False
    # should take a full threshold of NEW failures to trip again
    for _ in range(settings.circuit_breaker_failure_threshold - 1):
        assert breaker.record_failure("adzuna", "boom") is False
    assert breaker.record_failure("adzuna", "boom") is True


def test_spend_guard_blocks_when_daily_cap_would_be_exceeded(conn, settings):
    settings2 = settings
    guard = SpendGuard(conn, settings2)
    assert guard.can_spend(settings2.daily_spend_cap_usd - 0.01) is True
    guard.record("run1", "posting1", settings2.daily_spend_cap_usd - 0.01)
    assert guard.can_spend(0.02) is False
